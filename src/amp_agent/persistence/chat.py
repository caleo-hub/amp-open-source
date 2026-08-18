"""Persistence primitives for the local LangGraph Chat protocol."""
from __future__ import annotations
import uuid
import ast
import re
from datetime import datetime
from typing import Any
import json
from psycopg.types.json import Jsonb
from .db import connection


def _json_default(value: Any) -> Any:
    """Encode LangChain/Pydantic values without turning message content into repr()."""
    if isinstance(value, (uuid.UUID, datetime)):
        return str(value) if isinstance(value, uuid.UUID) else value.isoformat()
    # LangGraph exposes pending interrupts as ``Interrupt(id, value)``
    # objects. Preserve both fields so the AG-UI approval form can render the
    # actual action/arguments instead of receiving ``Interrupt(...)`` text.
    if hasattr(value, "id") and hasattr(value, "value"):
        return {"id": str(value.id), "value": value.value}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    if hasattr(value, "content"):
        return {
            "type": getattr(value, "type", value.__class__.__name__.lower()),
            "content": getattr(value, "content", None),
            "id": getattr(value, "id", None),
            "tool_calls": getattr(value, "tool_calls", None),
        }
    return str(value)


def protocol_json(value: Any) -> Any:
    """Return JSON-safe protocol payloads while preserving all renderable content."""
    return json.loads(json.dumps(value, default=_json_default, ensure_ascii=False))


def normalize_protocol_event(event: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    """Project Python LangGraph v3 events into the browser protocol envelope."""
    method = str(event.get("method") or "custom")
    if method == "messages-tuple":
        method = "messages"
    params = dict(event.get("params") or {})
    data = params.get("data", event.get("data"))
    # Python exposes messages/tools as (payload, metadata).  The React
    # assembler expects the payload, with metadata available separately.
    if method in {"messages", "tools"} and isinstance(data, (tuple, list)) and len(data) == 2 and isinstance(data[1], dict):
        params["data"] = data[0]
        params.setdefault("metadata", data[1])
    elif data is not None:
        params["data"] = data
    # A few LangGraph builds stringify Interrupt objects before exposing the
    # v3 values event. Decode that stable repr while the payload is still in
    # the worker, before protocol_json would otherwise preserve it as text.
    snapshot_data = params.get("data")
    if method in {"values", "updates"} and isinstance(snapshot_data, dict) and isinstance(snapshot_data.get("interrupts"), list):
        decoded: list[Any] = []
        for raw in snapshot_data["interrupts"]:
            if isinstance(raw, str):
                match = re.match(r"^Interrupt\(value=(.*), id=(['\"])(.*?)\2\)$", raw)
                if match:
                    try:
                        raw = {"id": match.group(3), "value": ast.literal_eval(match.group(1))}
                    except (SyntaxError, ValueError):
                        pass
            decoded.append(raw)
        snapshot_data["interrupts"] = decoded
        params["data"] = snapshot_data
    # LangGraph names its interrupt channel differently from the public
    # Agent Streaming Protocol.  The React controller consumes requests on
    # input.requested.
    if method == "interrupts":
        method = "input.requested"
        raw = params.get("data", data)
        if isinstance(raw, list) and raw:
            raw = raw[0]
        params["data"] = {
            "interrupt_id": (raw or {}).get("id") if isinstance(raw, dict) else None,
            "payload": (raw or {}).get("value", raw) if isinstance(raw, dict) else raw,
        }
    params.setdefault("namespace", [])
    native_seq = event.get("seq")
    key = f"native:{native_seq}" if native_seq is not None else f"event:{uuid.uuid4()}"
    return method, protocol_json(params), key


def append_stream_event(execution_id: uuid.UUID, method: str, params: dict[str, Any], event_key: str) -> dict:
    """Append one immutable v2 protocol event and return its durable cursor."""
    safe_params = protocol_json(params)
    namespace = safe_params.get("namespace", []) if isinstance(safe_params, dict) else []
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO amp.thread_stream_events(thread_id, run_id, event_key, method, namespace, params)
            SELECT conversation_id, id, %s, %s, %s, %s FROM amp.executions WHERE id = %s
            ON CONFLICT (run_id, event_key) DO UPDATE SET event_key = EXCLUDED.event_key
            RETURNING seq, thread_id, run_id, method, namespace, params, recorded_at
            """,
            (event_key, method, Jsonb(namespace), Jsonb(safe_params), execution_id),
        ).fetchone()
        if not row:
            raise RuntimeError("Execução não encontrada para evento de streaming.")
        conn.commit()
        return dict(row)


def append_lifecycle_event(execution_id: uuid.UUID, name: str, **detail: Any) -> dict:
    return append_stream_event(
        execution_id,
        "lifecycle",
        {"namespace": [], "data": {"event": name, **protocol_json(detail)}},
        f"lifecycle:{name}:{detail.get('attempt', '')}",
    )


def thread_stream_events(thread_id: uuid.UUID, after_seq: int = 0, limit: int = 250) -> list[dict]:
    with connection() as conn:
        rows = conn.execute(
            """SELECT seq, thread_id, run_id, method, namespace, params, recorded_at
                FROM amp.thread_stream_events
                WHERE thread_id = %s AND seq > %s
                ORDER BY seq LIMIT %s""",
            (thread_id, max(after_seq, 0), min(max(limit, 1), 1000)),
        ).fetchall()
        return [dict(row) for row in rows]

def list_threads(workspace_id: uuid.UUID, *, include_archived: bool = False, limit: int = 50) -> list[dict]:
    predicate = "" if include_archived else "AND c.archived_at IS NULL"
    with connection() as conn:
        rows = conn.execute(f"""
            SELECT c.id, c.workspace_id, c.channel, c.title, c.status, c.archived_at,
                   c.created_at, c.updated_at, c.last_message_at,
                   (SELECT count(*) FROM amp.executions e WHERE e.conversation_id = c.id) AS run_count
            FROM amp.conversations c WHERE c.workspace_id = %s {predicate}
              AND c.stream_protocol_version = 2
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
