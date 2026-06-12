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
from datetime import date, datetime

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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result: int = asyncio.run(args.func(args))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
