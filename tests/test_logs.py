# SPDX-License-Identifier: Apache-2.0
"""JSON log formatting."""

import json
import logging
import sys

import pytest

from lattice_cop.logs import JsonFormatter, configure_logging


def make_record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        "lattice_cop.test", logging.INFO, __file__, 1, "hello %s", ("x",), None
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_record_is_one_json_line_with_extras() -> None:
    line = JsonFormatter().format(make_record(entity_id="lattice-cop-ais-999000001", count=3))
    assert "\n" not in line
    payload = json.loads(line)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "lattice_cop.test"
    assert payload["message"] == "hello x"
    assert payload["entity_id"] == "lattice-cop-ais-999000001"
    assert payload["count"] == 3
    assert payload["time"].endswith("+00:00")


def test_exceptions_are_included() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = make_record()
        record.exc_info = sys.exc_info()
    payload = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in payload["exception"]


def test_private_and_unserializable_extras_are_handled() -> None:
    payload = json.loads(JsonFormatter().format(make_record(_hidden=1, thing={1, 2})))
    assert "_hidden" not in payload
    assert isinstance(payload["thing"], str)


def test_configure_logging_writes_json_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        configure_logging("WARNING")
        logging.getLogger("lattice_cop.test").info("hidden")
        logging.getLogger("lattice_cop.test").warning("shown", extra={"dropped": 2})
        lines = capsys.readouterr().out.strip().splitlines()
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
    assert len(lines) == 1
    assert json.loads(lines[0])["dropped"] == 2
    assert logging.getLogger("httpx").level == logging.WARNING
