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
