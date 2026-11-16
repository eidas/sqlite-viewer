import argparse


def main() -> None:
    import uvicorn

    from .app import create_app

    parser = argparse.ArgumentParser(description="SQLite の中身をブラウザで見るツール")
    parser.add_argument(
        "db",
        nargs="?",
        help="SQLite データベースファイルのパス（省略時はブラウザから選択）",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    from .db import NotSQLiteError

    try:
        app = create_app(args.db)
    except FileNotFoundError:
        parser.error(f"ファイルが見つかりません: {args.db}")
    except NotSQLiteError:
        parser.error(f"SQLite のデータベースファイルではありません: {args.db}")
    print(f"http://{args.host}:{args.port}/ を開いてください")
    uvicorn.run(app, host=args.host, port=args.port)
