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

DB ファイルのパスは省略でき、その場合はブラウザの「DB を開く / 切り替え」画面でパスを入力して開きます。
起動中に別の DB へ切り替えることもでき、最近開いたファイル（最大 10 件）から選び直せます。
履歴はサーバーを止めると消えます。

> `--host 0.0.0.0` などで外部に公開すると、アクセスできる人がサーバー上の任意の SQLite ファイルを
> 開けるようになります。基本はデフォルトの `127.0.0.1` のまま使ってください。

## サンプル DB

動作確認・デモ用のサンプル DB を生成できます（乱数シード固定で毎回同じ内容）。

```powershell
uv run sqlite-viewer-sample            # samples\demo.db を作成
uv run sqlite-viewer samples\demo.db
```

| テーブル | 内容 |
|---|---|
| customers / products / orders | 顧客・商品・注文（日本語、NULL、BLOB を含む） |
| order_items | 注文明細（WITHOUT ROWID、複合主キー） |
| order_summary | 注文ごとの合計を出すビュー |
| access_logs | アクセスログ 10,000 行（ページ送り・検索用。`--log-rows` で変更可） |
| お知らせ | 日本語のテーブル名・カラム名、改行・絵文字・HTML 風などの特殊な文字列 |
| `odd "table" name` | 予約語・空白・ダブルクォートを含む名前 |
| empty_table | 空のテーブル |

既にファイルがある場合は上書きしません（`--force` で上書き）。`samples/` は git 管理外です。
テストでも同じ生成処理を使っています（`tests/test_sample.py`）。

## 開発

```powershell
uv run pytest          # テスト
uv run ruff format .   # フォーマット
uv run ruff check .    # リント
```
