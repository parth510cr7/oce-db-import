from __future__ import annotations

import os

import psycopg
from psycopg.rows import dict_row


def require_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    return url


def connect() -> psycopg.Connection:
    return psycopg.connect(require_database_url(), row_factory=dict_row)

