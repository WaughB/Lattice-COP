#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check dotenv files. Reports key names only, never values.

uv run scripts/check-env.py              keys in .env.example that .env lacks
uv run scripts/check-env.py --settings   .env.example covers every setting the code reads
"""

import argparse
import sys
from pathlib import Path

from lattice_cop import envcheck

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    """Run the selected check and return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--settings", action="store_true", help="check .env.example against the code"
    )
    parser.add_argument("--env", type=Path, default=REPO_ROOT / ".env")
    parser.add_argument("--example", type=Path, default=REPO_ROOT / ".env.example")
    args = parser.parse_args()

    example_keys = envcheck.read_keys(args.example)
    if args.settings:
        problems = envcheck.example_problems(example_keys)
        label = ".env.example matches the settings the code reads"
    else:
        if not args.env.is_file():
            print(f"{args.env} does not exist. Copy .env.example to .env and fill it in.")
            return 1
        missing = envcheck.missing_from_env(envcheck.read_keys(args.env), example_keys)
        problems = [f"{key}: missing from {args.env.name}" for key in missing]
        label = f"{args.env.name} has every key in {args.example.name}"

    for problem in problems:
        print(problem)
    if problems:
        return 1
    print(f"OK: {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
