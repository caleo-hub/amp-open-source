from uuid import UUID

from langgraph.checkpoint.postgres import PostgresSaver

from .config import database_settings


def delete_thread(conversation_id: UUID) -> None:
    dsn = database_settings().dsn("langgraph,public")
    with PostgresSaver.from_conn_string(dsn) as checkpointer:
        checkpointer.delete_thread(str(conversation_id))
