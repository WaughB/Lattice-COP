# SPDX-License-Identifier: Apache-2.0
"""Compare dotenv files with each other and with the settings the code reads.

Used by ``scripts/check-env.py``. Only key names are ever read or reported,
never values.
"""

import re
from pathlib import Path

from lattice_cop.config import Settings

_KEY_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def dotenv_keys(text: str) -> set[str]:
    """Return the variable names assigned in dotenv-formatted ``text``."""
    keys: set[str] = set()
    for line in text.splitlines():
        match = _KEY_LINE.match(line)
        if match:
            keys.add(match.group(1))
    return keys


def read_keys(path: Path) -> set[str]:
    """Return the variable names assigned in the dotenv file at ``path``."""
    return dotenv_keys(path.read_text(encoding="utf-8"))


def settings_keys() -> set[str]:
    """Return the environment variable name for every setting the code reads."""
    return {name.upper() for name in Settings.model_fields}


def missing_from_env(env_keys: set[str], example_keys: set[str]) -> list[str]:
    """Return keys that ``.env.example`` has and ``.env`` lacks."""
    return sorted(example_keys - env_keys)


def example_problems(example_keys: set[str]) -> list[str]:
    """Return mismatches between ``.env.example`` and the settings the code reads."""
    wanted = settings_keys()
    problems = [
        f"{key}: read by the code but missing from .env.example" for key in wanted - example_keys
    ]
    problems += [
        f"{key}: in .env.example but not read by the code" for key in example_keys - wanted
    ]
    return sorted(problems)
