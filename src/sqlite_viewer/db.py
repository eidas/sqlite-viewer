"""SQLite データベースへの読み取り専用アクセス。"""

import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Column:
    name: str
    type: str
    notnull: bool
    default: str | None
    pk: bool


@dataclass
class Page:
    columns: list[str]
    rows: list[tuple]
    total: int
    page: int
    per_page: int
    sort: str | None = None
    desc: bool = False

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.per_page))


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    truncated: bool


class TableNotFoundError(Exception):
    pass


class ColumnNotFoundError(Exception):
    pass


class QueryError(Exception):
    pass


_ALLOWED_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    sqlite3.SQLITE_RECURSIVE,
    sqlite3.SQLITE_PRAGMA,
}


def _read_only_authorizer(action: int, *_args) -> int:
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


def _quote(name: str) -> str:
    """識別子を SQLite 用にクォートする。"""
    return '"' + name.replace('"', '""') + '"'


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise FileNotFoundError(self.path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        # mode=ro で開き、誤ってデータを書き換えないようにする
        conn = sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True)
        with closing(conn):
            yield conn

    def tables(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master"
                " WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'"
                " ORDER BY name"
            ).fetchall()
        return [r[0] for r in rows]

    def _check(self, table: str) -> None:
        if table not in self.tables():
            raise TableNotFoundError(table)

    def columns(self, table: str) -> list[Column]:
        self._check(table)
        with self.connect() as conn:
            rows = conn.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
        return [
            Column(
                name=r[1], type=r[2], notnull=bool(r[3]), default=r[4], pk=bool(r[5])
            )
            for r in rows
        ]

    def rows(
        self,
        table: str,
        page: int = 1,
        per_page: int = 50,
        sort: str | None = None,
        desc: bool = False,
    ) -> Page:
        self._check(table)
        page = max(1, page)
        q = _quote(table)
        order_by = ""
        if sort is not None:
            # カラム名は実在するものだけを受け付け、クォートして埋め込む
            if sort not in [c.name for c in self.columns(table)]:
                raise ColumnNotFoundError(sort)
            order_by = f" ORDER BY {_quote(sort)} {'DESC' if desc else 'ASC'}"
        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM {q}").fetchone()[0]
            cur = conn.execute(
                f"SELECT * FROM {q}{order_by} LIMIT ? OFFSET ?",
                (per_page, (page - 1) * per_page),
            )
            columns = [d[0] for d in cur.description]
            rows = cur.fetchall()
        return Page(
            columns=columns,
            rows=rows,
            total=total,
            page=page,
            per_page=per_page,
            sort=sort,
            desc=desc,
        )

    def query(
        self, sql: str, max_rows: int = 1000, timeout: float = 10.0
    ) -> QueryResult:
        """任意の SQL を実行する。接続は読み取り専用なので書き込みは失敗する。"""
        deadline = time.monotonic() + timeout
        with self.connect() as conn:
            # 長時間かかるクエリは timeout 秒で中断する
            conn.set_progress_handler(lambda: time.monotonic() > deadline, 10_000)
            # mode=ro でも ATTACH や VACUUM INTO で別ファイルを作れてしまうため、
            # 読み取り系の操作だけを許可する
            conn.set_authorizer(_read_only_authorizer)
            try:
                cur = conn.execute(sql)
                if cur.description is None:
                    return QueryResult(columns=[], rows=[], truncated=False)
                columns = [d[0] for d in cur.description]
                rows = cur.fetchmany(max_rows + 1)
            except sqlite3.OperationalError as e:
                if str(e) == "interrupted":
                    raise QueryError(f"{timeout:g} 秒を超えたため中断しました") from e
                raise QueryError(str(e)) from e
            except (sqlite3.Error, sqlite3.Warning) as e:
                raise QueryError(str(e)) from e
        return QueryResult(
            columns=columns, rows=rows[:max_rows], truncated=len(rows) > max_rows
        )
