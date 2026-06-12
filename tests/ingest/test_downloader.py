"""BulkDownloader（ストリーミング取得・再試行）の単体テスト。

ネットワークは ``httpx.MockTransport`` で差し替え、待機は no-op を注入して即時実行する。
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import httpx
import pytest

from laws_api_mirror.core.config import Settings
from laws_api_mirror.ingest.artifact import DownloadArtifact
from laws_api_mirror.ingest.bulkdownload import BulkDownloadRequest, FileSection
from laws_api_mirror.ingest.downloader import BulkDownloader, DownloadError

PAYLOAD = b"PK\x03\x04" + b"dummy zip body" * 1000
CAPTURED = date(2026, 6, 13)
EXPECTED_KEY = "raw/bulk/20260613/section1/all_xml.zip"


class _SleepRecorder:
    """注入する no-op sleep。呼ばれた待機秒数を記録する。"""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(download_landing_dir=tmp_path, **overrides)  # type: ignore[arg-type]


def _request() -> BulkDownloadRequest:
    return BulkDownloadRequest(file_section=FileSection.ALL)


async def _download(
    settings: Settings,
    handler: httpx.MockTransport,
    sleep: _SleepRecorder,
) -> DownloadArtifact:
    async with httpx.AsyncClient(transport=handler) as client:
        downloader = BulkDownloader(settings, client=client, sleep=sleep)
        return await downloader.download(_request(), captured_date=CAPTURED)


async def test_success_writes_file_and_meta(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    sleep = _SleepRecorder()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=PAYLOAD))

    artifact = await _download(settings, transport, sleep)

    dest = tmp_path / EXPECTED_KEY
    assert dest.read_bytes() == PAYLOAD
    assert not dest.with_name(dest.name + ".part").exists()
    assert artifact.object_key == EXPECTED_KEY
    assert artifact.landing_path == str(dest.resolve())
    assert artifact.sha256 == hashlib.sha256(PAYLOAD).hexdigest()
    assert artifact.byte_size == len(PAYLOAD)
    assert artifact.http_status == 200
    assert artifact.file_section == 1
    assert artifact.only_xml is True
    assert "file_section=1" in artifact.source_url
    assert sleep.delays == []

    # サイドカーメタが書かれ、ラウンドトリップできる
    meta = DownloadArtifact.read_meta(artifact.meta_path())
    assert meta.sha256 == artifact.sha256


async def test_retries_then_succeeds(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    sleep = _SleepRecorder()
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, content=PAYLOAD)

    artifact = await _download(settings, httpx.MockTransport(handler), sleep)

    assert len(calls) == 2
    assert sleep.delays == [settings.download_backoff_base**1]  # Retry-After なし → バックオフ
    assert artifact.byte_size == len(PAYLOAD)


async def test_respects_retry_after_header(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    sleep = _SleepRecorder()
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, headers={"Retry-After": "7"})
        return httpx.Response(200, content=PAYLOAD)

    await _download(settings, httpx.MockTransport(handler), sleep)

    assert sleep.delays == [7.0]


async def test_exhausts_retries_and_cleans_up(tmp_path: Path) -> None:
    settings = _settings(tmp_path, download_max_retries=3)
    sleep = _SleepRecorder()
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503)

    with pytest.raises(DownloadError):
        await _download(settings, httpx.MockTransport(handler), sleep)

    assert len(calls) == 3
    assert len(sleep.delays) == 2  # 最終試行の後は待機しない
    dest = tmp_path / EXPECTED_KEY
    assert not dest.exists()
    assert not dest.with_name(dest.name + ".part").exists()


async def test_client_error_is_not_retried(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    sleep = _SleepRecorder()
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(404)

    with pytest.raises(DownloadError, match="HTTP 404"):
        await _download(settings, httpx.MockTransport(handler), sleep)

    assert len(calls) == 1  # 4xx は即時失敗（再試行しない）
    assert sleep.delays == []
