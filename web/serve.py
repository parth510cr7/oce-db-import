from __future__ import annotations

import argparse

import uvicorn


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the OCE OSCE Simulator web API (FastAPI).")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true")
    args = ap.parse_args()

    uvicorn.run("web.api:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

