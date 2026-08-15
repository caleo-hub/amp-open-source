import hashlib
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from ..config.settings import database_settings


MIGRATIONS_DIR = Path(__file__).parent / "migrations"
MIGRATION_LOCK_KEY = 873421


@contextmanager
def connection(search_path: str = "amp,public"):
    settings = database_settings()
    with psycopg.connect(
        **settings.kwargs(search_path),
        row_factory=dict_row,
    ) as conn:
        yield conn


def run_migrations() -> None:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        raise RuntimeError("Nenhuma migração encontrada.")

    with connection("amp,public") as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_KEY,))
        try:
            conn.execute("CREATE SCHEMA IF NOT EXISTS amp")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS amp.schema_migrations (
                    version TEXT PRIMARY KEY,
                    checksum TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            conn.commit()

            for migration in files:
                checksum = hashlib.sha256(
                    migration.read_bytes()
                ).hexdigest()
                row = conn.execute(
                    "SELECT checksum FROM amp.schema_migrations WHERE version = %s",
                    (migration.name,),
                ).fetchone()
                if row:
                    if row["checksum"] != checksum:
                        raise RuntimeError(
                            f"Checksum divergente na migração {migration.name}."
                        )
                    continue

                sql = migration.read_text(encoding="utf-8")
                try:
                    conn.execute(sql)
                    conn.execute(
                        """
                        INSERT INTO amp.schema_migrations(version, checksum)
                        VALUES (%s, %s)
                        """,
                        (migration.name, checksum),
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_KEY,))


def setup_langgraph() -> None:
    from langgraph.checkpoint.postgres import PostgresSaver

    dsn = database_settings().dsn("langgraph,public")
    with PostgresSaver.from_conn_string(dsn) as checkpointer:
        checkpointer.setup()
