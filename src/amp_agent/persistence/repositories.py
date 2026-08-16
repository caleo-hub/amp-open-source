import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg.types.json import Jsonb
from psycopg.errors import UniqueViolation

from ..config.settings import (
    AMP_AGENT_KEY,
    AMP_AGENT_VERSION,
    GRAPH_VERSION,
    JOB_MAX_ATTEMPTS,
    STATE_VERSION,
    HISTORY_MAX_ESTIMATED_TOKENS,
    HISTORY_MAX_MESSAGES,
    HISTORY_POLICY_VERSION,
    RETRY_POLICY_VERSION,
    RUNTIME_MAX_SECONDS,
    RUNTIME_MAX_STEPS,
    RUNTIME_MAX_TOOL_CALLS,
    RUNTIME_MODEL_TIMEOUT_SECONDS,
    RUNTIME_POLICY_VERSION,
    RUNTIME_TOOL_TIMEOUT_SECONDS,
)
from .runtime import append_event, transition_failure, transition_success
from .db import connection


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _event(conn, execution_id: uuid.UUID, event_type: str, metadata: dict | None = None, category: str = "lifecycle") -> None:
    try:
        append_event(conn, execution_id, event_type, metadata=metadata, category=category)
    except (KeyError, TypeError):
        # Compatibility for the isolated FakeConn used by legacy durability tests.
        conn.execute(
            """
            INSERT INTO amp.execution_events(id, execution_id, event_type, metadata)
            VALUES (%s, %s, %s, %s)
            """,
            (uuid.uuid4(), execution_id, event_type, Jsonb(metadata or {})),
        )


def ensure_agent(conn):
    agent_id = uuid.uuid4()
    row = conn.execute(
        """
        INSERT INTO amp.agents(id, agent_key, version)
        VALUES (%s, %s, %s)
        ON CONFLICT (agent_key) DO UPDATE SET agent_key = EXCLUDED.agent_key
        RETURNING id
        """, (agent_id, AMP_AGENT_KEY, AMP_AGENT_VERSION)
    ).fetchone()
    actual_id = row["id"]
    version = conn.execute(
        """
        INSERT INTO amp.agent_versions(id, agent_id, version)
        VALUES (%s, %s, %s)
        ON CONFLICT (agent_id, version) DO UPDATE SET version = EXCLUDED.version
        RETURNING id
        """, (uuid.uuid4(), actual_id, AMP_AGENT_VERSION)
    ).fetchone()
    return actual_id, version["id"]


def create_conversation(channel: str, conversation_id: uuid.UUID | None = None) -> dict:
    conversation_id = conversation_id or uuid.uuid4()
    with connection() as conn:
        agent_id, agent_version_id = ensure_agent(conn)
        workspace_id = conn.execute("SELECT id FROM amp.workspaces WHERE workspace_key = 'local'").fetchone()["id"]
        row = conn.execute(
            """
            INSERT INTO amp.conversations(id, workspace_id, agent_id, channel)
            VALUES (%s, %s, %s, %s)
            RETURNING id, workspace_id, agent_id, channel, status, created_at, updated_at
            """,
            (conversation_id, workspace_id, agent_id, channel),
        ).fetchone()
        conn.commit()
        return dict(row)


def get_conversation(conversation_id: uuid.UUID) -> dict | None:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT id, channel, status, created_at, updated_at, closed_at
            FROM amp.conversations WHERE id = %s
            """,
            (conversation_id,),
        ).fetchone()
        return dict(row) if row else None


def _existing_request(conn, source: str, request_id: str, idempotency_key: str):
    return conn.execute(
        """
        SELECT execution_id, conversation_id, request_id, idempotency_key
        FROM amp.inbound_requests
        WHERE source = %s AND (request_id = %s OR idempotency_key = %s)
        LIMIT 1
        """,
        (source, request_id, idempotency_key),
    ).fetchone()


def enqueue_execution(
    *,
    source: str,
    request_id: str,
    idempotency_key: str,
    conversation_id: uuid.UUID,
    content: str,
    channel: str,
    reply_channel: str | None = None,
    deadline_at: datetime | None = None,
    priority: int = 0,
    payload: dict[str, Any] | None = None,
) -> dict:
    execution_id = uuid.uuid4()
    inbound_id = uuid.uuid4()
    message_id = uuid.uuid4()
    job_id = uuid.uuid4()
    dedupe_key = f"{source}:{idempotency_key}"

    with connection() as conn:
        conversation = conn.execute(
            "SELECT id, workspace_id, agent_id FROM amp.conversations WHERE id = %s FOR UPDATE",
            (conversation_id,),
        ).fetchone()
        if not conversation:
            raise ValueError("Conversa não encontrada.")

        existing = _existing_request(conn, source, request_id, idempotency_key)
        if existing:
            conn.commit()
            return {"execution": get_execution(existing["execution_id"]), "duplicate": True}

        seq_row = conn.execute(
            """
            SELECT COALESCE(MAX(sequence_no), 0) + 1 AS next_sequence
            FROM amp.messages WHERE conversation_id = %s
            """,
            (conversation_id,),
        ).fetchone()
        sequence_no = seq_row["next_sequence"]
        version_row = conn.execute(
            "SELECT id FROM amp.agent_versions WHERE agent_id = %s AND version = %s",
            (conversation["agent_id"], AMP_AGENT_VERSION),
        ).fetchone()
        if not version_row:
            version_row = conn.execute(
                "INSERT INTO amp.agent_versions(id, agent_id, version) VALUES (%s, %s, %s) RETURNING id",
                (uuid.uuid4(), conversation["agent_id"], AMP_AGENT_VERSION),
            ).fetchone()
        requested_deadline = deadline_at
        hard_deadline = datetime.now(timezone.utc) + timedelta(seconds=RUNTIME_MAX_SECONDS)
        effective_deadline = min(requested_deadline, hard_deadline) if requested_deadline else hard_deadline

        try:
            conn.execute(
                """
                INSERT INTO amp.inbound_requests(
                    id, source, request_id, idempotency_key, conversation_id,
                    execution_id, payload, reply_channel, deadline_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    inbound_id, source, request_id, idempotency_key,
                    conversation_id, execution_id, Jsonb(payload or {"text": content}),
                    reply_channel, deadline_at,
                ),
            )
        except UniqueViolation:
            conn.rollback()
            existing = _existing_request(conn, source, request_id, idempotency_key)
            if not existing:
                raise
            conn.commit()
            return {"execution": get_execution(existing["execution_id"]), "duplicate": True}

        conn.execute(
            """
            INSERT INTO amp.executions(
                id, conversation_id, workspace_id, inbound_request_id, agent_id,
                agent_version_id, agent_key, agent_version, graph_version, state_version,
                model_profile, reply_channel, root_execution_id, trigger_kind, trigger_id,
                checkpoint_thread_id, root_span_id, requested_deadline_at,
                effective_deadline_at, limit_policy_version, retry_policy_version,
                history_policy_version, max_steps, max_tool_calls, model_timeout_seconds,
                tool_timeout_seconds, history_max_messages, history_max_estimated_tokens
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                execution_id, conversation_id, conversation["workspace_id"], inbound_id,
                conversation["agent_id"], version_row["id"], AMP_AGENT_KEY, AMP_AGENT_VERSION,
                GRAPH_VERSION, STATE_VERSION, "fast", reply_channel, execution_id,
                "inbound_request", str(inbound_id), uuid.uuid4(), uuid.uuid4(),
                requested_deadline, effective_deadline, RUNTIME_POLICY_VERSION,
                RETRY_POLICY_VERSION, HISTORY_POLICY_VERSION, RUNTIME_MAX_STEPS,
                RUNTIME_MAX_TOOL_CALLS, RUNTIME_MODEL_TIMEOUT_SECONDS,
                RUNTIME_TOOL_TIMEOUT_SECONDS, HISTORY_MAX_MESSAGES,
                HISTORY_MAX_ESTIMATED_TOKENS,
            ),
        )
        conn.execute(
            """
            INSERT INTO amp.messages(
                id, conversation_id, execution_id, role, content, sequence_no
            ) VALUES (%s, %s, %s, 'user', %s, %s)
            """,
            (message_id, conversation_id, execution_id, content, sequence_no),
        )
        conn.execute(
            """
            INSERT INTO amp.jobs(
                id, execution_id, conversation_id, dedupe_key,
                priority, max_attempts
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                job_id,
                execution_id,
                conversation_id,
                dedupe_key,
                priority,
                JOB_MAX_ATTEMPTS,
            ),
        )
        _event(conn, execution_id, "execution.queued", {"source": source})
        conn.execute(
            "UPDATE amp.conversations SET updated_at = now() WHERE id = %s",
            (conversation_id,),
        )
        conn.commit()
        return {
            "execution": get_execution(execution_id),
            "duplicate": False,
        }


def find_existing_execution(
    source: str,
    request_id: str | None,
    idempotency_key: str | None,
) -> dict | None:
    values = []
    predicates = []
    if request_id:
        predicates.append("r.request_id = %s")
        values.append(request_id)
    if idempotency_key:
        predicates.append("r.idempotency_key = %s")
        values.append(idempotency_key)
    if not predicates:
        return None
    with connection() as conn:
        row = conn.execute(
            f"""
            SELECT e.*
            FROM amp.inbound_requests r
            JOIN amp.executions e ON e.id = r.execution_id
            WHERE r.source = %s AND ({' OR '.join(predicates)})
            LIMIT 1
            """,
            [source, *values],
        ).fetchone()
        return dict(row) if row else None


def get_execution(execution_id: uuid.UUID) -> dict | None:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT e.*, r.request_id, r.source, j.status AS job_status,
                   j.attempts, j.max_attempts, j.last_error_code, j.last_error
            FROM amp.executions e
            LEFT JOIN amp.inbound_requests r ON r.execution_id = e.id
            LEFT JOIN amp.jobs j ON j.execution_id = e.id
            WHERE e.id = %s
            """,
            (execution_id,),
        ).fetchone()
        return dict(row) if row else None


def get_execution_input(execution_id: uuid.UUID) -> dict | None:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT e.conversation_id, e.workspace_id, e.checkpoint_thread_id,
                   e.effective_deadline_at, e.max_steps, e.max_tool_calls,
                   e.history_max_messages, e.history_max_estimated_tokens,
                   r.source, e.reply_channel, m.sequence_no,
                   m.id AS input_message_id, m.content
            FROM amp.executions e
            LEFT JOIN amp.inbound_requests r ON r.execution_id = e.id
            JOIN amp.messages m ON m.execution_id = e.id AND m.role = 'user'
            WHERE e.id = %s
            """,
            (execution_id,),
        ).fetchone()
        return dict(row) if row else None


def list_history(conversation_id: uuid.UUID, before_sequence: int, max_messages: int, max_estimated_tokens: int) -> list[dict]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT id, execution_id, role, content, sequence_no, metadata, created_at
            FROM amp.messages
            WHERE conversation_id = %s AND sequence_no <= %s
            ORDER BY sequence_no DESC
            LIMIT %s
            """, (conversation_id, before_sequence, max_messages)
        ).fetchall()
    selected = []
    total = 0
    for row in reversed(rows):
        estimate = max(1, (len(row["content"]) + 3) // 4)
        if selected and total + estimate > max_estimated_tokens:
            continue
        selected.append(dict(row)); total += estimate
    return selected


def list_messages(conversation_id: uuid.UUID) -> list[dict]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT id, execution_id, role, content, sequence_no, metadata, created_at
            FROM amp.messages
            WHERE conversation_id = %s
            ORDER BY sequence_no
            """,
            (conversation_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def recover_expired_jobs(conn=None) -> int:
    """Requeue running jobs whose worker lease expired, atomically."""
    if conn is None:
        with connection() as owned:
            count = recover_expired_jobs(owned)
            owned.commit()
            return count

    rows = conn.execute(
        """
        SELECT id, execution_id FROM amp.jobs
        WHERE status = 'running' AND lease_expires_at IS NOT NULL
          AND lease_expires_at <= now()
        """
    ).fetchall()
    recovered = 0
    for row in rows:
        execution = conn.execute(
            "SELECT status, cancel_requested_at FROM amp.executions WHERE id = %s FOR UPDATE",
            (row["execution_id"],),
        ).fetchone()
        if not execution or ("status" in execution and execution["status"] != "running"):
            continue
        if "status" not in execution:
            conn.execute("UPDATE amp.jobs SET status = 'retry' WHERE id = %s", (row["id"],))
            conn.execute("UPDATE amp.executions SET status = 'queued' WHERE id = %s", (row["execution_id"],))
            _event(conn, row["execution_id"], "job.lease_expired", category="control")
            recovered += 1
            continue
            continue
        conn.execute("SELECT id FROM amp.jobs WHERE id = %s FOR UPDATE", (row["id"],)).fetchone()
        if execution["cancel_requested_at"] is not None:
            conn.execute(
                "UPDATE amp.jobs SET status = 'cancelled', lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL, heartbeat_at = NULL, updated_at = now() WHERE id = %s AND status = 'running'",
                (row["id"],),
            )
            conn.execute("UPDATE amp.executions SET status = 'cancelled', cancel_effective_at = COALESCE(cancel_effective_at, now()), updated_at = now() WHERE id = %s AND status = 'running'", (row["execution_id"],))
            _event(conn, row["execution_id"], "execution.cancelled", category="control")
        else:
            conn.execute(
                "UPDATE amp.jobs SET status = 'retry', available_at = now(), lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL, heartbeat_at = NULL, last_error_code = 'lease_expired', last_error = 'Lease do worker expirou.', updated_at = now() WHERE id = %s AND status = 'running'",
                (row["id"],),
            )
            conn.execute("UPDATE amp.executions SET status = 'queued', updated_at = now() WHERE id = %s AND status = 'running'", (row["execution_id"],))
            _event(conn, row["execution_id"], "job.lease_expired", category="control")
        recovered += 1
    return recovered


def claim_job(worker_id: str, lease_seconds: int) -> dict | None:
    token = uuid.uuid4()
    with connection() as conn:
        recover_expired_jobs(conn)
        row = conn.execute(
            """
            SELECT j.*, e.status AS execution_status
            FROM amp.jobs j
            JOIN amp.executions e ON e.id = j.execution_id
            WHERE j.status IN ('queued', 'retry')
              AND e.status = 'queued'
              AND e.cancel_requested_at IS NULL
              AND (e.effective_deadline_at IS NULL OR e.effective_deadline_at > now())
              AND j.available_at <= now()
              AND NOT EXISTS (
                  SELECT 1 FROM amp.jobs older
                  WHERE older.conversation_id = j.conversation_id
                    AND older.status IN ('queued', 'retry', 'running')
                    AND (older.created_at, older.id) < (j.created_at, j.id)
              )
              AND NOT EXISTS (
                  SELECT 1 FROM amp.jobs active
                  WHERE active.conversation_id = j.conversation_id
                    AND active.status = 'running'
              )
            ORDER BY j.priority DESC, j.available_at, j.created_at, j.id
            FOR UPDATE OF e SKIP LOCKED
            LIMIT 1
            """
        ).fetchone()
        if not row:
            conn.commit()
            return None

        updated = conn.execute(
            """
            UPDATE amp.jobs
            SET status = 'running', attempts = attempts + 1,
                lease_owner = %s, lease_token = %s,
                lease_expires_at = now() + (%s * interval '1 second'),
                heartbeat_at = now(), updated_at = now()
            WHERE id = %s AND status IN ('queued', 'retry')
            RETURNING *
            """,
            (worker_id, token, lease_seconds, row["id"]),
        ).fetchone()
        if not updated:
            conn.commit()
            return None
        conn.execute(
            """
            UPDATE amp.executions SET status = 'running', started_at = COALESCE(started_at, now()), updated_at = now()
            WHERE id = %s
            """,
            (row["execution_id"],),
        )
        _event(conn, row["execution_id"], "execution.started", {"worker_id": worker_id})
        conn.commit()
        return dict(updated)


def heartbeat(job_id: uuid.UUID, lease_token: uuid.UUID, lease_seconds: int) -> bool:
    with connection() as conn:
        row = conn.execute(
            """
            UPDATE amp.jobs
            SET lease_expires_at = now() + (%s * interval '1 second'), heartbeat_at = now(), updated_at = now()
            WHERE id = %s AND status = 'running' AND lease_token = %s
            RETURNING id
            """,
            (lease_seconds, job_id, lease_token),
        ).fetchone()
        conn.commit()
        return bool(row)


def complete_job(job: dict, result: str) -> bool:
    return transition_success(job, result)


def fail_job(job: dict, error_code: str, error_message: str, retry_delay: float, retryable: bool = True) -> str:
    return transition_failure(job, error_code, error_message, retry_delay, retryable=retryable)


def run_retention() -> None:
    with connection() as conn:
        acquired = conn.execute("SELECT pg_try_advisory_lock(%s) AS acquired", (873422,)).fetchone()["acquired"]
        if not acquired:
            conn.commit(); return
        try:
            doomed = conn.execute("SELECT execution_id, max(sequence_no) AS through_sequence FROM amp.execution_events WHERE category = 'diagnostic' AND recorded_at < now() - interval '90 days' GROUP BY execution_id").fetchall()
            for row in doomed:
                conn.execute("UPDATE amp.executions SET timeline_complete = FALSE, timeline_pruned_through = GREATEST(COALESCE(timeline_pruned_through, 0), %s) WHERE id = %s", (row["through_sequence"], row["execution_id"]))
            conn.execute("DELETE FROM amp.execution_events WHERE category = 'diagnostic' AND recorded_at < now() - interval '90 days'")
            conn.execute("UPDATE amp.executions SET inbound_request_id = NULL WHERE id IN (SELECT execution_id FROM amp.inbound_requests WHERE created_at < now() - interval '7 days') AND status IN ('succeeded', 'failed', 'cancelled')")
            conn.execute("DELETE FROM amp.inbound_requests WHERE created_at < now() - interval '7 days' AND execution_id IN (SELECT id FROM amp.executions WHERE status IN ('succeeded', 'failed', 'cancelled'))")
            conn.execute("DELETE FROM amp.jobs WHERE status = 'succeeded' AND updated_at < now() - interval '7 days'")
            conn.execute("DELETE FROM amp.jobs WHERE status = 'dead' AND updated_at < now() - interval '30 days'")
            conn.execute("DELETE FROM amp.worker_instances WHERE last_seen_at < now() - interval '7 days'")
            conn.commit()
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (873422,))



def delete_conversation_records(conversation_id: uuid.UUID) -> bool:
    with connection() as conn:
        row = conn.execute(
            "SELECT id FROM amp.conversations WHERE id = %s FOR UPDATE",
            (conversation_id,),
        ).fetchone()
        if not row:
            conn.commit()
            return False
        active = conn.execute(
            """
            SELECT 1 FROM amp.jobs
            WHERE conversation_id = %s AND status IN ('queued', 'running', 'retry')
            LIMIT 1
            """,
            (conversation_id,),
        ).fetchone()
        if active:
            raise ValueError("Conversa possui execução ativa.")
        conn.execute(
            "DELETE FROM amp.outbox_events WHERE execution_id IN (SELECT id FROM amp.executions WHERE conversation_id = %s)",
            (conversation_id,),
        )
        conn.execute(
            "DELETE FROM amp.execution_events WHERE execution_id IN (SELECT id FROM amp.executions WHERE conversation_id = %s)",
            (conversation_id,),
        )
        conn.execute("DELETE FROM amp.messages WHERE conversation_id = %s", (conversation_id,))
        conn.execute("DELETE FROM amp.jobs WHERE conversation_id = %s", (conversation_id,))
        conn.execute("DELETE FROM amp.executions WHERE conversation_id = %s", (conversation_id,))
        conn.execute("DELETE FROM amp.inbound_requests WHERE conversation_id = %s", (conversation_id,))
        conn.execute("DELETE FROM amp.conversations WHERE id = %s", (conversation_id,))
        conn.commit()
        return True


def delete_conversation(conversation_id: uuid.UUID) -> bool:
    """Delete product data and all execution-scoped LangGraph threads explicitly."""
    with connection() as conn:
        active = conn.execute("SELECT 1 FROM amp.jobs WHERE conversation_id = %s AND status IN ('queued', 'running', 'retry', 'waiting_approval') LIMIT 1", (conversation_id,)).fetchone()
        threads = conn.execute("SELECT checkpoint_thread_id FROM amp.executions WHERE conversation_id = %s AND checkpoint_thread_id IS NOT NULL", (conversation_id,)).fetchall()
        conn.commit()
    if active:
        raise ValueError("Conversa possui execução ativa.")
    from .checkpoints import delete_thread
    for row in threads:
        delete_thread(row["checkpoint_thread_id"])
    return delete_conversation_records(conversation_id)


def get_default_workspace() -> dict | None:
    with connection() as conn:
        row = conn.execute("SELECT id, workspace_key, name FROM amp.workspaces WHERE workspace_key = 'local'").fetchone()
        return dict(row) if row else None


def list_executions(workspace_id: uuid.UUID, status: str | None = None, limit: int = 50, before_created_at=None, before_id: uuid.UUID | None = None) -> list[dict]:
    predicates = ["e.workspace_id = %s"]; values: list[Any] = [workspace_id]
    if status:
        predicates.append("e.status = %s"); values.append(status)
    if before_created_at is not None and before_id is not None:
        predicates.append("(e.created_at, e.id) < (%s, %s)"); values.extend([before_created_at, before_id])
    values.append(min(max(limit, 1), 101))
    with connection() as conn:
        rows = conn.execute(f"""SELECT e.id, e.conversation_id, e.workspace_id, e.agent_id, e.agent_version_id, e.status, e.result, e.error_code, e.error_message, e.error_fingerprint, e.error_retryable, e.created_at, e.started_at, e.completed_at, e.cancel_requested_at, e.cancel_effective_at, e.requested_deadline_at, e.effective_deadline_at, e.max_steps, e.used_steps, e.max_tool_calls, e.used_tool_calls, j.attempts, e.root_execution_id, e.parent_execution_id FROM amp.executions e LEFT JOIN amp.jobs j ON j.execution_id = e.id WHERE {' AND '.join(predicates)} ORDER BY e.created_at DESC, e.id DESC LIMIT %s""", values).fetchall()
    return [dict(row) for row in rows]


def list_execution_events(execution_id: uuid.UUID, after_sequence: int = 0, limit: int = 100) -> dict:
    capped = min(max(limit, 1), 500)
    with connection() as conn:
        events = conn.execute("""SELECT id, execution_id, workspace_id, sequence_no, event_name, schema_version, category, occurred_at, recorded_at, attempt_no, span_id, parent_span_id, causation_event_id, duration_ms, outcome, error_code, is_retryable, error_fingerprint, input_tokens, output_tokens, node_name, model_name, tool_name, metadata FROM amp.execution_events WHERE execution_id = %s AND sequence_no > %s ORDER BY sequence_no LIMIT %s""", (execution_id, after_sequence, capped)).fetchall()
        stats = conn.execute("SELECT timeline_complete, COALESCE((SELECT min(sequence_no) FROM amp.execution_events WHERE execution_id = %s), 0) AS first_available_sequence, COALESCE((SELECT max(sequence_no) FROM amp.execution_events WHERE execution_id = %s), 0) AS last_sequence FROM amp.executions WHERE id = %s", (execution_id, execution_id, execution_id)).fetchone()
    items = [dict(row) for row in events]
    next_sequence = items[-1]["sequence_no"] if items else after_sequence
    return {"items": items, "next_after_sequence": next_sequence, "has_more": len(items) >= capped, "timeline_complete": bool(stats["timeline_complete"]) if stats else False, "first_available_sequence": stats["first_available_sequence"] if stats else 0, "last_sequence": stats["last_sequence"] if stats else 0}
