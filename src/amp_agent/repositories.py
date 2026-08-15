import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg.types.json import Jsonb

from .config import (
    AMP_AGENT_KEY,
    AMP_AGENT_VERSION,
    GRAPH_VERSION,
    JOB_MAX_ATTEMPTS,
    STATE_VERSION,
)
from .db import connection


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _event(conn, execution_id: uuid.UUID, event_type: str, metadata: dict | None = None) -> None:
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
        ON CONFLICT (agent_key) DO UPDATE SET version = EXCLUDED.version
        RETURNING id
        """,
        (agent_id, AMP_AGENT_KEY, AMP_AGENT_VERSION),
    ).fetchone()
    return row["id"]


def create_conversation(channel: str, conversation_id: uuid.UUID | None = None) -> dict:
    conversation_id = conversation_id or uuid.uuid4()
    with connection() as conn:
        agent_id = ensure_agent(conn)
        row = conn.execute(
            """
            INSERT INTO amp.conversations(id, agent_id, channel)
            VALUES (%s, %s, %s)
            RETURNING id, channel, status, created_at, updated_at
            """,
            (conversation_id, agent_id, channel),
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
        existing = _existing_request(conn, source, request_id, idempotency_key)
        if existing:
            conn.commit()
            return {"execution": get_execution(existing["execution_id"]), "duplicate": True}

        conversation = conn.execute(
            "SELECT id FROM amp.conversations WHERE id = %s FOR UPDATE",
            (conversation_id,),
        ).fetchone()
        if not conversation:
            raise ValueError("Conversa não encontrada.")

        seq_row = conn.execute(
            """
            SELECT COALESCE(MAX(sequence_no), 0) + 1 AS next_sequence
            FROM amp.messages WHERE conversation_id = %s
            """,
            (conversation_id,),
        ).fetchone()
        sequence_no = seq_row["next_sequence"]

        conn.execute(
            """
            INSERT INTO amp.inbound_requests(
                id, source, request_id, idempotency_key, conversation_id,
                execution_id, payload, reply_channel, deadline_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                inbound_id,
                source,
                request_id,
                idempotency_key,
                conversation_id,
                execution_id,
                Jsonb(payload or {"text": content}),
                reply_channel,
                deadline_at,
            ),
        )
        conn.execute(
            """
            INSERT INTO amp.executions(
                id, conversation_id, inbound_request_id, agent_key,
                agent_version, graph_version, state_version, model_profile,
                reply_channel
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                execution_id,
                conversation_id,
                inbound_id,
                AMP_AGENT_KEY,
                AMP_AGENT_VERSION,
                GRAPH_VERSION,
                STATE_VERSION,
                "fast",
                reply_channel,
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
            SELECT e.conversation_id, m.id AS input_message_id, m.content
            FROM amp.executions e
            JOIN amp.messages m ON m.execution_id = e.id AND m.role = 'user'
            WHERE e.id = %s
            """,
            (execution_id,),
        ).fetchone()
        return dict(row) if row else None


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


def claim_job(worker_id: str, lease_seconds: int) -> dict | None:
    token = uuid.uuid4()
    with connection() as conn:
        row = conn.execute(
            """
            SELECT j.*, e.status AS execution_status
            FROM amp.jobs j
            JOIN amp.executions e ON e.id = j.execution_id
            WHERE j.status IN ('queued', 'retry')
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
            FOR UPDATE OF j SKIP LOCKED
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
    with connection() as conn:
        row = conn.execute(
            """
            UPDATE amp.jobs
            SET status = 'succeeded', lease_owner = NULL, lease_token = NULL,
                lease_expires_at = NULL, updated_at = now()
            WHERE id = %s AND status = 'running' AND lease_token = %s
            RETURNING execution_id, conversation_id
            """,
            (job["id"], job["lease_token"]),
        ).fetchone()
        if not row:
            conn.commit()
            return False

        execution_id = row["execution_id"]
        conversation_id = row["conversation_id"]
        conn.execute(
            """
            UPDATE amp.executions
            SET status = 'succeeded', result = %s, completed_at = now(), updated_at = now()
            WHERE id = %s
            """,
            (result, execution_id),
        )
        seq = conn.execute(
            """
            SELECT COALESCE(MAX(sequence_no), 0) + 1 AS next_sequence
            FROM amp.messages WHERE conversation_id = %s
            """,
            (conversation_id,),
        ).fetchone()["next_sequence"]
        conn.execute(
            """
            INSERT INTO amp.messages(id, conversation_id, execution_id, role, content, sequence_no)
            VALUES (%s, %s, %s, 'assistant', %s, %s)
            ON CONFLICT (execution_id) WHERE role = 'assistant' DO NOTHING
            """,
            (uuid.uuid4(), conversation_id, execution_id, result, seq),
        )
        _event(conn, execution_id, "execution.completed")
        external = conn.execute(
            "SELECT reply_channel FROM amp.executions WHERE id = %s",
            (execution_id,),
        ).fetchone()["reply_channel"]
        if external:
            conn.execute(
                """
                INSERT INTO amp.outbox_events(id, execution_id, event_type, reply_channel, payload)
                VALUES (%s, %s, 'execution.completed', %s, %s)
                ON CONFLICT (execution_id, event_type) DO NOTHING
                """,
                (
                    uuid.uuid4(),
                    execution_id,
                    external,
                    Jsonb({"execution_id": str(execution_id), "speech": result, "ok": True}),
                ),
            )
        conn.execute(
            "UPDATE amp.conversations SET updated_at = now() WHERE id = %s",
            (conversation_id,),
        )
        conn.commit()
        return True


def fail_job(job: dict, error_code: str, error_message: str, retry_delay: float) -> str:
    with connection() as conn:
        current = conn.execute(
            "SELECT attempts, max_attempts, execution_id FROM amp.jobs WHERE id = %s AND lease_token = %s FOR UPDATE",
            (job["id"], job["lease_token"]),
        ).fetchone()
        if not current:
            conn.commit()
            return "stale"
        terminal = current["attempts"] >= current["max_attempts"]
        if terminal:
            conn.execute(
                """
                UPDATE amp.jobs
                SET status = 'dead', lease_owner = NULL, lease_token = NULL,
                    lease_expires_at = NULL, last_error_code = %s, last_error = %s, updated_at = now()
                WHERE id = %s
                """,
                ("max_retries_exceeded", error_message, job["id"]),
            )
            conn.execute(
                """
                UPDATE amp.executions
                SET status = 'failed', error_code = 'max_retries_exceeded',
                    error_message = %s, completed_at = now(), updated_at = now()
                WHERE id = %s
                """,
                (error_message, current["execution_id"]),
            )
            _event(
                conn,
                current["execution_id"],
                "job.dead",
                {"error_code": "max_retries_exceeded"},
            )
            _event(conn, current["execution_id"], "execution.failed", {"error_code": "max_retries_exceeded"})
            result = "dead"
        else:
            conn.execute(
                """
                UPDATE amp.jobs
                SET status = 'retry', available_at = now() + (%s * interval '1 second'),
                    lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
                    last_error_code = %s, last_error = %s, updated_at = now()
                WHERE id = %s
                """,
                (retry_delay, error_code, error_message, job["id"]),
            )
            conn.execute(
                "UPDATE amp.executions SET status = 'queued', updated_at = now() WHERE id = %s",
                (current["execution_id"],),
            )
            _event(conn, current["execution_id"], "job.retried", {"error_code": error_code})
            result = "retry"
        conn.commit()
        return result


def run_retention() -> None:
    with connection() as conn:
        acquired = conn.execute(
            "SELECT pg_try_advisory_lock(%s) AS acquired",
            (873422,),
        ).fetchone()["acquired"]
        if not acquired:
            conn.commit()
            return
        try:
            conn.execute(
                """
                DELETE FROM amp.execution_events
                WHERE created_at < now() - interval '90 days'
                """
            )
            conn.execute(
                """
                UPDATE amp.executions
                SET inbound_request_id = NULL
                WHERE id IN (
                    SELECT execution_id FROM amp.inbound_requests
                    WHERE created_at < now() - interval '7 days'
                )
                AND status IN ('succeeded', 'failed')
                """
            )
            conn.execute(
                """
                DELETE FROM amp.inbound_requests
                WHERE created_at < now() - interval '7 days'
                  AND execution_id IN (
                      SELECT id FROM amp.executions WHERE status IN ('succeeded', 'failed')
                  )
                """
            )
            conn.execute(
                """
                DELETE FROM amp.jobs
                WHERE status = 'succeeded' AND updated_at < now() - interval '7 days'
                """
            )
            conn.execute(
                """
                DELETE FROM amp.jobs
                WHERE status = 'dead' AND updated_at < now() - interval '30 days'
                """
            )
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
    """Delete product data and its LangGraph thread as one explicit operation."""
    with connection() as conn:
        active = conn.execute(
            """
            SELECT 1 FROM amp.jobs
            WHERE conversation_id = %s AND status IN ('queued', 'running', 'retry')
            LIMIT 1
            """,
            (conversation_id,),
        ).fetchone()
        conn.commit()
    if active:
        raise ValueError("Conversa possui execução ativa.")

    from .checkpoints import delete_thread

    delete_thread(conversation_id)
    return delete_conversation_records(conversation_id)
