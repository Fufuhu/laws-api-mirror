"""一括ダウンロード Zip のストリーミング取得（Stage 0: Fetch）。

docs/design/12-全件ダウンロード.md §12.7「取得の堅牢性と礼儀正しさ」に対応する。

- レスポンスを全展開せずチャンク単位で landing zone に書き出す（GB 級 Zip 前提）。
- SHA-256 とバイト数を逐次計算し、取得物の同一性を記録する（§12.5）。
- 接続・読み取りタイムアウトを分け、指数バックオフで再試行する。
- ``429`` / ``503`` 等を尊重し、``Retry-After`` があれば従う。
- 不完全な取得は成功扱いにせず、``.part`` 一時ファイルとして隔離する。

なお landing zone は最終的にオブジェクトストレージ（§11.2 / §12.4）を想定するが、
本実装ではローカルファイルシステムに着地させる。S3 連携は後続フェーズで追加する。
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from laws_api_mirror.core.config import Settings
from laws_api_mirror.core.config import settings as default_settings
from laws_api_mirror.ingest.artifact import DownloadArtifact
from laws_api_mirror.ingest.bulkdownload import BulkDownloadRequest

#: 一時的な障害として再試行する HTTP ステータス（§12.7）
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

#: 非同期 sleep の差し替え用シグネチャ（テストで no-op を注入する）
SleepFn = Callable[[float], Awaitable[None]]


class DownloadError(RuntimeError):
    """ダウンロードが回復不能に失敗したことを表す。"""


class _RetryableResponse(Exception):
    """再試行対象の HTTP ステータスを受け取ったことを表す内部例外。"""

    def __init__(self, status: int, retry_after: float | None) -> None:
        super().__init__(f"retryable HTTP status {status}")
        self.status = status
        self.retry_after = retry_after


class BulkDownloader:
    """e-Gov 一括ダウンロード Zip を landing zone へストリーミング取得する。

    :param settings: 設定（タイムアウト・User-Agent・landing zone 等）。
    :param client: 注入する ``httpx.AsyncClient``。``None`` なら設定からその都度生成する。
        テストでは ``httpx.MockTransport`` を載せたクライアントを渡す。
    :param sleep: バックオフ待機に使う関数。テストでは no-op を渡す。
    """

    def __init__(
        self,
        settings: Settings = default_settings,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: SleepFn = asyncio.sleep,
    ) -> None:
        self._settings = settings
        self._client = client
        self._sleep = sleep

    async def download(
        self,
        request: BulkDownloadRequest,
        *,
        captured_date: date | None = None,
    ) -> DownloadArtifact:
        """``request`` で指定された Zip を取得し、成果物メタを返す。

        :param captured_date: 取得日（こちら側のタイムスタンプ）。省略時は本日（UTC）。
        """
        captured = captured_date or datetime.now(UTC).date()
        url = request.build_url(self._settings.bulkdownload_base_url)
        object_key = request.object_key(captured)
        dest = Path(self._settings.download_landing_dir) / object_key
        dest.parent.mkdir(parents=True, exist_ok=True)

        if self._client is not None:
            return await self._run(self._client, request, url, object_key, dest)

        timeout = httpx.Timeout(
            connect=self._settings.download_connect_timeout,
            read=self._settings.download_read_timeout,
            write=self._settings.download_read_timeout,
            pool=self._settings.download_connect_timeout,
        )
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            return await self._run(client, request, url, object_key, dest)

    async def _run(
        self,
        client: httpx.AsyncClient,
        request: BulkDownloadRequest,
        url: str,
        object_key: str,
        dest: Path,
    ) -> DownloadArtifact:
        max_retries = self._settings.download_max_retries
        last_exc: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                status, sha256, byte_size = await self._attempt(client, url, dest)
            except _RetryableResponse as exc:
                last_exc = exc
                delay = exc.retry_after if exc.retry_after is not None else self._backoff(attempt)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                delay = self._backoff(attempt)
            else:
                artifact = DownloadArtifact(
                    file_section=int(request.file_section),
                    category_cd=request.category_cd,
                    update_date=request.update_date,
                    only_xml=request.only_xml,
                    source_url=url,
                    object_key=object_key,
                    landing_path=str(dest.resolve()),
                    sha256=sha256,
                    byte_size=byte_size,
                    http_status=status,
                    fetched_at=datetime.now(UTC),
                )
                artifact.write_meta()
                return artifact

            if attempt >= max_retries:
                break
            await self._sleep(delay)

        self._cleanup_part(dest)
        raise DownloadError(
            f"{url} のダウンロードに失敗しました（{max_retries} 回試行）"
        ) from last_exc

    async def _attempt(
        self,
        client: httpx.AsyncClient,
        url: str,
        dest: Path,
    ) -> tuple[int, str, int]:
        """1 回分の取得。成功時 ``(http_status, sha256_hex, byte_size)`` を返す。"""
        headers = {"User-Agent": self._settings.download_user_agent}
        hasher = hashlib.sha256()
        byte_size = 0
        part = self._part_path(dest)

        async with client.stream("GET", url, headers=headers) as response:
            if response.status_code in RETRYABLE_STATUS:
                await response.aread()
                raise _RetryableResponse(response.status_code, self._retry_after(response))
            if response.status_code >= 400:
                await response.aread()
                raise DownloadError(f"{url} が HTTP {response.status_code} を返しました")

            with part.open("wb") as fp:
                async for chunk in response.aiter_bytes(self._settings.download_chunk_size):
                    hasher.update(chunk)
                    byte_size += len(chunk)
                    fp.write(chunk)
            status = response.status_code

        part.replace(dest)
        return status, hasher.hexdigest(), byte_size

    def _backoff(self, attempt: int) -> float:
        return min(
            self._settings.download_backoff_max,
            self._settings.download_backoff_base**attempt,
        )

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        raw = response.headers.get("Retry-After")
        if raw is None:
            return None
        try:
            return float(int(raw))
        except ValueError:
            # HTTP-date 形式は本実装では解釈せず、通常のバックオフに委ねる
            return None

    @staticmethod
    def _part_path(dest: Path) -> Path:
        return dest.with_name(dest.name + ".part")

    @classmethod
    def _cleanup_part(cls, dest: Path) -> None:
        cls._part_path(dest).unlink(missing_ok=True)
