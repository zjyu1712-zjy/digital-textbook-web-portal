"""Local-only preview. Public deployment must use the supplied production setup."""
import argparse
from dataclasses import replace
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server

from .config import Config
from .server import create_app


class ThreadedServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser(description="本机预览；公网请使用部署说明中的 Gunicorn 配置")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    config = Config.from_env()
    config = replace(config, public_origin="http://127.0.0.1:" + str(args.port))
    app = create_app(config)
    try:
        with make_server("127.0.0.1", args.port, app, server_class=ThreadedServer) as server:
            print("本机预览：http://127.0.0.1:" + str(args.port), flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.close()


if __name__ == "__main__":
    main()
