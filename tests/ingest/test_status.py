"""取り込み状態判定（DB 非依存）の単体テスト。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from laws_api_mirror.ingest.status import RunInfo, _judge

_NOW = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)


def _run(status: str, finished: datetime | None = None) -> RunInfo:
    return RunInfo(
        id=1, kind="full", status=status, started_at=_NOW, finished_at=finished, stats=None
    )


def test_judge_never_when_no_run() -> None:
    assert _judge(None, None, now=_NOW, freshness_hours=48) == "never"


def test_judge_running() -> None:
    assert _judge(_run("running"), None, now=_NOW, freshness_hours=48) == "running"


def test_judge_failed_when_no_success() -> None:
    assert _judge(_run("failed"), None, now=_NOW, freshness_hours=48) == "failed"


def test_judge_ok_when_fresh_success() -> None:
    fresh = _NOW - timedelta(hours=1)
    assert _judge(_run("success", fresh), fresh, now=_NOW, freshness_hours=48) == "ok"


def test_judge_stale_when_old_success() -> None:
    old = _NOW - timedelta(hours=72)
    assert _judge(_run("success", old), old, now=_NOW, freshness_hours=48) == "stale"


def test_judge_completed_with_errors_is_ok_when_fresh() -> None:
    fresh = _NOW - timedelta(hours=2)
    last = _run("completed_with_errors", fresh)
    assert _judge(last, fresh, now=_NOW, freshness_hours=48) == "ok"
