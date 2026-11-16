import argparse


def main() -> None:
    import uvicorn

    from .app import create_app

    parser = argparse.ArgumentParser(description="SQLite の中身をブラウザで見るツール")
    parser.add_argument("db", help="SQLite データベースファイルのパス")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    app = create_app(args.db)
    print(f"http://{args.host}:{args.port}/ を開いてください")
    uvicorn.run(app, host=args.host, port=args.port)
