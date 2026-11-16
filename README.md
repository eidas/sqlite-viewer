# sqlite-viewer
SQLiteの中身をみるツール

ブラウザで SQLite データベースのテーブル一覧・スキーマ・データを閲覧できます。
データベースは読み取り専用で開くため、内容を書き換えることはありません。

サイドバーの「SQL 実行」から任意の SELECT 文を実行できます（Ctrl+Enter で実行）。

- 読み取り系の操作（SELECT / PRAGMA など）だけを許可し、ATTACH や VACUUM INTO などは拒否します
- 結果は先頭 1000 行まで表示します
- 10 秒を超えるクエリは中断します

## 使い方

```powershell
uv sync
uv run sqlite-viewer path\to\database.db
```

http://127.0.0.1:8000/ をブラウザで開きます。ポートは `--port` で変更できます。

## 開発

```powershell
uv run pytest          # テスト
uv run ruff format .   # フォーマット
uv run ruff check .    # リント
```
