"""サンプル DB の生成と、サンプル DB を使ったビューアの通しテスト。"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from sqlite_viewer import sample
from sqlite_viewer.app import create_app
from sqlite_viewer.db import Database

ALL_TABLES = [
    "access_logs",
    "customers",
    "empty_table",
    'odd "table" name',
    "order_items",
    "order_summary",
    "orders",
    "products",
    "お知らせ",
]


@pytest.fixture(scope="module")
def sample_db(tmp_path_factory):
    return sample.create_sample_db(
        tmp_path_factory.mktemp("sample") / "demo.db", log_rows=500
    )


@pytest.fixture(scope="module")
def client(sample_db):
    return TestClient(create_app(sample_db))


def _dump(path):
    conn = sqlite3.connect(path)
    try:
        return list(conn.iterdump())
    finally:
        conn.close()


def test_tables(sample_db):
    assert Database(sample_db).tables() == ALL_TABLES


def test_row_counts(sample_db):
    db = Database(sample_db)
    assert db.rows("customers").total == 200
    assert db.rows("products").total == 40
    assert db.rows("orders").total == 500
    assert db.rows("order_summary").total == 500
    assert db.rows("access_logs").total == 500
    assert db.rows("empty_table").total == 0


def test_deterministic(tmp_path):
    a = sample.create_sample_db(tmp_path / "a.db", log_rows=100)
    b = sample.create_sample_db(tmp_path / "b.db", log_rows=100)
    assert _dump(a) == _dump(b)


def test_foreign_keys_are_consistent(sample_db):
    conn = sqlite3.connect(sample_db)
    try:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


def test_does_not_overwrite(sample_db):
    with pytest.raises(FileExistsError):
        sample.create_sample_db(sample_db)


@pytest.mark.parametrize("table", ALL_TABLES)
def test_every_table_renders_and_sorts(client, sample_db, table):
    url = f"/tables/{table}"
    res = client.get(url)
    assert res.status_code == 200
    for column in Database(sample_db).columns(table):
        for order in ["asc", "desc"]:
            res = client.get(url, params={"sort": column.name, "order": order})
            assert res.status_code == 200, (column.name, order)


@pytest.mark.parametrize("table", ALL_TABLES)
def test_every_table_last_page(client, sample_db, table):
    pages = Database(sample_db).rows(table).pages
    res = client.get(f"/tables/{table}", params={"page": pages})
    assert res.status_code == 200
    assert f"{pages} / {pages} ページ" in res.text


def test_edge_case_text_is_escaped(client):
    res = client.get("/tables/お知らせ", params={"q": "script"})
    assert "<script>alert" not in res.text
    assert "&lt;script&gt;alert" in res.text


def test_search_japanese(client):
    res = client.get("/tables/customers", params={"q": "東京都"})
    assert res.status_code == 200
    assert "「東京都」に一致" in res.text


def test_search_literal_percent(sample_db):
    page = Database(sample_db).rows("お知らせ", search="100%")
    assert page.total == 1


def test_query_view(sample_db):
    result = Database(sample_db).query(
        "SELECT status, COUNT(*) FROM order_summary GROUP BY status ORDER BY status"
    )
    assert {r[0] for r in result.rows} <= set(sample.STATUSES)
    assert sum(r[1] for r in result.rows) == 500


def test_cli_creates_and_refuses_overwrite(tmp_path, capsys):
    out = tmp_path / "cli" / "demo.db"
    sample.main([str(out), "--log-rows", "10"])
    assert Database(out).rows("access_logs").total == 10
    with pytest.raises(SystemExit):
        sample.main([str(out)])
    sample.main([str(out), "--log-rows", "20", "--force"])
    assert Database(out).rows("access_logs").total == 20
