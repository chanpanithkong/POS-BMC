"""Development server launcher: python -m app.serve [--reload] [--port 8000]

psycopg's async driver cannot use the Windows Proactor event loop, so this sets
the selector loop before uvicorn starts. On Linux or in Docker, plain
`uvicorn app.main:app` works as well.
"""

import argparse

import uvicorn

from app.core.runtime import use_selector_loop


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the PIMS API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    use_selector_loop()
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload, proxy_headers=True)


if __name__ == "__main__":
    main()
