# SPDX-License-Identifier: Apache-2.0
"""Pure checks behind the compliance gate.

Each function takes plain data and returns a list of human-readable problems.
An empty list means the check passed. Keeping them pure lets the tests prove
that every check both passes on good input and fails on bad input.
"""

import json
import re
from collections.abc import Iterable, Iterator
from pathlib import Path, PurePosixPath

DISCLAIMER = (
    "Disclaimer: This is an independent personal project. It is not affiliated with, "
    "endorsed by, or sponsored by Anduril Industries. Anduril and Lattice are trademarks "
    "of Anduril Industries, Inc. This repository does not contain or redistribute the "
    "Lattice SDK; it is installed from Anduril's official package registries under "
    "Anduril's SDK License Agreement."
)

DATA_NOTICE = (
    "Vessel data provided by aisstream.io. Aircraft data comes from the owner's own ADS-B "
    "receiver, decoded with readsb. No live data is stored in or distributed from this "
    "repository."
)

MMSI_MIN = 999_000_000
MMSI_MAX = 999_999_999
FIXTURE_SUFFIXES = frozenset({".json", ".jsonl", ".ndjson"})
FIXTURE_DOCS = frozenset({"README.md"})

_SYNTHETIC_HEX = re.compile(r"^~?ffff[0-9a-f]*$")
_SDK_PATH = re.compile(r"lattice[_-]sdk", re.IGNORECASE)
_PUSH_PATTERNS = {
    "docker push": re.compile(r"docker\s+push", re.IGNORECASE),
    "push: true": re.compile(r"push\s*:\s*['\"]?true", re.IGNORECASE),
    "packages: write": re.compile(r"packages\s*:\s*['\"]?write", re.IGNORECASE),
}
_MMSI_KEYS = frozenset({"mmsi", "mmsi_string", "userid", "user_id"})
_HEX_KEYS = frozenset({"hex", "icao", "icao24", "icao_hex"})


def normalize(text: str) -> str:
    """Collapse Markdown quoting and line wrapping so wording can be compared exactly."""
    unquoted = re.sub(r"^\s*>\s?", "", text, flags=re.MULTILINE)
    return " ".join(unquoted.split())


def missing_notices(text: str, required: Iterable[str]) -> list[str]:
    """Return the required notices that do not appear word for word in ``text``."""
    haystack = normalize(text)
    return [notice for notice in required if normalize(notice) not in haystack]


def sdk_path_problems(paths: Iterable[str]) -> list[str]:
    """Flag tracked paths that look like vendored SDK code or packaged artifacts.

    The requirements allow ``lattice-sdk`` to appear in dependency manifests and
    lock files. That is about file contents; no manifest has it in its path, so
    path matching needs no exemption and a vendored ``lattice-sdk/package.json``
    is still caught.
    """
    problems: list[str] = []
    for raw in paths:
        path = PurePosixPath(raw)
        lowered = [part.lower() for part in path.parts]
        if "anduril" in lowered:
            problems.append(f"{raw}: inside a directory named 'anduril'")
        if _SDK_PATH.search(raw):
            problems.append(f"{raw}: path names the Lattice SDK")
        if "node_modules" in lowered:
            problems.append(f"{raw}: inside node_modules/")
        if raw.lower().endswith((".whl", ".tar.gz")):
            problems.append(f"{raw}: packaged artifact (*.whl or *.tar.gz)")
    return problems


def workflow_push_problems(name: str, text: str) -> list[str]:
    """Flag anything in a workflow file that could publish a container image."""
    return [
        f"{name}: contains '{label}'"
        for label, pattern in _PUSH_PATTERNS.items()
        if pattern.search(text)
    ]


def _walk(node: object) -> Iterator[tuple[str, object]]:
    """Yield every ``(key, value)`` pair found anywhere inside parsed JSON."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key), value
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def fixture_value_problems(document: object) -> list[str]:
    """Flag MMSIs and ICAO hex codes in parsed fixture data that are not provably synthetic."""
    problems: list[str] = []
    for key, value in _walk(document):
        lowered = key.lower()
        if lowered in _MMSI_KEYS:
            text = str(value).strip()
            if not (text.isdigit() and MMSI_MIN <= int(text) <= MMSI_MAX):
                problems.append(f"{key}={value!r} is outside {MMSI_MIN}-{MMSI_MAX}")
        elif lowered in _HEX_KEYS and not _SYNTHETIC_HEX.match(str(value).strip().lower()):
            problems.append(f"{key}={value!r} does not start with 'ffff'")
    return problems


def fixture_file_problems(path: Path) -> list[str]:
    """Check one fixture file: allowed type, parseable, and synthetic identifiers only."""
    if path.name in FIXTURE_DOCS:
        return []
    if path.suffix not in FIXTURE_SUFFIXES:
        return [f"{path.name}: only {sorted(FIXTURE_SUFFIXES)} fixtures are allowed"]
    text = path.read_text(encoding="utf-8")
    chunks = [text] if path.suffix == ".json" else [ln for ln in text.splitlines() if ln.strip()]
    problems: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        try:
            document = json.loads(chunk)
        except json.JSONDecodeError as exc:
            problems.append(f"{path.name}:{index}: not valid JSON ({exc.msg})")
            continue
        problems.extend(f"{path.name}:{index}: {p}" for p in fixture_value_problems(document))
    return problems
