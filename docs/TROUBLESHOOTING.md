# Troubleshooting

Each section starts with what you see, then the likely causes in the order worth checking. Commands are labelled with the shell they run in.

Two commands answer most questions:

```bash
# Ubuntu (WSL2), from the repo folder: checks Docker, .env and the dongle. Prints no secret values.
scripts/wsl/preflight.sh
```

```bash
# Ubuntu (WSL2): the last few log lines of both ingest services
docker compose logs --tail 20 ais-ingest adsb-ingest
```

## The dongle does not attach (USB)

**`preflight.sh` says "Dongle is not visible in Ubuntu".**

1. The attach script is not running. It must stay open in an administrator PowerShell window:

   ```powershell
   # Windows PowerShell (run as Administrator), from the repo folder
   .\scripts\windows\attach-sdr.ps1
   ```

2. The dongle has a different USB ID. The script looks for `0bda:2838`. List what Windows sees, then pass the right ID:

   ```powershell
   # Windows PowerShell
   usbipd list
   ```

   ```powershell
   # Windows PowerShell (run as Administrator); replace the ID with yours
   .\scripts\windows\attach-sdr.ps1 -HardwareId 0bda:2832
   ```

3. Another Windows program holds the dongle (SDR#, SDR++, a vendor driver tool). Close it and run the attach script again.
4. WSL was restarted. `wsl --shutdown`, a Windows update or a Docker Desktop restart detaches the dongle. Run the attach script again.

**`preflight.sh` says "Dongle is not visible inside a container".** Ubuntu sees the dongle but Docker does not. Restart Docker Desktop, run the attach script again, then run `preflight.sh` again.

**readsb logs "no supported devices found" or "usb_claim_interface error".** The dongle was attached after readsb started, or the kernel's TV driver took it. Restart the receiver:

```bash
# Ubuntu (WSL2)
docker compose --profile sdr restart readsb
```

**`preflight.sh` fails on `RECEIVER_ALT_M is empty`.** Put your antenna's height above sea level, in metres, in `.env`. An estimate is fine.

## No aircraft

Work from the antenna towards Lattice.

1. **Nothing on the receiver's own map (<http://127.0.0.1:8080>).** The problem is reception, not this project's code.
   - Check the dongle is attached (section above) and that `docker compose --profile sdr ps` shows `readsb` as healthy.
   - Move the antenna: vertical, high, at a window, away from the PC and USB 3 devices. A few feet can change the range a lot.
   - Wait for daytime. There are few flights at night.
   - Run `docker compose --profile sdr run --rm adsb-ingest sdr-check --minutes 5` for a quick measurement.
2. **Aircraft on the receiver's map but not on the Lattice map.** Read the counters:

   ```bash
   # Ubuntu (WSL2)
   docker compose logs --tail 3 adsb-ingest
   ```

   | What the `adsb-ingest counts` line shows | Meaning |
   | --- | --- |
   | `polls.failed_polls` keeps growing | `adsb-ingest` cannot reach readsb. Start it with `--profile sdr`. |
   | `clean.outside_aoi` or `clean.outside_radius` is high and `clean.kept` is 0 | The aircraft are real but outside your area. Check the `AOI_*` and `ADSB_*` values in `.env`. |
   | `clean.no_position` or `clean.stale` is high | Weak signal: readsb hears the aircraft but not its position often enough. Improve the antenna position. |
   | `publish.failed` or `publish.rejected` grows | Lattice is refusing or unreachable. See the Lattice section below. |
   | `publish.published` grows | Aircraft are reaching Lattice. Reload the map page; see "Tracks blink out" if they come and go. |

3. **`adsb-ingest` exits at once with "ADSB_SOURCE=adsbx is not supported".** The ADS-B Exchange fallback is not built. Set `ADSB_SOURCE=receiver`.

Aircraft show their callsign, or their hex code when no callsign has been heard yet. Type and registration come from the database inside the readsb image; a very new aircraft may be missing from it.

## No ships

1. **`AISSTREAM_API_KEY` is wrong or empty.** AISStream does not document how it answers a bad key. Expect either no messages at all (`stream.total_messages` stays at 0) or `AISStream connection lost; reconnecting` again and again with a growing `attempt`. Copy the key again from your AISStream account.
2. **Too many connections.** AISStream allows three connections per account. Stop other copies (`docker compose ps`, and any `docker compose run` left open in another terminal).
3. **The area is quiet or wrong.** Check `stream.positions_in_aoi` in the `ais-ingest counts` line. If it is 0 while `stream.total_messages` grows, the `AOI_*` box is wrong.
4. **Ships take a while to show names.** A ship sends its name every six minutes. Until then it shows as `MMSI` followed by its number.

## The AISStream WebSocket keeps closing

An occasional `AISStream connection lost; reconnecting` is normal. The service waits between 2 and 60 seconds, reconnects, and ships already in Lattice stay until their 10-minute expiry.

- **`TimeoutError: timed out during opening handshake` at start-up.** AISStream is slow to answer. The service retries by itself; this was seen twice in a row during testing before it connected.
- **It closes a few seconds after every connect.** The API key may be wrong, or the account already has three connections open.
- **It closes after long quiet periods.** Check your network. `ais-ingest` reconnects by itself once the network is back; in testing it recovered 12 seconds after a 75-second cut.
- **`stream.server_errors` grows.** AISStream sent an error message. The log line carries its text (never your key).

## 401, 403 or 412 from Lattice

The log lines `Lattice rejected an entity` and `gave up publishing an entity after retries` carry the HTTP status.

| What you see | Likely cause | Fix |
| --- | --- | --- |
| `ConnectError`, or "connection reset" | The Sandboxes environment has ended. They are time-limited (two hours in this project's experience). | Start a new environment and put its hostname and credentials in `.env`. See below. |
| 401 with "token is not a valid JWT" | `LATTICE_ENVIRONMENT_TOKEN` holds something that is not a token (for example the client secret). | Use the client ID and secret pair instead, or paste the real token. |
| 401 on every update | The credentials belong to an older environment, or `LATTICE_SANDBOXES_TOKEN` has expired or been revoked. | Copy the current values from the Sandboxes dashboard. |
| 403 with an empty body, once or twice, then fine | The environment's front end rejects the odd request, mostly in the first minutes. | Nothing. The next update for that track goes out seconds later. |
| 403 or 412 in bursts ("Keycloak token validation failed") | Too many updates at once. | Keep `PUBLISH_CONCURRENCY` at 2 or lower. |
| Settings error at start: "set LATTICE_ENVIRONMENT_TOKEN, or LATTICE_CLIENT_ID and LATTICE_CLIENT_SECRET, but not both" | Both ways to sign in are filled in. | Leave one of them empty. |

After starting a new environment, change `LATTICE_URL` and the credentials in `.env`, then recreate the services that hold them:

```bash
# Ubuntu (WSL2): the map app must be recreated too, because the credentials are built into its page
docker compose --profile sdr up -d --force-recreate ais-ingest adsb-ingest visualizer
```

Check with one synthetic vessel:

```bash
# Ubuntu (WSL2): publishes a vessel named LATTICE-COP SMOKE TEST for five minutes
docker compose run --rm ais-ingest smoke-test
```

## Tracks blink out

- **Aircraft vanish after a minute.** By design, an aircraft expires 60 seconds after its last update. At the edge of your range the receiver loses the position for longer than that. A better antenna position helps; `ADSB_EXPIRY_SECONDS` lengthens the time, at the cost of stale aircraft staying on the map.
- **Ships vanish after ten minutes.** A moored or anchored ship reports only every three minutes, and AISStream's coverage has gaps. `AIS_EXPIRY_SECONDS` lengthens the time.
- **Everything vanishes at once.** The environment has ended (see the Lattice section), or an ingest service has stopped. `docker compose --profile sdr ps` shows which.
- **One aircraft jumps away and comes back.** A corrupt position. The cleaning rules drop a position that implies an impossible speed and count it as `clean.position_jump`.
- **The map shows nothing after a new environment.** The map app still holds the old credentials. Recreate it with the command in the Lattice section, then reload the page.

## The map page

- **<http://127.0.0.1:5173> does not load.** `docker compose ps` should show `visualizer` as up. The first start takes a minute or two while the app builds.
- **The page loads but is empty.** Run the smoke test above. If the test vessel appears, the map is fine and the problem is upstream (see "No aircraft" and "No ships").
- **Never change the address the map listens on.** The page contains your Lattice credentials, so it is bound to `127.0.0.1` on purpose.

## Still stuck

Collect these before asking for help. None of them prints a secret, but read them through before sharing: the readsb log includes your antenna location.

```bash
# Ubuntu (WSL2)
scripts/wsl/preflight.sh
docker compose --profile sdr ps
docker compose logs --tail 50 ais-ingest adsb-ingest
```
