# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## リポジトリの現状

このリポジトリは初期状態であり、現時点では `.gitignore`（Python 用テンプレート）と `docs/design.md`（設計書）のみが含まれている。ソースコード・ビルド設定・テストはまだ存在しない。

実装方針は `docs/design.md` を参照（FastAPI + PostgreSQL + Alembic + SQLAlchemy async、e-Gov 法令API v2 互換、法令XMLを正規化テーブルに展開）。

- リポジトリ名: `laws-api-mirror`
- 推定される性質: 日本の法令 API（e-Gov 法令 API など）をミラー／ラップする Python プロジェクトと見られるが、実装方針は未確定。
- 言語: `.gitignore` の内容から Python プロジェクトとして開始される見込み。

## 作業時の指針

1. **推測でファイルを増やさない**: パッケージ構成・フレームワーク選定・依存関係は未決定。ユーザーから方針が示されるまで `pyproject.toml`、ディレクトリ構成、エントリポイント等を勝手に作らない。
2. **方針確認を優先**: 機能追加の依頼を受けた場合、まずパッケージマネージャ（uv / poetry / pip）、フレームワーク（FastAPI など）、対象とする法令 API のエンドポイントをユーザーに確認する。
3. **このファイルの更新タイミング**: プロジェクト構成が定まった時点で、本 CLAUDE.md を以下の観点で書き直すこと:
   - よく使うコマンド（ビルド・lint・テスト実行・単体テスト実行）
   - 全体アーキテクチャ（複数ファイルを読まないと掴めない設計の概要）
   - 外部 API ミラーとしての同期戦略・キャッシュ方針・レート制限対応

## 言語に関する取り決め

CLAUDE.md は日本語で記述する。
