# SPDX-License-Identifier: Apache-2.0
"""Dotenv key checks, including the real .env.example against the real settings."""

from pathlib import Path

from tampa_cop import envcheck

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_dotenv_keys_ignores_comments_values_and_blank_lines() -> None:
    text = "# comment\n\nA=1\n  B = two # trailing\nexport C=\n#D=4\nnot a key line\n"
    assert envcheck.dotenv_keys(text) == {"A", "B", "C"}


def test_missing_from_env_lists_keys_the_example_has() -> None:
    assert envcheck.missing_from_env({"A"}, {"A", "C", "B"}) == ["B", "C"]
    assert envcheck.missing_from_env({"A", "EXTRA"}, {"A"}) == []


def test_example_problems_reports_both_directions() -> None:
    keys = envcheck.settings_keys()
    assert envcheck.example_problems(keys) == []

    problems = envcheck.example_problems((keys - {"LATTICE_URL"}) | {"OLD_SETTING"})
    assert problems == [
        "LATTICE_URL: read by the code but missing from .env.example",
        "OLD_SETTING: in .env.example but not read by the code",
    ]


def test_env_example_covers_every_setting_the_code_reads() -> None:
    example_keys = envcheck.read_keys(REPO_ROOT / ".env.example")
    assert envcheck.example_problems(example_keys) == []
