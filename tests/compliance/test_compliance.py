# SPDX-License-Identifier: Apache-2.0
"""Compliance gate: licence notices, no SDK files, no image pushes, synthetic fixtures.

The first half runs the checks against this repository. The second half proves
each check actually fails on bad input, so a green gate means something.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.compliance import checks

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _tracked_files() -> list[str]:
    git = shutil.which("git")
    assert git, "git is required for the compliance checks"
    result = subprocess.run(  # noqa: S603 - fixed arguments, no shell
        [git, "-C", str(REPO_ROOT), "ls-files", "-z"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [path for path in result.stdout.split("\0") if path]


# --- The repository itself -------------------------------------------------


@pytest.mark.parametrize("filename", ["README.md", "THIRD_PARTY_NOTICES.md"])
def test_disclaimer_is_present_word_for_word(filename: str) -> None:
    text = (REPO_ROOT / filename).read_text(encoding="utf-8")
    assert checks.missing_notices(text, [checks.DISCLAIMER]) == []


def test_readme_carries_the_data_notice() -> None:
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert checks.missing_notices(text, [checks.DATA_NOTICE]) == []


def test_no_sdk_files_are_tracked() -> None:
    tracked = _tracked_files()
    assert tracked, "expected git to list tracked files"
    assert checks.sdk_path_problems(tracked) == []


def test_workflows_never_push_images() -> None:
    workflows = sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])
    assert workflows, "expected at least one workflow to check"
    problems = [
        problem
        for workflow in workflows
        for problem in checks.workflow_push_problems(
            workflow.name, workflow.read_text(encoding="utf-8")
        )
    ]
    assert problems == []


def test_fixtures_are_synthetic() -> None:
    files = sorted(path for path in FIXTURES.rglob("*") if path.is_file())
    problems = [problem for path in files for problem in checks.fixture_file_problems(path)]
    assert problems == []


def test_compose_publishes_ports_on_loopback_only() -> None:
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert compose["services"], "expected Compose services to check"
    assert checks.compose_exposure_problems(compose) == []


# --- The checks themselves -------------------------------------------------


def test_notice_check_ignores_wrapping_and_block_quotes() -> None:
    wrapped = "# Title\n\n> " + checks.DISCLAIMER.replace(". ", ".\n> ") + "\n"
    assert checks.missing_notices(wrapped, [checks.DISCLAIMER]) == []


def test_notice_check_fails_on_changed_wording() -> None:
    altered = checks.DISCLAIMER.replace("not affiliated with", "unaffiliated with")
    assert checks.missing_notices(altered, [checks.DISCLAIMER]) == [checks.DISCLAIMER]


@pytest.mark.parametrize(
    "path",
    [
        "vendor/anduril/entities.py",
        "third_party/lattice_sdk/__init__.py",
        "web/lattice-sdk/package.json",
        "web/node_modules/leaflet/index.js",
        "wheels/anduril_thing-5.5.0-py3-none-any.whl",
        "downloads/sdk.tar.gz",
    ],
)
def test_sdk_check_flags_vendored_paths(path: str) -> None:
    assert checks.sdk_path_problems([path])


def test_sdk_check_allows_our_own_files() -> None:
    ours = ["pyproject.toml", "uv.lock", "src/lattice_cop/lattice/entity.py", "README.md"]
    assert checks.sdk_path_problems(ours) == []


@pytest.mark.parametrize(
    "snippet",
    [
        "run: docker push ghcr.io/someone/image",
        "with:\n  push: true\n",
        "with:\n  push: 'true'\n",
        "permissions:\n  packages: write\n",
    ],
)
def test_workflow_check_flags_image_pushes(snippet: str) -> None:
    assert checks.workflow_push_problems("ci.yml", snippet)


def test_workflow_check_allows_push_triggers() -> None:
    text = "on:\n  push:\n    branches: [main]\npermissions:\n  contents: read\n"
    assert checks.workflow_push_problems("ci.yml", text) == []


@pytest.mark.parametrize(
    "document",
    [
        {"MetaData": {"MMSI": 999000001}, "Message": {"PositionReport": {"UserID": 999000001}}},
        {"aircraft": [{"hex": "ffff01"}, {"hex": "~ffff02"}]},
        {"mmsi": "999999999"},
    ],
)
def test_fixture_check_allows_synthetic_identifiers(document: object) -> None:
    assert checks.fixture_value_problems(document) == []


@pytest.mark.parametrize(
    "document",
    [
        {"MetaData": {"MMSI": 367000001}},
        {"Message": {"PositionReport": {"UserID": 998999999}}},
        {"mmsi": "not-a-number"},
        {"aircraft": [{"hex": "a1b2c3"}]},
        {"aircraft": [{"hex": "~a1b2c3"}]},
    ],
)
def test_fixture_check_flags_real_looking_identifiers(document: object) -> None:
    assert checks.fixture_value_problems(document)


def test_fixture_file_check_reads_json_and_jsonl(tmp_path: Path) -> None:
    good = tmp_path / "good.jsonl"
    good.write_text('{"hex": "ffff01"}\n\n{"MMSI": 999000002}\n', encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"aircraft": [{"hex": "abc123"}]}), encoding="utf-8")
    assert checks.fixture_file_problems(good) == []
    assert checks.fixture_file_problems(bad)


def test_fixture_file_check_rejects_unparseable_and_unknown_files(tmp_path: Path) -> None:
    broken = tmp_path / "broken.jsonl"
    broken.write_text("{not json}\n", encoding="utf-8")
    capture = tmp_path / "capture.csv"
    capture.write_text("mmsi,lat,lon\n", encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text("docs", encoding="utf-8")
    assert checks.fixture_file_problems(broken)
    assert checks.fixture_file_problems(capture)
    assert checks.fixture_file_problems(readme) == []


@pytest.mark.parametrize(
    "service",
    [
        {"ports": ["127.0.0.1:5173:5173"]},
        {"ports": ["127.0.0.1:8080:80/tcp", "[::1]:8080:80"]},
        {"ports": [{"target": 5173, "published": 5173, "host_ip": "127.0.0.1"}]},
        {"command": ["ais-ingest"]},
    ],
)
def test_exposure_check_allows_loopback_and_unpublished_services(service: object) -> None:
    assert checks.compose_exposure_problems({"services": {"svc": service}}) == []


@pytest.mark.parametrize(
    "service",
    [
        {"ports": ["5173:5173"]},
        {"ports": ["5173"]},
        {"ports": ["0.0.0.0:5173:5173"]},
        {"ports": ["192.168.1.10:5173:5173"]},
        {"ports": [{"target": 5173, "published": 5173}]},
        {"network_mode": "host"},
    ],
)
def test_exposure_check_flags_anything_wider(service: object) -> None:
    assert checks.compose_exposure_problems({"services": {"svc": service}})


def test_exposure_check_ignores_malformed_documents() -> None:
    assert checks.compose_exposure_problems(None) == []
    assert checks.compose_exposure_problems({"services": {"svc": None}}) == []
