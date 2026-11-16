"""FastAPI アプリケーション。"""

from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .db import (
    ColumnNotFoundError,
    Database,
    NotSQLiteError,
    QueryError,
    TableNotFoundError,
)

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.tests["instanceof_bytes"] = lambda v: isinstance(v, bytes)

MAX_RECENT = 10


class _NoDatabase(Exception):
    """DB が開かれていない状態で DB が必要な画面にアクセスした。"""


def _clean_path(raw: str) -> str:
    # エクスプローラーの「パスのコピー」で付く前後の " を取り除く
    return raw.strip().strip('"').strip()


def create_app(db_path: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="SQLite Viewer")
    # ローカルで 1 人が使う前提なので、開いている DB はアプリ全体で 1 つ
    state: dict = {"db": None, "recent": []}

    def open_db(path: str | Path) -> Database:
        db = Database(path)
        state["db"] = db
        recent = [p for p in state["recent"] if p != db.path]
        state["recent"] = [db.path, *recent][:MAX_RECENT]
        return db

    if db_path is not None:
        open_db(db_path)

    def current_db() -> Database:
        if state["db"] is None:
            raise _NoDatabase
        return state["db"]

    @app.exception_handler(_NoDatabase)
    def no_database(request: Request, exc: _NoDatabase):
        return RedirectResponse("/open", status_code=303)

    def render(request: Request, name: str, context: dict):
        db = state["db"]
        return templates.TemplateResponse(
            request,
            name,
            {"db": db, "tables": db.tables() if db else [], **context},
        )

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        current_db()
        return render(request, "index.html", {})

    @app.get("/open", response_class=HTMLResponse)
    def open_form(request: Request):
        return render(
            request, "open.html", {"recent": state["recent"], "path": "", "error": None}
        )

    @app.post("/open", response_class=HTMLResponse)
    async def open_submit(request: Request):
        # python-multipart に依存しないよう、フォームは自前でパースする
        form = parse_qs((await request.body()).decode("utf-8"))
        raw = form.get("path", [""])[0]
        path = _clean_path(raw)
        error = None
        if not path:
            error = "パスを入力してください"
        else:
            try:
                open_db(path)
                return RedirectResponse("/", status_code=303)
            except FileNotFoundError:
                error = f"ファイルが見つかりません: {path}"
            except NotSQLiteError:
                error = f"SQLite のデータベースファイルではありません: {path}"
            except OSError as e:
                error = f"ファイルを開けません: {e}"
        return render(
            request,
            "open.html",
            {"recent": state["recent"], "path": raw, "error": error},
        )

    @app.get("/tables/{table}", response_class=HTMLResponse)
    def table(
        request: Request,
        table: str,
        page: int = Query(1, ge=1),
        per_page: int = Query(50, ge=1, le=1000),
        sort: str | None = None,
        order: Literal["asc", "desc"] = "asc",
        q: str = "",
    ):
        db = current_db()
        try:
            columns = db.columns(table)
            data = db.rows(
                table,
                page=page,
                per_page=per_page,
                sort=sort or None,
                desc=order == "desc",
                # NUL があると LIKE のパターンがそこで切れて全件一致になるため除く
                search=q.replace("\x00", "").strip() or None,
            )
        except TableNotFoundError:
            raise HTTPException(status_code=404, detail="テーブルが見つかりません")
        except ColumnNotFoundError:
            raise HTTPException(status_code=400, detail="カラムが見つかりません")
        return render(
            request,
            "table.html",
            {"table": table, "columns": columns, "data": data},
        )

    @app.get("/query", response_class=HTMLResponse)
    def query(request: Request, sql: str = ""):
        db = current_db()
        result = error = None
        if sql.strip():
            try:
                result = db.query(sql)
            except QueryError as e:
                error = str(e)
        return render(
            request,
            "query.html",
            {"sql": sql, "result": result, "error": error},
        )

    return app
