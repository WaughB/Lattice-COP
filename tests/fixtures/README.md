# Test fixtures

Every file here is synthetic. Nothing in this directory was captured from a
live AIS or ADS-B feed, and nothing ever should be.

The compliance tests enforce this:

- MMSIs must be in `999000000`-`999999999` (not assigned to real vessels).
- ICAO hex codes must start with `ffff` (`~ffff..` for non-ICAO test cases).
- Only `.json`, `.jsonl` and `.ndjson` files are allowed, so every fixture can
  be parsed and checked.

## Replay files

`tests/test_replay.py` runs these through the cleaning rules and checks the
keep and drop counts.

- `ais_replay.jsonl`: one arrival per line, as `{"received_at": ..., "message": ...}`.
  The message uses AISStream's envelope. Positions are made-up points in Tampa Bay.
- `adsb_replay.jsonl`: one readsb `aircraft.json` document per line.

Both were written by hand-built generators from `tests/builders.py`, never
from a recording.
