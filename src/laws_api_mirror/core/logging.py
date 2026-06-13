"""構造化ログの初期化（C-2）。

標準ライブラリの ``logging`` だけで JSON 行ログを出す軽量な設定。追加依存を避け、
CI/本番でフォーマットを一致させる。``logging.LogRecord`` の ``extra=`` で渡した任意
フィールドも JSON に展開する（``run_id`` / ``law_revision_id`` など取り込み文脈の付与用）。

使い方:

    from laws_api_mirror.core.logging import configure_logging, get_logger
    configure_logging()
    log = get_logger(__name__)
    log.info("ingest.run.finished", extra={"run_id": 1, "inserted": 84})
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

#: LogRecord の標準属性（これ以外を extra として JSON に展開する）
_RESERVED = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
    }
)


class JsonFormatter(logging.Formatter):
    """LogRecord を 1 行の JSON に整形する。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO", *, json_format: bool = True) -> None:
    """ルートロガーを 1 度だけ構成する（既存ハンドラは置き換える）。"""
    root = logging.getLogger()
    root.setLevel(level.upper())
    handler = logging.StreamHandler()
    if json_format:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.handlers = [handler]


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
