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
- [x] USB container test to choose Docker Path A or B (2026-11-15): after the
      owner ran `attach-sdr.ps1`, the dongle (0bda:2838) is visible in Ubuntu and
      inside a container started with `--device /dev/bus/usb`. Path A (Docker
      Desktop) stays.
- [x] **Gate:** CI green on the placeholder package; image builds; CVE scan passes
      (run 43634056851, commit `2c57318`, 2026-11-14)

### Phase 1: Lattice and visualizer smoke test
- [x] `config.py` (pydantic-settings, `SecretStr`), Lattice client setup per the
      REST AIS sample, sandbox header; `scripts/check-env.py`
- [x] `smoke-test` command: one synthetic vessel (MMSI 999000001), 5-minute expiry
      (unit-tested against mocked HTTP; not yet run against a real environment)
- [x] `visualizer` service: upstream app cloned at a pinned commit, bound to 127.0.0.1
      (owner approved 2026-11-14; serves the page; image scan clean)
- [x] Check `http://127.0.0.1:5173` opens from Windows (HTTP 200 from Windows
      PowerShell and from Ubuntu; refused on the WSL2 network address)
- [x] Live smoke test (2026-11-15, new Sandboxes environment, client ID and
      secret): the vessel was published and read back from Lattice as live,
      at the right position, with a five-minute expiry.
- [x] **Gate:** vessel appears at the right spot, then expires (2026-11-15):
      the owner's screenshot shows `LATTICE-COP SMOKE TEST` mid-bay in the
      visualizer; after expiry Lattice answers 404 for the entity.

### Phase 2: AISStream connection
- [x] WebSocket client, subscription within 3 s, single connection
- [x] Reconnect with exponential backoff and jitter (2 s to 60 s)
- [x] 60 s counters by message type; no publishing yet
- [x] `ais-ingest` runs the client and stops cleanly on SIGINT or SIGTERM
- [x] **Gate:** 15 minutes connected with AOI position reports; forced disconnect
      recovers (live run 2026-11-15, 16:01 to 16:24 UTC): 791 messages, 459
      position reports, all inside the AOI, every minute. The container's network
      was cut for 75 s; the client re-subscribed 12 s after it came back and then
      ran 16 minutes without a break. SIGTERM stopped it with exit code 0.

### Phase 3: RTL-SDR and signal gate
- [x] `readsb` service (profile `sdr`), tar1090 on 127.0.0.1:8080. Short run
      (2026-11-15): readsb found the dongle and decoded aircraft on Docker Desktop.
- [x] `sdr-check` command and pass/fail report (two-minute trial against the
      live receiver worked; the 30-minute gate needs the receiver location)
- [x] CI scans the upstream readsb image and reports it without failing the build
- [x] `attach-sdr.ps1`, `detach-sdr.ps1`, `preflight.sh` (written early, for the Phase 0 USB test)
- [x] **Gate:** report passes and owner sees aircraft in tar1090 (2026-11-15,
      17:21 to 17:51 UTC): 53 unique aircraft inside the AOI, median position
      age 2.6 s, farthest 46 nm, no dropouts or restarts in 1800 polls. The
      owner confirmed aircraft on the tar1090 map. The receiver stays the
      ADS-B source; no ADS-B Exchange fallback is needed.

### Phase 4: Data cleaning
- [x] `models.py` (one `Track` for both sources), cleaning thresholds in settings
- [x] AIS rules, ADS-B rules, each a pure function with unit tests
- [x] Publish throttle (used by the publisher in Phase 5)
- [x] Synthetic replay files with expected keep/drop counts
- [x] **Gate:** clean-module coverage of 95% or more; replay counts match
      (2026-11-15: `clean/` is at 100% branch coverage, and CI now fails below
      95%; both replays give the expected counts)

### Phase 5: Lattice conversion and publishing
- [x] `geo.py` conversions, `entity.py` mapping, `publisher.py` (throttle, retries)
- [x] Both ingest services wired end to end, deterministic entity IDs
- [x] **Gate:** 30 minutes with no publish errors beyond retried transients.
      Live run 2026-11-15, 18:16 to 18:46 UTC, no restarts, memory under 50 MiB each:
      - AIS: 636 of 636 updates published, no errors.
      - ADS-B: 3,992 published, 2 transient failures retried successfully, and
        2 updates rejected with HTTP 403 (empty body) that were not retried.
      - Lattice held exactly the aircraft readsb had fresh positions for, and
        120 live vessels.
      The two 403s are outside "retried transients". The owner accepted the
      run as it stands on 2026-11-16: the Sandboxes environment is torn down
      and provisioned again every few hours, so the odd rejected update is
      expected.

### Added at the owner's request: aircraft enrichment (2026-11-16)
- [x] readsb's built-in aircraft database switched on (type, registration,
      operator, build year)
- [x] Emitter category, squawk, emergency and priority status, barometric and
      selected altitude carried through cleaning
- [x] Lattice mapping: `ontology.specific_type`, callsign and registration
      alternate IDs, `transponder_codes`, `indicators.emergency`, a fuller
      description
- [x] Confirm against Lattice that every new field is accepted (2026-11-16,
      16:12 UTC, new environment): every aircraft inside the area read back
      from the Entities API with its type, alternate IDs, transponder codes,
      emergency flag and description as sent, and no update was rejected.
      How the Lattice UI shows them is part of the Phase 6 visual check.

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
