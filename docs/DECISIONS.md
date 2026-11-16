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
  `UV_PROJECT_ENVIRONMENT=$HOME/.venvs/tampa-cop`.
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
- **AISStream live message shape (checked 2026-11-15).** Live messages use
  lower-case `MetaData.latitude` / `longitude` (the docs show capitals) and
  carry `MetaData.time_utc` as `2026-01-01 12:00:00.123456789 +0000 UTC`.
  The cleaner takes the position from the typed message body, and parses that
  time format for the staleness rule.
- **AIS message time.** `time_utc` is when AISStream received the message. If
  it is missing or unreadable, the arrival time is used instead of dropping
  the message.
- **Position-jump slack.** `POSITION_JUMP_SLACK_NM` (default 0.1) is added to
  the distance a track may cover. Without it, two reports a fraction of a
  second apart would imply a huge speed from ordinary position noise. A jump
  never replaces the last kept position, and the rule heals by itself: once
  enough time has passed, the same position is plausible again.
- **Rule order.** AIS: invalid position, outside AOI, non-vessel MMSI, stale,
  duplicate, position jump. ADS-B: no position, stale, outside the AOI box,
  outside the radius, non-ICAO, position jump. Extra counters cover messages
  the rules cannot read (`malformed`, `unsupported`, `invalid_static`).
- **AOI box and radius for ADS-B.** An aircraft must be inside both. With the
  defaults the whole box lies within the 60 nm radius, so the box decides.
- **Unknown altitude.** An aircraft with neither geometric nor barometric
  altitude is kept at the geoid offset with "altitude unknown" in its
  description. The requirements do not cover this case.
- **Geoid offset.** The default is now -26.7 m: EGM96 gives -26.65 m at Tampa
  International (GeographicLib GeoidEval, 2026-11-15). The requirements
  estimated -28 m and asked for it to be verified.
- **Static data merge.** A newer static message never blanks a field that an
  earlier one filled, because class B vessels send the name and the other
  details in separate parts.
- **Throttle location.** The throttle is in `clean/throttle.py`; the Phase 5
  publisher will use it. For AIS, a change of name, description or call sign
  lets an update through early.
- **Emergency squawks are logged with the hex address.** The requirements ask
  for a warning. It is logged once each time an aircraft starts sending 7500,
  7600 or 7700, not on every poll. This is the one place a log line names an
  aircraft.
- **Synthetic MMSIs and the vessel rule.** Fixture MMSIs must be in the 999
  range, which the vessel rule drops (first digit must be 2 to 7). The replay
  therefore runs twice: once with `AIS_ALLOW_NON_VESSEL_MMSI` on to exercise
  every other rule, and once with defaults to show the range is dropped.
- **Registration and type.** readsb's aircraft.json has no `r` or `t` fields
  unless its aircraft database is enabled (`TAR1090_ENABLE_AC_DB`, which
  downloads a database at start). It is off, so aircraft are named by
  callsign or hex. To be revisited in Phase 6.
- **Async SDK client.** The ingest services use the SDK's `AsyncLattice`, so
  publishing never blocks the WebSocket or the poll loop. The SDK's own
  retries are off (`max_retries=0`); the publisher retries 408, 429, 5xx and
  network failures itself, up to four tries with 0.5 s to 8 s backoff.
- **Newest-wins queue.** Updates wait in a queue keyed by entity ID. If a
  newer report for the same track arrives before the older one is sent, only
  the newer one goes out, so a slow Lattice never builds a backlog.
- **Parallel publishes.** `PUBLISH_CONCURRENCY` defaults to 2. With 8, the
  Sandboxes environment answered some updates with 403 (empty body) and 412
  ("Keycloak token validation failed ... context deadline exceeded").
- **Error logs are rate-limited.** A rejected or abandoned update is logged
  with its entity ID, status and body (never headers), at most once every
  30 s per kind of failure. Counters record every one.
- **Entity details.** `platform_type` is `Surface Vessel` or `Airplane`.
  Vessels carry their MMSI as an alternate ID (`ALT_ID_TYPE_MMSI_ID`). The
  SDK has no alternate-ID type for an ICAO address, so aircraft carry none;
  the hex is in the entity ID. `createdTime` is when this process first
  published the track, and is forgotten after an hour without updates.
- **ADS-B Exchange fallback not built.** The receiver passed its signal gate,
  and the requirements allow the fallback only if it fails. `adsb-ingest`
  exits with a clear message if `ADSB_SOURCE=adsbx`. The related settings
  stay, validated but unused.
- **Unchanged aircraft.json documents are skipped.** If readsb has not
  written a new file since the last poll, nothing is cleaned or published.
- **Ingest services restart.** `ais-ingest` and `adsb-ingest` now use
  `restart: unless-stopped`. Without the `sdr` profile, `adsb-ingest` keeps
  polling and counts failed polls instead of exiting.
- **Phase 5 live run (2026-11-15, 18:16 to 18:46 UTC).** AIS: 636 of 636
  published. ADS-B: 3,992 published, 2 retried, 2 rejected with 403 and an
  empty body (18:16:59 and 18:21:25). Each affected aircraft was published
  again two seconds later. The requirements say never to retry 4xx, so these
  were not retried; whether to treat an empty-bodied 403 from the Sandboxes
  front end as transient is the owner's call.

## 2026-11-16

- **Phase 5 gate accepted by the owner.** The two un-retried 403s stand. The
  rule of never retrying a 4xx is unchanged.
- **Aircraft enrichment (owner request).** This goes beyond the requirements
  document, which asks only for icon, name, position, heading and expiry.
  - *Source of the extra data.* Only the receiver and the readsb image are
    used; nothing is looked up on the internet. `TAR1090_ENABLE_AC_DB=true`
    makes readsb add registration, type code, long type name, owner or
    operator and build year from the tar1090-db database that is built into
    the pinned image. `UPDATE_TAR1090=false` stays, so the container
    downloads nothing at start and the database is as old as the image.
    readsb's memory rose from about 65 MiB to about 96 MiB.
  - *Where it goes in the entity.* `ontology.specific_type` is the long type
    name, or the type code when there is no long name. `platform_type` stays
    `Airplane` for every aircraft, as the requirements say. Callsign and
    registration go out as `ALT_ID_TYPE_CALLSIGN` and
    `ALT_ID_TYPE_REGISTRATION_ID` (vessels now send their call sign the same
    way). `transponder_codes` carries the Mode S address (the ICAO hex as a
    number), the flight ID, the squawk as `mode3` and the barometric altitude
    as `mode_c_altitude_ft`. The description lists all of it in words.
  - *Squawk encoding is an assumption.* `mode3` is an integer in the SDK and
    its notes do not say how to encode the four octal digits. The squawk is
    sent as it is read aloud (7700 goes out as 7700, not as 4032). This is
    not yet checked against a live environment.
  - *Emergencies.* `indicators.emergency` is true for squawks 7500, 7600 and
    7700 and for the ADS-B states general, no radio, unlawful interference
    and downed aircraft. Medical ("lifeguard") and minimum-fuel flights are
    named in the description as a priority but do not set the flag. The flag
    is sent as false otherwise, so it clears when the emergency ends.
  - *Privacy.* The database marks aircraft in the FAA's two privacy
    programmes, LADD and PIA. Their owner or operator name is left out. Type
    and registration are still sent.
  - *Verified live later the same day.* The Sandboxes environment had been
    torn down when this was built (TLS connections reset). On the owner's
    next environment (16:12 UTC) Lattice accepted every update, and each
    aircraft read back from the Entities API with all new fields as sent,
    including `mode3` equal to the squawk as read. How the Lattice UI
    displays `mode3` is still to be looked at in Phase 6.
- **Sandboxes environments last two hours.** The owner provisions a new one
  each time and updates `.env`. The first request to a new environment was
  answered with 403 and an empty body, and the same request succeeded seconds
  later. This matches the two 403s of the Phase 5 run, which also came in
  the first minutes.
- **Route, airline and photo lookups not built.** They would mean sending
  each callsign or ICAO address to a third-party service (such as adsbdb or
  adsb.lol), which is a new data source with its own terms. That is the
  owner's call.
- **Phase 6 signed off by the owner.** The visual items were checked by the
  owner on the map and in the Lattice UI. Expiry was measured through the
  Entities API instead of by eye: aircraft were gone within 82 seconds of
  stopping `adsb-ingest`, and ships within 10 minutes 20 seconds of stopping
  `ais-ingest`. No screenshot is in the repo yet.
- **README status table removed.** The documentation checklist has no status
  section; `docs/PLAN.md` carries the phase state.
- **SDK licence review (owner request).** Read: the Anduril Lattice Software
  Development Kit License Agreement, "Updated July 31, 2026", as shipped in
  `anduril-lattice-sdk` 5.5.0. The sample app's `LICENSE.md` and the licence
  page on Anduril's developer site carry the same text. This is a reading by
  the project's tooling, not legal advice.
  - *In line with it:* the SDK and the sample app are installed at build time,
    used unmodified and never committed (3.4); no image is pushed (3.4);
    Anduril's licence files stay in the installed packages (3.8); only the
    owner's own credentials and environment are used (4.3, 4.4); credentials
    stay in the git-ignored `.env` and the map app stays on `127.0.0.1` (5.1).
  - *Fixed:* CI kept installed packages, and so a copy of the SDK, in the
    repository's GitHub Actions cache. The cache is now off, the stored
    caches were deleted, and a compliance test keeps it off.
  - *Open, owner's call:* the repository name contains "Lattice" (3.7 gives
    no right to Anduril's trade names or marks). Screenshots of the Lattice UI
    show Anduril's product and logo, and the agreement gives no permission to
    publish them. The agreement does not cover the Sandboxes service; any
    terms accepted at sign-up there have not been seen.
- **Project renamed to Tampa-COP (owner decision).** The first name contained
  the word "Lattice", which is Anduril's mark; the SDK licence (3.7) gives no
  right to use it, and the requirements bar Anduril trademarks from the repo
  name. The repository, the Python package (`tampa_cop`), the image and
  Compose project names, the entity ID prefix (`tampa-cop-ais-...`,
  `tampa-cop-adsb-...`) and the integration names changed with it. "Lattice"
  now appears only where it describes what the project connects to. Entities
  published under the old prefix expire by themselves. Git history keeps the
  old name.
- **Screenshots added at the owner's instruction.** The owner supplied five
  screenshots of the Lattice UI and asked for them in the README, after the
  licence review above had flagged that the SDK licence gives no explicit
  permission to publish them. Three are used. They are cropped to the map and
  the track panel, which leaves out the Anduril logo and the Sandbox banner,
  in keeping with the rule against Anduril logos in the repo. They show live
  traffic at one moment each; the README's data-handling section says so.
- **Message-flow diagram redrawn.** One line per box, wider boxes, and
  six-sided decision boxes in place of diamonds, which wasted space.
- **Soak test result.** Two hours and three minutes, 16:45 to 18:48 UTC, with
  the receiver, both ingest services and the map app running. No container
  restarted and memory stayed flat; the figures are in `docs/PLAN.md`. The
  Sandboxes environment, issued at about 16:02 UTC, was expected to end
  mid-run but answered at every sample, so the whole run was against a live
  Lattice. Eight updates out of about 12,900 sent were rejected with HTTP 403
  and an empty body, the same transient the owner accepted at the Phase 5
  gate. The publisher logs at most one such error every 30 seconds, so the
  log shows fewer lines than the `publish.rejected` counter.
- **Soak ran on the pre-rename build.** The rename to Tampa-COP landed while
  the soak was running, and restarting would have reset it. The rename
  changed names only. Afterwards the old containers were removed, the stack
  was rebuilt as Compose project `tampa-cop`, and both services published
  under the new entity IDs within a minute.
- **Phase 7 gate closed.** Every line of the definition of done is met. The
  final project licence remains the owner's open decision.
