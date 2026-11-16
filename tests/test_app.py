import sqlite3

import pytest
from fastapi.testclient import TestClient

from sqlite_viewer.app import create_app
from sqlite_viewer.db import (
    ColumnNotFoundError,
    Database,
    NotSQLiteError,
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


def test_rows_search(db_path):
    db = Database(db_path)
    # name 列 "user1", "user10".."user19", "user100".."user119" に一致
    page = db.rows("users", per_page=200, search="user1")
    assert page.total == 1 + 10 + 20
    assert page.search == "user1"
    # 数値列（id）も文字列として検索される
    assert db.rows("users", search="120").total == 1
    # 大文字小文字を区別しない（ASCII）
    assert db.rows("users", search="USER119").total == 1


def test_rows_search_wildcards_are_literal(db_path):
    db = Database(db_path)
    assert db.rows("users", search="%").total == 0
    assert db.rows("users", search="_").total == 0
    # note 列の "<b>x</b>" に一致
    assert db.rows("users", search="<b>").total == 60


def test_rows_search_skips_blob(tmp_path):
    path = tmp_path / "blob.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE files (name TEXT, body BLOB)")
    conn.execute("INSERT INTO files VALUES ('a.txt', ?)", (b"findme",))
    conn.commit()
    conn.close()
    db = Database(path)
    assert db.rows("files", search="findme").total == 0
    assert db.rows("files", search="a.txt").total == 1


def test_table_page_search_ignores_nul(client):
    # LIKE は NUL で打ち切られて全件一致になるため、NUL は取り除く
    res = client.get("/tables/users", params={"q": "user119\x00"})
    assert "「user119」に一致: 1 行" in res.text


def test_rows_search_with_sort_and_page(db_path):
    page = Database(db_path).rows(
        "users", page=2, per_page=5, sort="id", desc=True, search="user1"
    )
    assert page.total == 31
    assert [r[0] for r in page.rows] == [115, 114, 113, 112, 111]


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


def test_table_page_search(client):
    res = client.get(
        "/tables/users",
        params={"q": "user1", "sort": "id", "order": "desc", "per_page": 5},
    )
    assert res.status_code == 200
    assert "「user1」に一致: 31 行" in res.text
    assert 'value="user1"' in res.text
    # ページ送り・見出しリンクが検索語を引き継ぐ
    assert 'href="?page=2&amp;per_page=5&amp;sort=id&amp;order=desc&amp;q=user1"' in (
        res.text
    )
    assert 'href="?page=1&amp;per_page=5&amp;sort=id&amp;order=asc&amp;q=user1"' in (
        res.text
    )
    # 検索解除リンクは検索語を外し、並べ替えは残す
    assert 'href="?page=1&amp;per_page=5&amp;sort=id&amp;order=desc">検索を解除' in (
        res.text
    )


def test_table_page_search_escaped(client):
    res = client.get("/tables/users", params={"q": '"><script>'})
    assert res.status_code == 200
    assert "<script>" not in res.text


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


def test_not_sqlite_file(tmp_path):
    path = tmp_path / "text.txt"
    path.write_text("hello, this is not a database")
    with pytest.raises(NotSQLiteError):
        Database(path)


def test_empty_file_is_empty_db(tmp_path):
    path = tmp_path / "empty.db"
    path.touch()
    assert Database(path).tables() == []


@pytest.fixture
def other_db(tmp_path):
    path = tmp_path / "other.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE products (id INTEGER, title TEXT)")
    conn.commit()
    conn.close()
    return path


def test_start_without_db_redirects_to_open(tmp_path):
    client = TestClient(create_app())
    for url in ["/", "/query", "/tables/users"]:
        res = client.get(url, follow_redirects=False)
        assert res.status_code == 303
        assert res.headers["location"] == "/open"
    res = client.get("/open")
    assert res.status_code == 200
    assert "データベースを開く" in res.text
    # DB 未選択時は SQL 実行のリンクを出さない
    assert 'href="/query"' not in res.text


def test_switch_db(client, db_path, other_db):
    assert "users" in client.get("/").text
    res = client.post("/open", data={"path": str(other_db)})
    assert res.status_code == 200
    assert str(res.url).endswith("/")
    assert 'href="/tables/products"' in res.text
    assert 'href="/tables/users"' not in res.text
    # 最近開いたファイルに両方出て、新しい順に並ぶ
    page = client.get("/open").text
    assert page.index(str(other_db)) < page.index(str(db_path))
    assert "（表示中）" in page


def test_switch_db_strips_quotes(client, other_db):
    res = client.post("/open", data={"path": f'  "{other_db}" '})
    assert "products" in res.text


def test_switch_db_errors(client, tmp_path):
    text = tmp_path / "text.txt"
    text.write_text("not a db")
    cases = [
        ("", "パスを入力してください"),
        (str(tmp_path / "nope.db"), "ファイルが見つかりません"),
        (str(tmp_path), "ファイルが見つかりません"),
        (str(text), "SQLite のデータベースファイルではありません"),
    ]
    for path, message in cases:
        res = client.post("/open", data={"path": path})
        assert res.status_code == 200
        assert message in res.text
    # 失敗しても元の DB は開いたまま
    assert "users" in client.get("/").text


def test_recent_dedup_and_limit(tmp_path):
    paths = []
    for i in range(12):
        p = tmp_path / f"db{i}.db"
        p.touch()
        paths.append(p)
    client = TestClient(create_app())
    for p in [*paths, paths[0]]:
        client.post("/open", data={"path": str(p)})
    page = client.get("/open").text
    assert page.count('name="path" value="') == 10 + 1  # 履歴 10 件 + 入力欄
    assert str(paths[0].resolve()) in page
    assert str(paths[1].resolve()) not in page


def test_table_not_found(client):
    assert client.get("/tables/nope").status_code == 404
