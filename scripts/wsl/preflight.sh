#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Checks to run in Ubuntu (WSL2) before `docker compose up`.
#
#   scripts/wsl/preflight.sh            full check, including the RTL-SDR
#   scripts/wsl/preflight.sh --no-sdr   skip the USB checks (no receiver, or ADSB_SOURCE=adsbx)
#
# Exits 0 when everything passes, 1 otherwise. It never prints secret values.
set -uo pipefail

SDR_USB_ID="${SDR_USB_ID:-0bda:2838}"
USB_TEST_IMAGE="alpine:3.22@sha256:49340b346798875b5592e5d420241f2f9cfba5f47e62ebb1446a1b34734e898f"

check_sdr=1
for arg in "$@"; do
  case "${arg}" in
    --no-sdr) check_sdr=0 ;;
    -h | --help)
      sed -n '3,9p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "unknown option: ${arg}" >&2
      exit 2
      ;;
  esac
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
env_file="${repo_root}/.env"
failures=0

pass() { printf '  [ ok ] %s\n' "$1"; }
fail() {
  printf '  [FAIL] %s\n' "$1"
  if [[ -n "${2:-}" ]]; then printf '         %s\n' "$2"; fi
  failures=$((failures + 1))
}

# Print the value of KEY from .env without sourcing the file.
env_value() {
  local key="$1" line value
  line="$(grep -E "^${key}=" "${env_file}" 2>/dev/null | tail -n 1)"
  value="${line#*=}"
  value="${value%%[[:space:]]#*}"
  value="${value%"${value##*[![:space:]]}"}"
  value="${value%\"}"
  value="${value#\"}"
  printf '%s' "${value}"
}

require_env() {
  local key
  for key in "$@"; do
    if [[ -n "$(env_value "${key}")" ]]; then
      pass "${key} is set"
    else
      fail "${key} is empty in .env"
    fi
  done
}

echo "Docker"
if ! command -v docker >/dev/null 2>&1; then
  fail "docker is not installed or not on PATH" \
    "Turn on Docker Desktop's WSL integration for Ubuntu, or install Docker Engine."
elif os="$(docker info --format '{{.OperatingSystem}}' 2>/dev/null)"; then
  pass "Docker is running (${os})"
  if docker compose version >/dev/null 2>&1; then
    pass "Docker Compose plugin is available"
  else
    fail "Docker Compose plugin is missing"
  fi
else
  fail "Docker is not running" "Start Docker Desktop (or: sudo service docker start)."
fi

echo "Settings (.env)"
if [[ ! -f "${env_file}" ]]; then
  fail ".env is missing" "Copy .env.example to .env and fill it in."
else
  pass ".env exists"
  require_env LATTICE_URL LATTICE_SANDBOXES_TOKEN AISSTREAM_API_KEY
  case "$(env_value LATTICE_URL)" in
    http://* | https://* | */*)
      fail "LATTICE_URL must be the hostname only" \
        "Remove https:// and any path. The visualizer adds the scheme itself."
      ;;
  esac
  if [[ -n "$(env_value LATTICE_ENVIRONMENT_TOKEN)" ]]; then
    pass "LATTICE_ENVIRONMENT_TOKEN is set"
  elif [[ -n "$(env_value LATTICE_CLIENT_ID)" && -n "$(env_value LATTICE_CLIENT_SECRET)" ]]; then
    pass "LATTICE_CLIENT_ID and LATTICE_CLIENT_SECRET are set"
  else
    fail "No Lattice credentials in .env" \
      "Set LATTICE_ENVIRONMENT_TOKEN, or both LATTICE_CLIENT_ID and LATTICE_CLIENT_SECRET."
  fi
  if [[ "$(env_value ADSB_SOURCE)" == "adsbx" ]]; then
    require_env ADSBX_RAPIDAPI_KEY ADSBX_POLL_SECONDS
  elif [[ "${check_sdr}" -eq 1 ]]; then
    require_env RECEIVER_LAT RECEIVER_LON RECEIVER_ALT_M
  fi
fi

if [[ "${check_sdr}" -eq 1 ]]; then
  echo "RTL-SDR (USB ID ${SDR_USB_ID})"
  if ! command -v lsusb >/dev/null 2>&1; then
    fail "lsusb is not installed" "Run: sudo apt install usbutils"
  elif lsusb | grep -qi "${SDR_USB_ID}"; then
    pass "Dongle is visible in Ubuntu"
  else
    fail "Dongle is not visible in Ubuntu" \
      "On Windows, run scripts\\windows\\attach-sdr.ps1 and keep that window open."
  fi

  if [[ ! -d /dev/bus/usb ]]; then
    fail "/dev/bus/usb does not exist, so no USB device can be passed to a container" \
      "Attach the dongle with usbipd-win first."
  elif docker run --rm --device /dev/bus/usb:/dev/bus/usb "${USB_TEST_IMAGE}" \
    sh -c 'apk add --no-cache usbutils >/dev/null 2>&1 && lsusb' 2>/dev/null \
    | grep -qi "${SDR_USB_ID}"; then
    pass "Dongle is visible inside a container"
  else
    fail "Dongle is not visible inside a container" \
      "Docker Desktop may not pass USB through. See Path B in the README."
  fi
else
  echo "RTL-SDR"
  echo "  [skip] USB checks skipped (--no-sdr)"
fi

echo
if [[ "${failures}" -eq 0 ]]; then
  echo "Preflight passed."
else
  echo "Preflight failed: ${failures} problem(s) above."
  exit 1
fi
