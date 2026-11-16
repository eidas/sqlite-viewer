import sqlite3

import pytest
from fastapi.testclient import TestClient

from sqlite_viewer.app import create_app
from sqlite_viewer.db import (
    ColumnNotFoundError,
    Database,
    QueryError,
    TableNotFoundError,
)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "sample.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, note TEXT, data BLOB);
        CREATE VIEW user_names AS SELECT name FROM users;
        """
    )
    conn.execute('CREATE TABLE "weird ""name""" (x INTEGER)')
    conn.executemany(
        "INSERT INTO users (name, note, data) VALUES (?, ?, ?)",
        [(f"user{i}", None if i % 2 else "<b>x</b>", b"\x00\x01") for i in range(120)],
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def client(db_path):
    return TestClient(create_app(db_path))


def test_tables(db_path):
    assert Database(db_path).tables() == ["user_names", "users", 'weird "name"']


def test_columns(db_path):
    cols = Database(db_path).columns("users")
    assert [c.name for c in cols] == ["id", "name", "note", "data"]
    assert cols[0].pk and cols[1].notnull


def test_rows_pagination(db_path):
    page = Database(db_path).rows("users", page=3, per_page=50)
    assert page.total == 120
    assert page.pages == 3
    assert len(page.rows) == 20


def test_rows_sort(db_path):
    db = Database(db_path)
    asc = db.rows("users", per_page=3, sort="id")
    assert [r[0] for r in asc.rows] == [1, 2, 3]
    desc = db.rows("users", per_page=3, sort="id", desc=True)
    assert [r[0] for r in desc.rows] == [120, 119, 118]
    # ページ送りしても並べ替えが効いていること
    page2 = db.rows("users", page=2, per_page=3, sort="id", desc=True)
    assert [r[0] for r in page2.rows] == [117, 116, 115]


def test_rows_sort_nulls(db_path):
    # NULL は昇順で先頭に来る（SQLite の仕様）
    page = Database(db_path).rows("users", per_page=1, sort="note")
    assert page.rows[0][2] is None


def test_rows_sort_unknown_column(db_path):
    with pytest.raises(ColumnNotFoundError):
        Database(db_path).rows("users", sort='id" DESC; --')


def test_unknown_table(db_path):
    with pytest.raises(TableNotFoundError):
        Database(db_path).rows("users; DROP TABLE users")


def test_read_only(db_path):
    with Database(db_path).connect() as conn, pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM users")


def test_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        Database(tmp_path / "nope.db")


def test_index_page(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "users" in res.text


def test_table_page(client):
    res = client.get("/tables/users", params={"page": 2})
    assert res.status_code == 200
    assert "120 行" in res.text
    assert "2 / 3 ページ" in res.text
    assert "BLOB (2 bytes)" in res.text
    assert "NULL" in res.text
    # HTML がエスケープされていること
    assert "&lt;b&gt;x&lt;/b&gt;" in res.text


def test_table_page_sort(client):
    res = client.get(
        "/tables/users", params={"sort": "id", "order": "desc", "per_page": 3}
    )
    assert res.status_code == 200
    assert 'aria-sort="descending"' in res.text
    # 並べ替え中の列見出しは昇順への切り替えリンクになる
    assert 'href="?page=1&amp;per_page=3&amp;sort=id&amp;order=asc"' in res.text
    # ページ送りリンクが並べ替え状態を引き継ぐ
    assert 'href="?page=2&amp;per_page=3&amp;sort=id&amp;order=desc"' in res.text
    assert "並べ替えを解除" in res.text
    assert res.text.index(">120<") < res.text.index(">119<")


def test_table_page_sort_bad_params(client):
    assert client.get("/tables/users", params={"sort": "nope"}).status_code == 400
    res = client.get("/tables/users", params={"sort": "id", "order": "x"})
    assert res.status_code == 422


def test_table_with_quotes_in_name(client):
    assert client.get('/tables/weird "name"').status_code == 200


def test_query(db_path):
    result = Database(db_path).query("SELECT id, name FROM users WHERE id <= 3")
    assert result.columns == ["id", "name"]
    assert result.rows == [(1, "user0"), (2, "user1"), (3, "user2")]
    assert not result.truncated


def test_query_truncated(db_path):
    result = Database(db_path).query("SELECT * FROM users", max_rows=100)
    assert len(result.rows) == 100
    assert result.truncated


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM users",
        "SELEC 1",
        "SELECT 1; SELECT 2",
        "ATTACH '{other}' AS other",
        "VACUUM INTO '{other}'",
    ],
)
def test_query_errors(db_path, sql):
    other = db_path.parent / "other.db"
    with pytest.raises(QueryError):
        Database(db_path).query(sql.format(other=other.as_posix()))
    assert Database(db_path).rows("users").total == 120
    assert not other.exists()


def test_query_pragma(db_path):
    result = Database(db_path).query("PRAGMA table_info(users)")
    assert [r[1] for r in result.rows] == ["id", "name", "note", "data"]


def test_query_timeout(db_path):
    slow = (
        "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c)"
        " SELECT COUNT(*) FROM c"
    )
    with pytest.raises(QueryError, match="中断"):
        Database(db_path).query(slow, timeout=0.2)


def test_query_page(client):
    res = client.get("/query", params={"sql": "SELECT name FROM users LIMIT 2"})
    assert res.status_code == 200
    assert "2 行" in res.text
    assert "user1" in res.text


def test_query_page_error(client):
    res = client.get("/query", params={"sql": "SELECT * FROM nope"})
    assert res.status_code == 200
    assert "no such table" in res.text


def test_query_page_empty(client):
    res = client.get("/query")
    assert res.status_code == 200
    assert "<textarea" in res.text


def test_table_not_found(client):
    assert client.get("/tables/nope").status_code == 404
