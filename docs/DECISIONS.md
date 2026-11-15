# Decision log

Short, dated notes on choices made during the build and on places where the
requirements doc and current vendor docs disagree (vendor docs win).

## 2026-11-14

- **Visualizer variable names.** The requirements name four variables
  including `VITE_SANDBOX_TOKEN`. The upstream app (commit `439255e`) reads
  five: `VITE_LATTICE_URL`, `VITE_LATTICE_BEARER_TOKEN`,
  `VITE_LATTICE_CLIENT_ID`, `VITE_LATTICE_CLIENT_SECRET` and
  `VITE_LATTICE_SANDBOX_TOKEN`. Compose maps the upstream names. Bearer token
  and client credentials are mutually exclusive in the app.
- **`LATTICE_URL` is a bare hostname.** Both the REST AIS sample and the
  visualizer expect the endpoint without a scheme
  (`lattice-<id>.env.sandboxes.developer.anduril.com`). Our config accepts
  either form and strips the scheme.
- **Visualizer runs the Vite dev server.** Upstream only documents
  `npm run dev`, and its `vite.config.ts` proxies Lattice calls through the
  dev server. So the browser talks to the visualizer container, which
  forwards to Lattice. The requirements' diagram showed the browser calling
  Lattice directly; the README diagram follows the real path.
- **Visualizer SDK package.** The app uses Buf-generated types
  (`@buf/anduril_lattice-sdk.bufbuild_es`, from the Buf registry), not
  `@anduril-industries/lattice-sdk` from npm. Same rule applies: installed at
  build time, never committed.
- **Visualizer licence.** Its `LICENSE.md` is the Anduril Lattice SDK License
  Agreement (updated 2026-07-31). It does not forbid cloning, but it does
  forbid modifying and redistributing. Plan: clone at a pinned commit at build
  time, run it unmodified, never push the image. Owner to confirm (Phase 1
  stop-and-ask).
- **SDK version.** `anduril-lattice-sdk` 5.5.0 (2026-11-09) declares Python
  3.14 support. The REST sample pins 5.4.0.
- **Virtualenv outside the repo.** The repo lives on a OneDrive-synced Windows
  drive, where a `.venv` is slow and symlinks are unreliable. Development uses
  `UV_PROJECT_ENVIRONMENT=$HOME/.venvs/lattice-cop`.
- **Commit identity.** Commits use the owner's GitHub noreply address so a
  personal email is not published in a public repo.
- **Coverage badge.** No Codecov account is used. The README badge is a static
  "enforced in CI" badge; the real number is in each CI run's job summary, and
  `fail_under = 90` in `pyproject.toml` is the gate.
- **pip removed from the runtime image.** Trivy flagged fixable HIGH findings
  in libraries bundled inside pip (msgpack, urllib3, setuptools). Nothing
  installs packages at run time, so the runtime stage uninstalls pip. The same
  stage runs `apt-get upgrade` to pick up Debian fixes newer than the pinned
  base digest.
- **gitleaks runs from its pinned container image**, not the marketplace
  action. The action scans only the pushed commits on push events; the
  requirement is the full history.
- **pip-audit gate is "has a fix".** pip-audit has no fix-only switch, so CI
  reads its JSON report and fails only on vulnerabilities with a fix version.
  All findings are still printed in the job summary. Dev dependencies are
  audited too.
- **Synthetic non-ICAO hex.** The compliance check accepts `~ffff..` as well
  as `ffff..`, so the TIS-B (`~` prefix) cleaning rule can have fixtures.
- **SDK path check has no manifest exemption.** The check on tracked paths
  flags any path naming the SDK. No dependency manifest has the SDK in its
  path, so an exemption would only weaken the check.
- **Placeholder license.** Apache-2.0, copyright 2026 Brett Waugh, pending the
  owner's final choice (stop-and-ask).
- **`ADSBX_MONTHLY_QUOTA` added.** The requirements ask for the poll interval
  to be validated against the plan's monthly quota, but list no variable for
  the quota. It is required only when `ADSB_SOURCE=adsbx`.
- **Per-service required settings.** One `Settings` model serves every
  command. Lattice settings are always required. `AISSTREAM_API_KEY` and the
  receiver location are checked by the commands that need them, so the smoke
  test and `adsb-ingest` do not demand an AISStream key.
- **Empty values mean "unset".** Compose passes `KEY=` lines through as empty
  strings, so settings ignore empty values and fall back to defaults.
- **SDK retries.** The SDK retries 408, 409, 429 and 5xx itself (two retries
  by default). The Phase 5 publisher will set `max_retries=0` and do its own
  backoff, because the requirements say never to retry other 4xx errors.
- **API error logging.** `ApiError`'s string form includes response headers.
  We log only the status code and body.
- **Publish route.** SDK 5.5.0 publishes with `PUT /api/v1/entities`. Tests
  mock that route with respx.
- **Visualizer approved.** The owner approved cloning the Entity Visualizer
  at pinned commit `439255e` at build time and running it unmodified
  (2026-11-14). `docker/visualizer/Dockerfile` fetches it with BuildKit's git
  `ADD`, so no upstream code is ever in this repository.
- **Visualizer runs `vite` directly.** Upstream's `npm run dev` script is just
  `vite`. The image starts the same binary with `--host 0.0.0.0 --port 5173`
  so Compose can publish it on 127.0.0.1, and removes npm, npx, corepack and
  yarn from the runtime stage (not needed at run time; they carry CVEs).
- **Visualizer credentials are passed at run time.** Vite's dev server reads
  `VITE_*` from the container environment, so Compose maps them from the
  `LATTICE_*` values in `.env`. Nothing secret is baked into the image.
- **Compose requires `LATTICE_URL`.** With an empty hostname the upstream
  dev server crash-loops on a bad proxy URL. Compose now stops with a clear
  message instead. CI sets a placeholder hostname.
- **Loopback-only check.** The compliance tests fail if any Compose service
  publishes a port on anything but 127.0.0.1, or uses host networking.
- **Smoke test and unreachable environments.** The first live run
  (2026-11-14) found the owner's previous Sandboxes environment resetting TLS
  connections, and the command printed a traceback. It now logs one JSON error
  line for transport failures. The live gate waits for a new environment.
- **Live smoke test passed (2026-11-15).** Against the owner's new Sandboxes
  environment the synthetic vessel was published and read back as live. The
  first try used the value labelled "environment token", which Lattice
  rejected as "not a valid JWT"; it was a copy of the client secret. The
  client ID and secret worked.
- **AISStream message shape (docs checked 2026-11-15).** The current docs
  show `MetaData.Latitude` / `MetaData.Longitude` with capital letters; older
  payloads used lower case. The client reads the typed body
  (`Message.<type>.Latitude` / `Longitude`) first and accepts either case in
  `MetaData` as a fallback.
- **AISStream sends binary frames.** Each frame is UTF-8 JSON in a binary
  WebSocket frame. The client accepts binary and text.
- **Subscription confirmation and compression.** AISStream answers a valid
  subscription with `SubscriptionConfirmation` and `CompressionEnabled`. Its
  docs say uncompressed connections have been bandwidth-limited since
  September 2026. The client always offers permessage-deflate and logs a
  warning if the confirmation says compression is off.
- **No documented AISStream error format.** The docs only say the connection
  closes (late or malformed subscription, invalid key, connection limit, slow
  reader). The client treats any close as a reason to reconnect with backoff,
  and also logs a top-level `error` field if one arrives, with the API key
  removed. A wrong key therefore shows up as repeated reconnects that never
  receive data, backing off to one try a minute.
- **Backoff formula.** The ceiling doubles from 2 s to 60 s; the delay is a
  random point in the top half of the ceiling, never under 2 s. The attempt
  counter resets once a subscribed AIS message arrives, not on connect, so a
  server that accepts and then drops connections is still backed off.
- **AOI counter in Phase 2.** Position reports are counted as inside or
  outside the AOI so the gate can be read from the logs. This is a counter
  only; the real cleaning rules arrive in Phase 4.
- **Logs carry counts only.** The AIS client never logs MMSIs, names or
  positions, so container logs do not become a store of live data.
- **Mock AISStream server in tests.** One test starts a WebSocket server on
  127.0.0.1 to exercise the real library (handshake, compression, forced
  disconnect, reconnect). It never leaves loopback; every other test uses
  fake connections.
- **websockets 17.** The dependency range is now `>=15,<18` and the lock file
  pins 17.4 (Dependabot's pull request 2), tested against the new client.
- **Docker Path A confirmed (2026-11-15).** With the dongle attached through
  usbipd-win, `scripts/wsl/preflight.sh` sees USB ID 0bda:2838 both in Ubuntu
  and inside a container on Docker Desktop. No switch to Docker Engine (Path
  B) is needed.
- **Phase 1 gate passed (2026-11-15).** The owner's screenshot shows the
  smoke test vessel in the middle of Tampa Bay. The screenshot is not in the
  repository; screenshots go to `docs/img/` only in Phase 6, after approval.
  Expiry was confirmed through the API: the entity returns 404 once expired.
- **Phase 2 gate passed (2026-11-15).** Live run from 16:01 to 16:24 UTC in
  the Compose container. All four message types arrived (30 to 45 messages a
  minute), with no invalid frames, no server errors and no positions outside
  the AOI. The forced disconnect was `docker network disconnect` for 75 s:
  the keepalive ping timed out after about 30 s, five retries backed off from
  2 s to 32 s, and the client re-subscribed 12 s after the network returned.
  AISStream confirmed compression on both connections. Only counts were
  logged; no live data was kept.
- **Module layout.** The AISStream client moved to `sources/aisstream.py` and
  the AOI box to `geo.py`, the names the requirements give.
- **readsb image.** `ghcr.io/sdr-enthusiasts/docker-adsb-ultrafeeder`, pinned
  by digest (image built 2026-11-10, readsb 3.16.21), run unmodified. Its
  licence file is GPL-3.0; readsb is GPL-3.0-or-later and tar1090
  GPL-2.0-or-later (each checked in its repository on 2026-11-15).
- **readsb feeds nobody.** No `ULTRAFEEDER_CONFIG` or `MLAT_CONFIG` is set,
  so the container sends nothing to any aggregator; its log confirms MLAT is
  disabled and no stats package runs. `UPDATE_TAR1090=false` stops the
  start-up update download.
- **readsb stores nothing.** Graphs, heatmap and traces are off, no volume is
  mounted, and `/run`, `/var/log`, `/var/globe_history` and
  `/var/lib/collectd` are RAM disks. Everything goes when the container stops.
- **Automatic gain.** The requirements say "autogain". The image offers
  `READSB_GAIN=auto` (readsb's built-in, the upstream default and
  recommendation) and `autogain` (a legacy script that needs 90 minutes
  without a restart and keeps state on disk). We use `auto`.
- **Antenna location stays out of readsb's JSON.**
  `READSB_RX_LOCATION_ACCURACY=0` keeps the location out of the files tar1090
  serves, so the tar1090 map shows no site marker or range rings and a
  screenshot cannot give the address away. `sdr-check` gets the location from
  settings and never prints it.
- **USB passthrough keys.** Upstream's recommended `device_cgroup_rules:
  "c 189:* rwm"` plus a `/dev/bus/usb` bind mount, which survives a replug.
  The container is not privileged. `cap_drop: ALL` and `read_only` are not
  set: the image runs s6-overlay as root and upstream documents neither.
- **aircraft.json path.** `http://readsb/data/aircraft.json` inside the
  Compose network, as `.env.example` assumed; confirmed against the image.
- **sdr-check measurements.** Addresses starting with `~` (non-ICAO) are
  ignored. An aircraft counts for the AOI and range checks only while its
  position is under 15 s old; ranges beyond 300 nm are treated as decoding
  errors. A readsb restart is a falling `messages` counter. A dropout is a
  failed fetch, or five polls in a row without a newer file; each outage
  counts once. A run stopped early always fails.
- **sdr-check settings.** `SDR_CHECK_MINUTES`, `SDR_CHECK_MIN_AIRCRAFT`,
  `SDR_CHECK_MAX_MEDIAN_SEEN_POS` and `SDR_CHECK_MIN_RANGE_NM` hold the
  owner-tunable pass marks, with the requirements' proposed values as defaults.
- **readsb image scan.** CI scans the pinned upstream image with Trivy and
  writes the result to the job summary. It never fails the build.
- **Phase 3 gate passed (2026-11-15).** The 30-minute `sdr-check` run at
  midday passed all four marks (53 aircraft in the AOI, median position age
  2.6 s, farthest 46 nm, no dropouts or restarts) and the owner confirmed
  aircraft on tar1090. `ADSB_SOURCE` stays `receiver`. The report and the
  owner's screenshot are not in the repository.
