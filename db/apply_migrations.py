import os
import pathlib
import sys
from typing import Iterable

import psycopg


def iter_sql_files(migrations_dir: pathlib.Path) -> Iterable[pathlib.Path]:
    for p in sorted(migrations_dir.glob("*.sql")):
        if p.is_file():
            yield p


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required, e.g. postgresql://user:pass@localhost:5432/db", file=sys.stderr)
        return 2

    migrations_dir = pathlib.Path(__file__).resolve().parent / "migrations"
    if not migrations_dir.exists():
        print(f"Missing migrations dir: {migrations_dir}", file=sys.stderr)
        return 2

    with psycopg.connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                create table if not exists schema_migrations (
                  filename text primary key,
                  applied_at timestamptz not null default now()
                );
                """
            )

            for sql_path in iter_sql_files(migrations_dir):
                cur.execute("select 1 from schema_migrations where filename = %s", (sql_path.name,))
                already = cur.fetchone() is not None
                if already:
                    continue

                sql = sql_path.read_text(encoding="utf-8")
                print(f"Applying {sql_path.name}...")
                cur.execute(sql)
                cur.execute("insert into schema_migrations(filename) values (%s)", (sql_path.name,))

    print("Migrations complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

