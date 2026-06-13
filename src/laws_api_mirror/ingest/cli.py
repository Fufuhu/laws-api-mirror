"""取り込み CLI。

現時点では全件ダウンロード（Stage 0: Fetch、§12）の ``download`` サブコマンドのみ提供する。

例::

    # 全件・XML のみ
    laws-ingest download --section 1

    # 差分（指定日・XML のみ）
    laws-ingest download --section 3 --update-date 20260613

    # 全データ（画像・様式込み）
    laws-ingest download --section 1 --full
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, datetime
from pathlib import Path

from pydantic import ValidationError

from laws_api_mirror.ingest.bulkdownload import BulkDownloadRequest, FileSection
from laws_api_mirror.ingest.downloader import BulkDownloader, DownloadError


def _parse_date(value: str) -> date:
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        f"日付は YYYYMMDD または YYYY-MM-DD 形式で指定してください: {value!r}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="laws-ingest", description="法令データ取り込み CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    download = subparsers.add_parser(
        "download", help="e-Gov 一括ダウンロード Zip を landing zone に取得する"
    )
    download.add_argument(
        "--section",
        type=int,
        choices=[int(s) for s in FileSection],
        default=int(FileSection.ALL),
        help="file_section: 1=全件 / 2=分類別 / 3=差分（既定: 1）",
    )
    download.add_argument("--category", default=None, help="分類コード（section=2 のとき必須）")
    download.add_argument(
        "--update-date",
        type=_parse_date,
        default=None,
        help="基準日 YYYYMMDD（section=3 のとき必須）",
    )
    download.add_argument(
        "--full",
        action="store_true",
        help="画像・様式を含む全データを取得する（既定は XML のみ）",
    )
    download.set_defaults(func=_run_download)

    bootstrap = subparsers.add_parser(
        "bootstrap", help="一括 Zip から全法令を DB に投入する（Stage 1→Load→索引後構築）"
    )
    bootstrap.add_argument("zip_path", help="一括 Zip のパス（landing zone 上の生 Zip）")
    bootstrap.add_argument(
        "--keep-indexes",
        action="store_true",
        help="二次索引を保持したまま投入する（既定は DROP→後構築で高速化）",
    )
    bootstrap.add_argument(
        "--no-copy",
        action="store_true",
        help="COPY ではなく INSERT で投入する（性能比較用。既定は COPY）",
    )
    bootstrap.set_defaults(func=_run_bootstrap)

    worker = subparsers.add_parser(
        "worker", help="Procrastinate ワーカーを起動する（取り込みジョブを実行）"
    )
    worker.add_argument(
        "--queue", action="append", default=None, help="処理するキュー（既定: ingest）"
    )
    worker.set_defaults(func=_run_worker)

    enqueue_delta = subparsers.add_parser(
        "enqueue-delta", help="指定日の差分取り込みジョブを投入する"
    )
    enqueue_delta.add_argument(
        "--update-date", type=_parse_date, required=True, help="基準日 YYYYMMDD"
    )
    enqueue_delta.set_defaults(func=_run_enqueue_delta)
    return parser


async def _run_download(args: argparse.Namespace) -> int:
    try:
        request = BulkDownloadRequest(
            file_section=FileSection(args.section),
            only_xml=not args.full,
            category_cd=args.category,
            update_date=args.update_date,
        )
    except ValidationError as exc:
        for error in exc.errors():
            msg = str(error["msg"]).removeprefix("Value error, ")
            print(f"引数エラー: {msg}")
        return 2
    downloader = BulkDownloader()
    try:
        artifact = await downloader.download(request)
    except DownloadError as exc:
        print(f"ダウンロード失敗: {exc}")
        return 1
    print(artifact.model_dump_json(indent=2))
    return 0


async def _run_bootstrap(args: argparse.Namespace) -> int:
    from laws_api_mirror.ingest.bootstrap import bootstrap_from_zip

    zip_path = Path(args.zip_path)
    if not zip_path.exists():
        print(f"Zip が見つかりません: {zip_path}")
        return 2
    summary = await bootstrap_from_zip(
        zip_path, drop_indexes=not args.keep_indexes, use_copy=not args.no_copy
    )
    print(
        json.dumps(
            {
                "ingest_run_id": summary.ingest_run_id,
                "total": summary.total,
                "inserted": summary.inserted,
                "failed": summary.failed,
                "node_count": summary.node_count,
                "failures": summary.failures,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if summary.failed == 0 else 1


async def _run_worker(args: argparse.Namespace) -> int:
    from laws_api_mirror.ingest.jobs import procrastinate_app

    queues = args.queue or ["ingest"]
    async with procrastinate_app.open_async():
        await procrastinate_app.run_worker_async(queues=queues)
    return 0


async def _run_enqueue_delta(args: argparse.Namespace) -> int:
    from laws_api_mirror.ingest.jobs import ingest_delta, procrastinate_app

    update_date: date = args.update_date
    async with procrastinate_app.open_async():
        job_id = await ingest_delta.defer_async(update_date=update_date.strftime("%Y%m%d"))
    print(f"差分取り込みジョブを投入しました: job_id={job_id} update_date={update_date:%Y%m%d}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result: int = asyncio.run(args.func(args))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
