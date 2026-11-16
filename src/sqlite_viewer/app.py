"""FastAPI アプリケーション。"""

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .db import ColumnNotFoundError, Database, QueryError, TableNotFoundError

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.tests["instanceof_bytes"] = lambda v: isinstance(v, bytes)


def create_app(db_path: str | Path) -> FastAPI:
    db = Database(db_path)
    app = FastAPI(title="SQLite Viewer")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return templates.TemplateResponse(
            request, "index.html", {"db": db, "tables": db.tables()}
        )

    @app.get("/tables/{table}", response_class=HTMLResponse)
    def table(
        request: Request,
        table: str,
        page: int = Query(1, ge=1),
        per_page: int = Query(50, ge=1, le=1000),
        sort: str | None = None,
        order: Literal["asc", "desc"] = "asc",
    ):
        try:
            columns = db.columns(table)
            data = db.rows(
                table,
                page=page,
                per_page=per_page,
                sort=sort or None,
                desc=order == "desc",
            )
        except TableNotFoundError:
            raise HTTPException(status_code=404, detail="テーブルが見つかりません")
        except ColumnNotFoundError:
            raise HTTPException(status_code=400, detail="カラムが見つかりません")
        return templates.TemplateResponse(
            request,
            "table.html",
            {
                "db": db,
                "tables": db.tables(),
                "table": table,
                "columns": columns,
                "data": data,
            },
        )

    @app.get("/query", response_class=HTMLResponse)
    def query(request: Request, sql: str = ""):
        result = error = None
        if sql.strip():
            try:
                result = db.query(sql)
            except QueryError as e:
                error = str(e)
        return templates.TemplateResponse(
            request,
            "query.html",
            {
                "db": db,
                "tables": db.tables(),
                "sql": sql,
                "result": result,
                "error": error,
            },
        )

    return app
