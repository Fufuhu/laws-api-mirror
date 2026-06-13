# Testcontainers 解説と本プロジェクトでの使い方

設計書本体には収めない補助ドキュメント。本プロジェクトのテスト戦略の中核である [Testcontainers](https://testcontainers.com/) について、概念整理と具体的な使い方をまとめる。設計書 §2.10 / §9 を補完する位置付け。

## 1. Testcontainers とは

**「テスト時に Docker コンテナとして本物のミドルウェアを立ち上げ、テスト終了後に自動で破棄する」** ためのライブラリ群。元は Java 製で、現在は Python / Go / .NET / Node.js など各言語に移植されている。

- 公式サイト: <https://testcontainers.com/>
- Python 実装: <https://github.com/testcontainers/testcontainers-python>

### 1.1 何を解決するか

データベースや外部サービスに依存するコードをテストする際、従来は以下のどちらかだった:

| 手段 | 問題 |
|---|---|
| モック化 (`unittest.mock` 等) | 本物の挙動と乖離してバグを見逃す（特に SQL の方言・拡張機能） |
| 共有テスト DB | 並列実行で衝突、状態汚染、CI 不安定 |
| インメモリ DB（SQLite 等） | 本番と異なる DB のため拡張機能や独自 SQL が使えない |

Testcontainers は **「テストごとに使い捨ての本物 DB を Docker で立てる」** という第 3 の選択肢を提供する。

### 1.2 ライフサイクル

```
[テスト開始] → docker pull (初回のみ) → docker run → 接続情報を fixture へ
                                                    ↓
                                              テスト本体実行
                                                    ↓
[テスト終了] ← docker stop & docker rm ← fixture teardown
```

ポート割り当ては自動でホストの空きポートにマッピングされる。明示的な `--name` を指定しないので並列実行も衝突しない。

## 2. 本プロジェクトでの採用理由

本プロジェクトは PostgreSQL の以下の機能を中核に据えている:

- `ltree` 拡張（`elm` パスの解決、§4.7.1）
- `pg_bigm` 拡張（全文検索、§5）
- `tsvector` + `textsearch_ja`（MeCab、§5 / §11.1）
- `EXCLUDE` 制約（`enforcement_period` の重複防止、§4.3）
- `daterange` 型、`GENERATED ALWAYS AS ... STORED` 列
- `LISTEN/NOTIFY`（Procrastinate ジョブキュー、§11.7）

これらは **SQLite では代用できない**。本物の PostgreSQL を立ててテストする必要があり、Testcontainers がそれを最も摩擦なく実現する。

## 3. 最小コード例

```python
import pytest
from testcontainers.postgres import PostgresContainer
from sqlalchemy import create_engine, text

@pytest.fixture(scope="session")
def pg():
    with PostgresContainer("postgres:16") as container:
        yield container

def test_law_insert(pg):
    engine = create_engine(pg.get_connection_url())
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        assert result.scalar() == 1
```

- `with PostgresContainer(...)` でコンテナ起動。
- `get_connection_url()` で `postgresql://test:test@localhost:55432/test` のような URL が取れる。
- `with` ブロックを抜けると自動で停止・削除。
- `scope="session"` でテストスイート全体で 1 コンテナを使い回す（起動コストを抑える）。

## 4. 本プロジェクトの想定構成

### 4.1 カスタム PostgreSQL イメージ

`pg_bigm` / `ltree` / `textsearch_ja`（MeCab）をプリインストールしたカスタムイメージを `docker/postgres/Dockerfile` で定義し、リポジトリにコミットする。

```dockerfile
# docker/postgres/Dockerfile（例）
FROM postgres:16

RUN apt-get update && apt-get install -y \
    postgresql-16-pg-bigm \
    mecab mecab-ipadic-utf8 libmecab-dev \
    && rm -rf /var/lib/apt/lists/*

# 必要に応じて textsearch_ja のセットアップスクリプトを配置
COPY ./init-extensions.sql /docker-entrypoint-initdb.d/
```

`init-extensions.sql`:

```sql
CREATE EXTENSION IF NOT EXISTS ltree;
CREATE EXTENSION IF NOT EXISTS pg_bigm;
-- textsearch_ja は MeCab トークナイザの設定をここで実行
```

CI / 開発者ローカルで同じイメージを使うため、`docker build -t laws-api-mirror-pg:16 docker/postgres/` を事前に実行する Makefile ターゲットを用意する。

### 4.2 pytest fixture

`tests/conftest.py`:

```python
import pytest
from testcontainers.postgres import PostgresContainer
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from alembic import command
from alembic.config import Config

@pytest.fixture(scope="session")
def pg_container():
    """セッション全体で 1 つの PostgreSQL コンテナを使い回す"""
    with PostgresContainer("laws-api-mirror-pg:16") as container:
        # Alembic で最新スキーマを適用
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", container.get_connection_url())
        command.upgrade(cfg, "head")
        yield container

@pytest.fixture
async def db_session(pg_container):
    """テストごとに新しいセッションを発行し、終了時にロールバック"""
    async_url = pg_container.get_connection_url().replace(
        "postgresql://", "postgresql+asyncpg://"
    )
    engine = create_async_engine(async_url)
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn)
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()
    await engine.dispose()
```

ポイント:

- `scope="session"`: コンテナ起動コスト（数秒〜十数秒）を一度だけに抑える。
- **テストごとにトランザクションをロールバック**することで、コンテナを使い回しつつ状態を分離。
- Alembic を fixture 内から実行することで、スキーマ定義の変更がそのままテスト基盤に反映される。

### 4.3 S3 / SeaweedFS のコンテナ化

添付ファイルの S3 連携テストにも Testcontainers を使う。SeaweedFS の Docker イメージか、AWS S3 モックの `motoserver/moto` を選ぶ。

```python
from testcontainers.core.container import DockerContainer

@pytest.fixture(scope="session")
def s3_container():
    container = (
        DockerContainer("motoserver/moto:latest")
        .with_exposed_ports(5000)
        .with_env("MOTO_PORT", "5000")
    )
    with container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(5000)
        yield f"http://{host}:{port}"

@pytest.fixture
def s3_client(s3_container, monkeypatch):
    monkeypatch.setenv("AWS_ENDPOINT_URL_S3", s3_container)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    import boto3
    return boto3.client("s3", region_name="us-east-1", endpoint_url=s3_container)
```

`testcontainers-python` には公式モジュールが無い場合があるので、`DockerContainer` 汎用クラスで起動する形になる。

### 4.4 Procrastinate ワーカー

§11.7 で「ワーカーは API サーバーとは別プロセス」と確定済み。テストでも同様に **ワーカー用プロセスを別起動**するか、`procrastinate.testing` のインメモリコネクタを使う方法がある。

- **統合テスト**: 別 Python プロセス（`subprocess.Popen`）でワーカーを起動し、ジョブ完了をポーリング。
- **ユニットテスト**: `InMemoryConnector` を使い、Postgres 接続なしでタスク関数の論理を検証。

```python
@pytest.fixture
async def procrastinate_app(pg_container):
    from procrastinate import App, PsycopgConnector
    app = App(connector=PsycopgConnector(
        kwargs={"conninfo": pg_container.get_connection_url()}
    ))
    await app.schema_manager.apply_schema_async()
    yield app
```

### 4.5 統合テストのフロー

`tests/integration/test_law_data.py` 抜粋:

```python
@pytest.mark.asyncio
async def test_law_data_xml_roundtrip(db_session, s3_client, client):
    # 1. 代表法令 XML を fixture から投入
    await ingest_law_revision(db_session, fixture_path("322CO0000000016.xml"))
    # 2. API を叩く
    resp = await client.get("/api/2/law_data/322CO0000000016",
                            params={"response_format": "xml"})
    # 3. レスポンス形状を検証
    assert resp.status_code == 200
    assert "<Law" in resp.text
```

## 5. トレードオフと注意点

| 項目 | 内容 |
|---|---|
| 起動が遅い | Postgres コンテナの起動に数秒〜十数秒。`scope="session"` で 1 回に抑える |
| Docker 必須 | CI / 開発者ローカルに Docker が必要（GitHub Actions のデフォルトに同梱） |
| メモリ消費 | コンテナごとに数十〜数百 MB。並列度を計画的に |
| イメージ pull | 初回のみ時間がかかる。CI ではイメージキャッシュを設定 |
| Docker-in-Docker | CI 上で Docker を使う際の権限設定に注意（GitHub Actions では問題なし） |

## 6. 代替候補と不採用理由

| 候補 | 理由 |
|---|---|
| `pytest-postgresql` | ホストインストール済みの Postgres プロセスを起動。`pg_bigm` 等の拡張をホストに入れる運用が必要で開発者ローカルの摩擦が大きい |
| 手動 `docker-compose` + pytest fixture | コンテナのライフサイクル管理を自前で書く必要があり、Testcontainers と比べた利点が薄い |
| Neon / Supabase の branch DB | 外部依存になり CI のオフライン実行が不可。コスト要件もある |
| SQLite | 中核機能（`ltree` / `pg_bigm` / `tsvector` / `EXCLUDE` / `LISTEN/NOTIFY`）が無い |

## 7. CI 設定の概略

GitHub Actions の例（`.github/workflows/test.yml`）:

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: docker build -t laws-api-mirror-pg:16 docker/postgres/
      - run: uv sync
      - run: uv run pytest
```

GitHub Actions の `ubuntu-latest` には Docker が同梱されているため、追加セットアップ不要。

## 8. 参考リンク

- Testcontainers Python: <https://testcontainers-python.readthedocs.io/>
- PostgresContainer モジュール: <https://testcontainers-python.readthedocs.io/en/latest/database.html>
- moto (AWS モック): <https://github.com/getmoto/moto>
- SeaweedFS: <https://github.com/seaweedfs/seaweedfs>
- Procrastinate testing: <https://procrastinate.readthedocs.io/en/stable/howto/testing.html>
