"""構造化ログフォーマッタの単体テスト。"""

from __future__ import annotations

import json
import logging

from laws_api_mirror.core.logging import JsonFormatter


def _record(msg: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_emits_core_fields() -> None:
    payload = json.loads(JsonFormatter().format(_record("hello")))
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logger"
    assert payload["message"] == "hello"
    assert "ts" in payload


def test_json_formatter_includes_extra_fields() -> None:
    record = _record("ingest.run.finished", run_id=7, inserted=84)
    payload = json.loads(JsonFormatter().format(record))
    assert payload["run_id"] == 7
    assert payload["inserted"] == 84


def test_json_formatter_handles_non_ascii() -> None:
    payload = json.loads(JsonFormatter().format(_record("勅令を取り込み")))
    assert payload["message"] == "勅令を取り込み"
