"""日本語トークナイズと ``text_search``(tsvector) 生成（設計 §5 / §11.1-B / §13.6）。

検索インデックスは pg_bigm（bigram、``text_plain``）と tsvector のハイブリッド。
tsvector 経路は **アプリ側（fugashi/MeCab）でトークナイズして空白区切りに変換し、
``to_tsvector('simple', ...)`` に渡す**方式（§11.1 方式 B）を採る。辞書管理を Python
レイヤに閉じ込め、CI/本番のバージョン一致を保ちやすくするため。

``text_search`` は STORED 生成列にせず、取り込み後の別パスで書き込む（§11.1-4 / §13.6）。
本モジュールはトークナイザと、``law_node`` への一括書き込みを提供する。

辞書: unidic-lite（pip 同梱の小型 UniDic）。バージョンの ``text_index_meta`` への記録は
後続フェーズで対応する（§11.1）。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from laws_api_mirror.db.models import LawNode


@lru_cache(maxsize=1)
def _tagger() -> Any:
    # 辞書ロードが重いため遅延生成し、プロセス内で使い回す。
    from fugashi import Tagger

    return Tagger()


def tokenize(value: str) -> str:
    """テキストを形態素の表層形の空白区切り文字列に変換する。"""
    return " ".join(word.surface for word in _tagger()(value))


async def populate_text_search(
    session: AsyncSession,
    *,
    law_revision_id: str | None = None,
    batch_size: int = 1000,
) -> int:
    """``text_plain`` を持つ law_node に ``text_search``(tsvector) を書き込む。

    呼び出し側がトランザクション境界を管理する。書き込んだ行数を返す。

    対象行をいったん取得してから UPDATE する（同一接続でのカーソル併用を避ける）。
    大規模・全 DB 一括ではメモリを抑えるため ``law_revision_id`` で法令単位に
    スコープして呼ぶこと（ブートストラップは法令ごとに本関数を呼ぶ）。
    """
    stmt = select(LawNode.id, LawNode.text_plain).where(LawNode.text_plain.is_not(None))
    if law_revision_id is not None:
        stmt = stmt.where(LawNode.law_revision_id == law_revision_id)

    targets = (await session.execute(stmt)).all()
    if not targets:
        return 0

    update = text("UPDATE law_node SET text_search = to_tsvector('simple', :tok) WHERE id = :id")
    updated = 0
    for start in range(0, len(targets), batch_size):
        batch: list[dict[str, Any]] = [
            {"id": node_id, "tok": tokenize(text_plain)}
            for node_id, text_plain in targets[start : start + batch_size]
        ]
        await session.execute(update, batch)
        updated += len(batch)
    return updated
