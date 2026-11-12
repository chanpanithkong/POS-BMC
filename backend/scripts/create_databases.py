"""Creates pims_db and pims_test_db if they do not exist. Never drops or alters an existing database.

Run:  .venv\\Scripts\\python.exe -m scripts.create_databases
"""

import sys

import psycopg
from psycopg import sql

from app.core.config import get_settings


def main() -> int:
    settings = get_settings()
    if not settings.db_password.get_secret_value():
        print("DB_PASSWORD is empty in backend/.env. Add your postgres password and run again.")
        return 1
    conninfo = psycopg.conninfo.make_conninfo(
        host=settings.db_host, port=settings.db_port, user=settings.db_user, password=settings.db_password.get_secret_value(), dbname="postgres"
    )
    with psycopg.connect(conninfo, autocommit=True) as conn:
        for name in (settings.db_name, settings.test_db_name):
            exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
            if exists:
                print(f"{name}: already exists, left unchanged")
                continue
            conn.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0").format(sql.Identifier(name)))
            print(f"{name}: created")
    return 0


if __name__ == "__main__":
    sys.exit(main())
