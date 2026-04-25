from __future__ import annotations

import os
import time

import httpx


def require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"{name} is required")
    return v


def main() -> int:
    base = require_env("OCE_API_BASE").rstrip("/")
    r = httpx.get(base + "/health", timeout=5)
    r.raise_for_status()

    # This is only a connectivity smoke test; station flow tests come next.
    print({"health": r.json()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

