# Lattice-COP build plan

Source of truth: the owner's requirements doc (2026-11-14). This file tracks
progress through its eight phases. A phase is not started until the previous
gate passes or the owner approves skipping it. Differences between the
requirements and current vendor docs are logged in [DECISIONS.md](DECISIONS.md).

## Working rules

- Commit after every task, push after every commit, directly on `main`,
  Conventional Commit messages.
- Never commit secrets, `.env`, live AIS/ADS-B data, or any Lattice SDK source.
- Tests never touch the network; fixtures are synthetic (MMSI `999xxxxxx`,
  ICAO hex `ffffxx`).
- Stop and ask the owner at every stop-and-ask point (listed at the bottom).

## Phases

### Phase 0: Repo and CI scaffold
- [x] `.gitattributes`, `.gitignore`, `.dockerignore`, `.env.example`
- [x] `pyproject.toml` (uv, Python 3.14), lock file, placeholder package and test
- [x] Confirm `anduril-lattice-sdk` and all dependencies install and import on 3.14
- [x] pre-commit hooks, Dependabot, CI workflow (lint, types, test, secrets,
      deps, images, docs, compliance, release)
- [x] Compliance pytest module (disclaimer, SDK files, image pushes, fixtures)
- [x] `Dockerfile` (multi-stage, `python:3.14-slim` by digest, non-root) and a
      Compose skeleton with the `sdr` profile
- [ ] USB container test to choose Docker Path A or B. Blocked on the owner:
      install usbipd-win, plug in the dongle, run `scripts/windows/attach-sdr.ps1`,
      then `scripts/wsl/preflight.sh`. First try (2026-11-14): no dongle visible in WSL2.
- [x] **Gate:** CI green on the placeholder package; image builds; CVE scan passes
      (run 43634056851, commit `2c57318`, 2026-11-14)

### Phase 1: Lattice and visualizer smoke test
- [x] `config.py` (pydantic-settings, `SecretStr`), Lattice client setup per the
      REST AIS sample, sandbox header; `scripts/check-env.py`
- [x] `smoke-test` command: one synthetic vessel (MMSI 999000001), 5-minute expiry
      (unit-tested against mocked HTTP; not yet run against a real environment)
- [ ] `visualizer` service: upstream app cloned at a pinned commit, bound to 127.0.0.1
      (waiting on the owner's reading of the app's licence; see DECISIONS.md)
- [ ] Check `http://127.0.0.1:5173` opens from a Windows browser
- [ ] **Gate:** vessel appears at the right spot, then expires; owner confirms

### Phase 2: AISStream connection
- [ ] WebSocket client, subscription within 3 s, single connection
- [ ] Reconnect with exponential backoff and jitter (2 s to 60 s)
- [ ] 60 s counters by message type; no publishing yet
- [ ] **Gate:** 15 minutes connected with AOI position reports; forced disconnect recovers

### Phase 3: RTL-SDR and signal gate
- [ ] `readsb` service (profile `sdr`), tar1090 on 127.0.0.1:8080
- [ ] `sdr-check` command and pass/fail report
- [x] `attach-sdr.ps1`, `detach-sdr.ps1`, `preflight.sh` (written early, for the Phase 0 USB test)
- [ ] **Gate:** report passes and owner sees aircraft in tar1090

### Phase 4: Data cleaning
- [ ] AIS rules, ADS-B rules, each a pure function with unit tests
- [ ] Synthetic replay file with expected keep/drop counts
- [ ] **Gate:** clean-module coverage of 95% or more; replay counts match

### Phase 5: Lattice conversion and publishing
- [ ] `geo.py` conversions, `entity.py` mapping, `publisher.py` (throttle, retries)
- [ ] Both ingest services wired end to end, deterministic entity IDs
- [ ] **Gate:** 30 minutes with no publish errors beyond retried transients

### Phase 6: Visual verification
- [ ] Icons, names, headings, expiry, no duplicates
- [ ] Screenshots to `docs/img/` only after owner approval
- [ ] **Gate:** owner sign-off

### Phase 7: Docs and hardening
- [ ] README to the documentation checklist; `docs/TROUBLESHOOTING.md`
- [ ] 2-hour soak test: flat memory, no crash loops
- [ ] **Gate:** definition of done met

## Stop-and-ask points

- Final project license; switching to Docker Path B (Phase 0)
- A dependency does not support Python 3.14 (Phase 0)
- The visualizer's `LICENSE.md` forbids or limits cloning it into a build (Phase 1)
- Any physical step: dongle, admin PowerShell, antenna, screenshots
- Signal gate fails; switching to ADS-B Exchange (Phase 3)
- A HIGH or CRITICAL CVE with no fix (`.trivyignore` entry needs approval)
- Anything that would publish an image, store live data, or expose a service
  beyond 127.0.0.1
