from uuid import UUID

from langgraph.checkpoint.postgres import PostgresSaver

from ..config.settings import database_settings
from .db import connection


def delete_thread(conversation_id: UUID) -> None:
    dsn = database_settings().dsn("langgraph,public")
    with PostgresSaver.from_conn_string(dsn) as checkpointer:
        checkpointer.delete_thread(str(conversation_id))


def delete_terminal_threads(checkpointer) -> int:
    with connection() as conn:
        rows = conn.execute("SELECT id, checkpoint_thread_id FROM amp.executions WHERE status IN ('succeeded', 'failed', 'cancelled') AND completed_at < now() - interval '7 days' AND checkpoint_thread_id IS NOT NULL").fetchall()
    for row in rows:
        checkpointer.delete_thread(str(row["checkpoint_thread_id"]))
    return len(rows)
