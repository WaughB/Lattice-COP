# Test fixtures

Every file here is synthetic. Nothing in this directory was captured from a
live AIS or ADS-B feed, and nothing ever should be.

The compliance tests enforce this:

- MMSIs must be in `999000000`-`999999999` (not assigned to real vessels).
- ICAO hex codes must start with `ffff` (`~ffff..` for non-ICAO test cases).
- Only `.json`, `.jsonl` and `.ndjson` files are allowed, so every fixture can
  be parsed and checked.
