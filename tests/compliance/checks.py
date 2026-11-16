# SPDX-License-Identifier: Apache-2.0
"""Pure checks behind the compliance gate.

Each function takes plain data and returns a list of human-readable problems.
An empty list means the check passed. Keeping them pure lets the tests prove
that every check both passes on good input and fails on bad input.
"""

import json
import re
from collections.abc import Iterable, Iterator
from pathlib import Path, PurePosixPath

DISCLAIMER = (
    "Disclaimer: This is an independent personal project. It is not affiliated with, "
    "endorsed by, or sponsored by Anduril Industries. Anduril and Lattice are trademarks "
    "of Anduril Industries, Inc. This repository does not contain or redistribute the "
    "Lattice SDK; it is installed from Anduril's official package registries under "
    "Anduril's SDK License Agreement."
)

DATA_NOTICE = (
    "Vessel data provided by aisstream.io. Aircraft data comes from the owner's own ADS-B "
    "receiver, decoded with readsb. No live data is stored in or distributed from this "
    "repository."
)

MMSI_MIN = 999_000_000
MMSI_MAX = 999_999_999
FIXTURE_SUFFIXES = frozenset({".json", ".jsonl", ".ndjson"})
FIXTURE_DOCS = frozenset({"README.md"})

_SYNTHETIC_HEX = re.compile(r"^~?ffff[0-9a-f]*$")
_SDK_PATH = re.compile(r"lattice[_-]sdk", re.IGNORECASE)
_PUSH_PATTERNS = {
    "docker push": re.compile(r"docker\s+push", re.IGNORECASE),
    "push: true": re.compile(r"push\s*:\s*['\"]?true", re.IGNORECASE),
    "packages: write": re.compile(r"packages\s*:\s*['\"]?write", re.IGNORECASE),
}
_MMSI_KEYS = frozenset({"mmsi", "mmsi_string", "userid", "user_id"})
_HEX_KEYS = frozenset({"hex", "icao", "icao24", "icao_hex"})


def normalize(text: str) -> str:
    """Collapse Markdown quoting and line wrapping so wording can be compared exactly."""
    unquoted = re.sub(r"^\s*>\s?", "", text, flags=re.MULTILINE)
    return " ".join(unquoted.split())


def missing_notices(text: str, required: Iterable[str]) -> list[str]:
    """Return the required notices that do not appear word for word in ``text``."""
    haystack = normalize(text)
    return [notice for notice in required if normalize(notice) not in haystack]


def sdk_path_problems(paths: Iterable[str]) -> list[str]:
    """Flag tracked paths that look like vendored SDK code or packaged artifacts.

    The requirements allow ``lattice-sdk`` to appear in dependency manifests and
    lock files. That is about file contents; no manifest has it in its path, so
    path matching needs no exemption and a vendored ``lattice-sdk/package.json``
    is still caught.
    """
    problems: list[str] = []
    for raw in paths:
        path = PurePosixPath(raw)
        lowered = [part.lower() for part in path.parts]
        if "anduril" in lowered:
            problems.append(f"{raw}: inside a directory named 'anduril'")
        if _SDK_PATH.search(raw):
            problems.append(f"{raw}: path names the Lattice SDK")
        if "node_modules" in lowered:
            problems.append(f"{raw}: inside node_modules/")
        if raw.lower().endswith((".whl", ".tar.gz")):
            problems.append(f"{raw}: packaged artifact (*.whl or *.tar.gz)")
    return problems


def workflow_push_problems(name: str, text: str) -> list[str]:
    """Flag anything in a workflow file that could publish a container image."""
    return [
        f"{name}: contains '{label}'"
        for label, pattern in _PUSH_PATTERNS.items()
        if pattern.search(text)
    ]


_SDK_CACHE_PATTERN = re.compile(r"^\s*enable-cache:\s*[\"']?true", re.IGNORECASE | re.MULTILINE)


def workflow_cache_problems(name: str, text: str) -> list[str]:
    """Flag a workflow that keeps installed packages in the Actions cache.

    The cache would hold a copy of the Lattice SDK.
    """
    if _SDK_CACHE_PATTERN.search(text):
        return [f"{name}: the package cache is on, which stores a copy of the Lattice SDK"]
    return []


def _walk(node: object) -> Iterator[tuple[str, object]]:
    """Yield every ``(key, value)`` pair found anywhere inside parsed JSON."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key), value
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def fixture_value_problems(document: object) -> list[str]:
    """Flag MMSIs and ICAO hex codes in parsed fixture data that are not provably synthetic."""
    problems: list[str] = []
    for key, value in _walk(document):
        lowered = key.lower()
        if lowered in _MMSI_KEYS:
            text = str(value).strip()
            if not (text.isdigit() and MMSI_MIN <= int(text) <= MMSI_MAX):
                problems.append(f"{key}={value!r} is outside {MMSI_MIN}-{MMSI_MAX}")
        elif lowered in _HEX_KEYS and not _SYNTHETIC_HEX.match(str(value).strip().lower()):
            problems.append(f"{key}={value!r} does not start with 'ffff'")
    return problems


def fixture_file_problems(path: Path) -> list[str]:
    """Check one fixture file: allowed type, parseable, and synthetic identifiers only."""
    if path.name in FIXTURE_DOCS:
        return []
    if path.suffix not in FIXTURE_SUFFIXES:
        return [f"{path.name}: only {sorted(FIXTURE_SUFFIXES)} fixtures are allowed"]
    text = path.read_text(encoding="utf-8")
    chunks = [text] if path.suffix == ".json" else [ln for ln in text.splitlines() if ln.strip()]
    problems: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        try:
            document = json.loads(chunk)
        except json.JSONDecodeError as exc:
            problems.append(f"{path.name}:{index}: not valid JSON ({exc.msg})")
            continue
        problems.extend(f"{path.name}:{index}: {p}" for p in fixture_value_problems(document))
    return problems


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "[::1]", "::1"})


def _port_host(port: object) -> str | None:
    """Return the host address a Compose port entry binds to, or None if it has none."""
    if isinstance(port, dict):
        host = port.get("host_ip")
        return str(host) if host else None
    text = str(port)
    if text.startswith("["):
        return text.split("]", 1)[0] + "]"
    parts = text.split(":")
    # "host_ip:host_port:container_port" is the only short form that names an address.
    return parts[0] if len(parts) >= 3 else None


def compose_exposure_problems(compose: object) -> list[str]:
    """Flag Compose services reachable beyond this machine.

    Every published port must name a loopback address. Host networking is
    refused outright, because it publishes every port a container opens.
    """
    problems: list[str] = []
    services = compose.get("services", {}) if isinstance(compose, dict) else {}
    for name, service in services.items():
        if not isinstance(service, dict):
            continue
        if service.get("network_mode") == "host":
            problems.append(f"{name}: uses host networking")
        for port in service.get("ports") or []:
            host = _port_host(port)
            if host not in _LOOPBACK_HOSTS:
                problems.append(f"{name}: port {port!r} is not bound to 127.0.0.1")
    return problems
