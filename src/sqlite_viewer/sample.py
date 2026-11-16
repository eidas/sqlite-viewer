"""テスト・デモ用のサンプル DB を生成する。

乱数のシードを固定しているので、何度作っても同じ内容になる。
ビューアの動作確認に使えるよう、次のようなデータを含める。

- 日本語のデータ、NULL、BLOB、長い文字列、改行・絵文字・HTML 風の文字列
- 外部キーでつながったテーブルと、それらを集計したビュー
- 日本語・予約語・空白・ダブルクォートを含むテーブル名やカラム名
- WITHOUT ROWID テーブル、空のテーブル
- ページ送りや検索を試せる大きめのテーブル（access_logs）
"""

import argparse
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_OUTPUT = Path("samples") / "demo.db"
BASE_TIME = datetime(2026, 1, 1, 9, 0, 0)

SCHEMA = """
CREATE TABLE customers (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    email       TEXT    NOT NULL UNIQUE,
    prefecture  TEXT,
    birthday    TEXT,
    is_member   INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL
);

CREATE TABLE products (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    category    TEXT    NOT NULL,
    price       INTEGER NOT NULL CHECK (price >= 0),
    stock       INTEGER NOT NULL DEFAULT 0,
    description TEXT,
    thumbnail   BLOB
);

CREATE TABLE orders (
    id          INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers (id),
    ordered_at  TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT '受付'
);
CREATE INDEX idx_orders_customer ON orders (customer_id);

CREATE TABLE order_items (
    order_id    INTEGER NOT NULL REFERENCES orders (id),
    product_id  INTEGER NOT NULL REFERENCES products (id),
    quantity    INTEGER NOT NULL,
    unit_price  INTEGER NOT NULL,
    PRIMARY KEY (order_id, product_id)
) WITHOUT ROWID;

CREATE TABLE access_logs (
    id          INTEGER PRIMARY KEY,
    accessed_at TEXT    NOT NULL,
    path        TEXT    NOT NULL,
    status_code INTEGER NOT NULL,
    response_ms REAL    NOT NULL,
    user_agent  TEXT
);
CREATE INDEX idx_access_logs_path ON access_logs (path);

CREATE TABLE お知らせ (
    id          INTEGER PRIMARY KEY,
    タイトル    TEXT    NOT NULL,
    本文        TEXT,
    公開        INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE "odd ""table"" name" (
    "select"          INTEGER,
    "group by"        TEXT,
    "col with space"  REAL
);

CREATE TABLE empty_table (
    id    INTEGER PRIMARY KEY,
    value TEXT
);

CREATE VIEW order_summary AS
SELECT
    o.id                             AS order_id,
    c.name                           AS customer,
    o.ordered_at                     AS ordered_at,
    o.status                         AS status,
    COUNT(i.product_id)              AS items,
    SUM(i.quantity * i.unit_price)   AS total
FROM orders o
JOIN customers c ON c.id = o.customer_id
LEFT JOIN order_items i ON i.order_id = o.id
GROUP BY o.id;
"""

LAST_NAMES = [
    "佐藤",
    "鈴木",
    "高橋",
    "田中",
    "伊藤",
    "渡辺",
    "山本",
    "中村",
    "小林",
    "加藤",
]
FIRST_NAMES = [
    "太郎",
    "花子",
    "一郎",
    "陽菜",
    "蓮",
    "結衣",
    "大翔",
    "さくら",
    "湊",
    "美咲",
]
PREFECTURES = [
    "北海道",
    "宮城県",
    "東京都",
    "神奈川県",
    "愛知県",
    "大阪府",
    "京都府",
    "福岡県",
    "沖縄県",
]
CATEGORIES = {
    "文房具": ["ボールペン", "ノート", "付箋", "消しゴム", "ホッチキス"],
    "食品": ["コーヒー豆", "緑茶", "せんべい", "チョコレート", "カップ麺"],
    "家電": [
        "USB ケーブル",
        "モバイルバッテリー",
        "イヤホン",
        "電気ケトル",
        "LED ライト",
    ],
    "書籍": [
        "SQL 入門",
        "Python 実践",
        "データベース設計",
        "Web 開発の基礎",
        "アルゴリズム図鑑",
    ],
}
STATUSES = ["受付", "発送済み", "配達完了", "キャンセル"]
PATHS = [
    "/",
    "/products",
    "/products/{id}",
    "/cart",
    "/checkout",
    "/login",
    "/api/search",
]
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) Safari/17.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0) Mobile Safari",
    "curl/8.5.0",
    None,
]

# 表示やエスケープの確認に使う特殊な文字列
EDGE_CASE_TEXTS = [
    "<script>alert('xss')</script>",
    "100% オフ_セール（% と _ を含む）",
    "改行を\n含む\n文字列",
    "絵文字 🍣🍺🎉 を含む",
    "とても長い文字列 " + "あいうえお" * 100,
    "ダブルクォート \" とシングルクォート ' とバックスラッシュ \\",
    "",
]


def _ts(rng: random.Random, days: int = 365) -> str:
    t = BASE_TIME + timedelta(seconds=rng.randrange(days * 24 * 60 * 60))
    return t.strftime("%Y-%m-%d %H:%M:%S")


def _fake_png(rng: random.Random) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + rng.randbytes(rng.randint(32, 256))


def create_sample_db(
    path: str | Path, *, log_rows: int = 10_000, seed: int = 42
) -> Path:
    """サンプル DB を path に作る。既にファイルがある場合は FileExistsError。"""
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)

    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)

        customers = []
        for i in range(1, 201):
            name = f"{rng.choice(LAST_NAMES)} {rng.choice(FIRST_NAMES)}"
            birthday = (
                None
                if rng.random() < 0.2
                else (datetime(1960, 1, 1) + timedelta(days=rng.randrange(365 * 45)))
                .date()
                .isoformat()
            )
            customers.append(
                (
                    i,
                    name,
                    f"user{i:03d}@example.com",
                    None if rng.random() < 0.1 else rng.choice(PREFECTURES),
                    birthday,
                    int(rng.random() < 0.4),
                    _ts(rng),
                )
            )
        conn.executemany(
            "INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?, ?)", customers
        )

        products = []
        pid = 0
        for category, names in CATEGORIES.items():
            for base in names:
                for variant in ["", " デラックス"]:
                    pid += 1
                    products.append(
                        (
                            pid,
                            base + variant,
                            category,
                            rng.randrange(100, 20000, 10),
                            rng.randint(0, 500),
                            rng.choice([None, f"{base}の説明です。", *EDGE_CASE_TEXTS]),
                            None if rng.random() < 0.3 else _fake_png(rng),
                        )
                    )
        conn.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)", products)
        prices = {p[0]: p[3] for p in products}

        orders, items = [], []
        for oid in range(1, 501):
            orders.append(
                (oid, rng.randint(1, len(customers)), _ts(rng), rng.choice(STATUSES))
            )
            for product_id in rng.sample(sorted(prices), rng.randint(1, 4)):
                items.append((oid, product_id, rng.randint(1, 5), prices[product_id]))
        conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", orders)
        conn.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?)", items)

        logs = []
        for lid in range(1, log_rows + 1):
            p = rng.choice(PATHS).replace("{id}", str(rng.randint(1, len(products))))
            logs.append(
                (
                    lid,
                    _ts(rng, days=30),
                    p,
                    rng.choices([200, 302, 404, 500], weights=[85, 8, 5, 2])[0],
                    round(rng.lognormvariate(3.5, 0.8), 2),
                    rng.choice(USER_AGENTS),
                )
            )
        conn.executemany("INSERT INTO access_logs VALUES (?, ?, ?, ?, ?, ?)", logs)

        notices = [
            (
                1,
                "サイトをリニューアルしました",
                "いつもご利用ありがとうございます。",
                1,
            ),
            (
                2,
                "年末年始の営業について",
                "12/29〜1/3 はお休みです。\nご了承ください。",
                1,
            ),
            (3, "下書き", None, 0),
        ]
        notices += [
            (i, f"特殊文字テスト {i - 3}", text, 1)
            for i, text in enumerate(EDGE_CASE_TEXTS, start=4)
        ]
        conn.executemany("INSERT INTO お知らせ VALUES (?, ?, ?, ?)", notices)

        conn.executemany(
            'INSERT INTO "odd ""table"" name" VALUES (?, ?, ?)',
            [
                (1, "a", 1.5),
                (2, None, -0.25),
                (None, "NULL だけの行もある", None),
                (2**62, "大きな整数", 1e100),
            ],
        )
        conn.commit()
    finally:
        conn.close()
    return path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="テスト・デモ用のサンプル DB を作る")
    parser.add_argument(
        "output",
        nargs="?",
        default=str(DEFAULT_OUTPUT),
        help=f"出力先（デフォルト: {DEFAULT_OUTPUT}）",
    )
    parser.add_argument(
        "--log-rows",
        type=int,
        default=10_000,
        help="access_logs の行数（デフォルト: 10000）",
    )
    parser.add_argument(
        "--force", action="store_true", help="出力先が既にあれば上書きする"
    )
    args = parser.parse_args(argv)

    output = Path(args.output)
    if output.exists():
        if not args.force:
            parser.error(f"既にファイルがあります（上書きは --force）: {output}")
        output.unlink()
    create_sample_db(output, log_rows=args.log_rows)
    print(f"サンプル DB を作成しました: {output}")
    print(f"表示するには: uv run sqlite-viewer {output}")
