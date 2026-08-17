"""Persistence primitives for the local LangGraph Chat protocol."""
from __future__ import annotations
import uuid
from datetime import datetime
from psycopg.types.json import Jsonb
from .db import connection

def list_threads(workspace_id: uuid.UUID, *, include_archived: bool = False, limit: int = 50) -> list[dict]:
    predicate = "" if include_archived else "AND c.archived_at IS NULL"
    with connection() as conn:
        rows = conn.execute(f"""
            SELECT c.id, c.workspace_id, c.channel, c.title, c.status, c.archived_at,
                   c.created_at, c.updated_at, c.last_message_at,
                   (SELECT count(*) FROM amp.executions e WHERE e.conversation_id = c.id) AS run_count
            FROM amp.conversations c WHERE c.workspace_id = %s {predicate}
            ORDER BY c.last_message_at DESC, c.id DESC LIMIT %s
            """, (workspace_id, limit)).fetchall()
        return [dict(row) for row in rows]

def update_thread(thread_id: uuid.UUID, *, title: str | None = None, archived: bool | None = None) -> dict | None:
    assignments: list[str] = []
    values: list[object] = []
    if title is not None:
        title = " ".join(title.split())[:120]
        if not title: raise ValueError("O título não pode ficar vazio.")
        assignments += ["title = %s"]; values += [title]
    if archived is not None:
        assignments += ["archived_at = %s"]; values += [datetime.now().astimezone() if archived else None]
    if not assignments: return get_thread(thread_id)
    assignments += ["updated_at = now()"]
    with connection() as conn:
        row = conn.execute(f"UPDATE amp.conversations SET {', '.join(assignments)} WHERE id = %s RETURNING id, workspace_id, channel, title, status, archived_at, created_at, updated_at, last_message_at", (*values, thread_id)).fetchone()
        conn.commit(); return dict(row) if row else None

def get_thread(thread_id: uuid.UUID) -> dict | None:
    with connection() as conn:
        row = conn.execute("""SELECT c.id, c.workspace_id, c.channel, c.title, c.status, c.archived_at,
            c.created_at, c.updated_at, c.last_message_at,
            (SELECT count(*) FROM amp.executions e WHERE e.conversation_id = c.id) AS run_count
            FROM amp.conversations c WHERE c.id = %s""", (thread_id,)).fetchone()
        return dict(row) if row else None

def thread_runs(thread_id: uuid.UUID, limit: int = 100) -> list[dict]:
    with connection() as conn:
        rows = conn.execute("""SELECT e.id, e.conversation_id, e.status, e.result, e.error_code,
            e.error_message, e.created_at, e.started_at, e.completed_at, e.checkpoint_thread_id,
            e.used_steps, e.used_tool_calls, r.request_id, j.attempts
            FROM amp.executions e LEFT JOIN amp.inbound_requests r ON r.execution_id = e.id
            LEFT JOIN amp.jobs j ON j.execution_id = e.id WHERE e.conversation_id = %s
            ORDER BY e.created_at DESC, e.id DESC LIMIT %s""", (thread_id, limit)).fetchall()
        return [dict(row) for row in rows]

def thread_events(thread_id: uuid.UUID, limit: int = 500) -> list[dict]:
    with connection() as conn:
        rows = conn.execute("""SELECT x.*, row_number() OVER (ORDER BY x.recorded_at, x.id) AS stream_sequence FROM amp.execution_events x
            JOIN amp.executions e ON e.id = x.execution_id WHERE e.conversation_id = %s
            ORDER BY x.recorded_at, x.id LIMIT %s""", (thread_id, limit)).fetchall()
        return [dict(row) for row in rows]

def put_note(workspace_id: uuid.UUID, note_key: str, content: str) -> dict:
    with connection() as conn:
        row = conn.execute("""INSERT INTO amp.notes(workspace_id, note_key, content) VALUES (%s, %s, %s)
            ON CONFLICT (workspace_id, note_key) DO UPDATE SET content = EXCLUDED.content, updated_at = now()
            RETURNING workspace_id, note_key, content, created_at, updated_at""", (workspace_id, note_key, content)).fetchone()
        conn.commit(); return dict(row)

def list_notes(workspace_id: uuid.UUID, limit: int = 20) -> list[dict]:
    with connection() as conn:
        rows = conn.execute("""SELECT note_key, content, created_at, updated_at
            FROM amp.notes WHERE workspace_id = %s ORDER BY updated_at DESC LIMIT %s""",
            (workspace_id, min(max(limit, 1), 100))).fetchall()
        return [dict(row) for row in rows]

def save_approval_decision(execution_id: uuid.UUID, tool_call_id: str, decision: dict) -> dict:
    with connection() as conn:
        row = conn.execute("""INSERT INTO amp.approval_decisions(execution_id, tool_call_id, decision)
            VALUES (%s, %s, %s) ON CONFLICT (execution_id, tool_call_id) DO UPDATE SET decision = EXCLUDED.decision
            RETURNING execution_id, tool_call_id, decision, created_at""", (execution_id, tool_call_id, Jsonb(decision))).fetchone()
        conn.commit(); return dict(row)

def pending_approval_decision(execution_id: uuid.UUID) -> dict | None:
    with connection() as conn:
        row = conn.execute("SELECT tool_call_id, decision FROM amp.approval_decisions WHERE execution_id = %s ORDER BY created_at DESC LIMIT 1", (execution_id,)).fetchone()
        return dict(row) if row else None

def resume_approval(execution_id: uuid.UUID, decision: dict) -> dict | None:
    with connection() as conn:
        execution = conn.execute("SELECT id, status FROM amp.executions WHERE id = %s FOR UPDATE", (execution_id,)).fetchone()
        if not execution: return None
        if execution["status"] not in {"waiting_approval", "running"}: return dict(execution)
        conn.execute("""INSERT INTO amp.approval_decisions(execution_id, tool_call_id, decision)
            VALUES (%s, %s, %s)
            ON CONFLICT (execution_id, tool_call_id) DO UPDATE SET decision = EXCLUDED.decision""",
            (execution_id, str(decision.get("tool_call_id") or "approval"), Jsonb(decision)))
        conn.execute("UPDATE amp.executions SET status = 'queued', updated_at = now() WHERE id = %s", (execution_id,))
        conn.execute("UPDATE amp.jobs SET status = 'queued', available_at = now(), lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL, updated_at = now() WHERE execution_id = %s", (execution_id,))
        conn.commit(); return {"id": execution_id, "status": "queued"}
