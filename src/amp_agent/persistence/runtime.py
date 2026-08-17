from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg.types.json import Jsonb

from ..config.settings import (
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
from ..observability.sanitize import fingerprint_error, sanitize_metadata
from .db import connection

TERMINAL_EXECUTIONS = {"succeeded", "failed", "cancelled"}
RETRYABLE_CODES = {"worker_error", "dependency_unavailable", "model_timeout", "tool_timeout"}


class RuntimeControlError(RuntimeError):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code


class ExecutionCancelled(RuntimeControlError):
    def __init__(self):
        super().__init__("cancelled")


class RuntimeLimitExceeded(RuntimeControlError):
    def __init__(self, code: str):
        super().__init__(code)


def _category(event_name: str) -> str:
    if event_name.startswith(("execution.", "job.", "worker.")):
        return "control" if "cancel" in event_name or "limit" in event_name else "lifecycle"
    return "diagnostic"


def append_event(
    conn,
    execution_id: uuid.UUID,
    event_name: str,
    *,
    category: str | None = None,
    metadata: dict[str, Any] | None = None,
    attempt_no: int | None = None,
    span_id: uuid.UUID | None = None,
    parent_span_id: uuid.UUID | None = None,
    causation_event_id: uuid.UUID | None = None,
    duration_ms: float | None = None,
    outcome: str | None = None,
    error_code: str | None = None,
    is_retryable: bool | None = None,
    error_fingerprint: str | None = None,
    node_name: str | None = None,
    model_name: str | None = None,
    tool_name: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> dict:
    row = conn.execute(
        """
        UPDATE amp.executions
        SET next_event_sequence = next_event_sequence + 1
        WHERE id = %s
        RETURNING workspace_id, root_span_id, next_event_sequence - 1 AS sequence_no
        """,
        (execution_id,),
    ).fetchone()
    if not row:
        raise RuntimeError("Execução não encontrada para evento.")
    now = datetime.now(timezone.utc)
    span_id = span_id or row["root_span_id"]
    event_id = uuid.uuid4()
    conn.execute(
        """
        INSERT INTO amp.execution_events(
            id, execution_id, workspace_id, sequence_no, event_type, event_name,
            schema_version, category, node_name, tool_name, model_name,
            occurred_at, recorded_at, attempt_no, span_id, parent_span_id,
            causation_event_id, duration_ms, outcome, error_code, is_retryable,
            error_fingerprint, input_tokens, output_tokens, metadata
        ) VALUES (%s, %s, %s, %s, %s, %s, 1, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            event_id, execution_id, row["workspace_id"], row["sequence_no"], event_name,
            event_name, category or _category(event_name), node_name, tool_name, model_name,
            now, now, attempt_no, span_id, parent_span_id, causation_event_id,
            duration_ms, outcome, error_code, is_retryable, error_fingerprint,
            input_tokens, output_tokens, Jsonb(sanitize_metadata(metadata)),
        ),
    )
    return {"id": event_id, "sequence_no": row["sequence_no"], "span_id": span_id}


def record_event(execution_id: uuid.UUID, event_name: str, **kwargs: Any) -> dict:
    with connection() as conn:
        result = append_event(conn, execution_id, event_name, **kwargs)
        conn.commit()
        return result


def get_execution_control(execution_id: uuid.UUID) -> dict | None:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT id, status, conversation_id, workspace_id, root_span_id,
                   cancel_requested_at, cancel_effective_at, cancel_reason,
                   effective_deadline_at, max_steps, used_steps,
                   max_tool_calls, used_tool_calls
            FROM amp.executions WHERE id = %s
            """, (execution_id,)
        ).fetchone()
        return dict(row) if row else None


def assert_execution_active(execution_id: uuid.UUID, lease_token: uuid.UUID | None = None) -> dict:
    row = get_execution_control(execution_id)
    if not row:
        raise RuntimeControlError("execution_not_found")
    if row["status"] in TERMINAL_EXECUTIONS:
        raise RuntimeControlError(row["status"])
    if row["cancel_requested_at"] is not None:
        raise ExecutionCancelled()
    if row["effective_deadline_at"] and datetime.now(timezone.utc) >= row["effective_deadline_at"]:
        raise RuntimeLimitExceeded("deadline_exceeded")
    if lease_token is not None:
        with connection() as conn:
            lease = conn.execute(
                "SELECT id FROM amp.jobs WHERE execution_id = %s AND status = 'running' AND lease_token = %s",
                (execution_id, lease_token),
            ).fetchone()
            conn.commit()
        if not lease:
            raise RuntimeControlError("lease_lost")
    return row


def consume_budget(execution_id: uuid.UUID, kind: str) -> int:
    column = "used_steps" if kind == "step" else "used_tool_calls"
    limit_column = "max_steps" if kind == "step" else "max_tool_calls"
    with connection() as conn:
        row = conn.execute(
            f"""
            UPDATE amp.executions
            SET {column} = {column} + 1, updated_at = now()
            WHERE id = %s AND status = 'running'
              AND cancel_requested_at IS NULL
              AND {column} < {limit_column}
            RETURNING {column} AS used, {limit_column} AS maximum
            """, (execution_id,)
        ).fetchone()
        if not row:
            conn.rollback()
            raise RuntimeLimitExceeded("step_limit_exceeded" if kind == "step" else "tool_call_limit_exceeded")
        conn.commit()
        return row["used"]


def request_cancel(execution_id: uuid.UUID, reason: str = "user_requested", requested_by: dict | None = None) -> dict:
    with connection() as conn:
        execution = conn.execute(
            "SELECT * FROM amp.executions WHERE id = %s FOR UPDATE", (execution_id,)
        ).fetchone()
        if not execution:
            return {"found": False}
        if execution["status"] in TERMINAL_EXECUTIONS:
            conn.commit()
            return {"found": True, "status": execution["status"], "terminal": True}
        job = conn.execute(
            "SELECT * FROM amp.jobs WHERE execution_id = %s FOR UPDATE", (execution_id,)
        ).fetchone()
        if execution["cancel_requested_at"] is None:
            conn.execute(
                """
                UPDATE amp.executions
                SET cancel_requested_at = now(), cancel_reason = %s,
                    cancel_requested_by = %s, updated_at = now()
                WHERE id = %s
                """, (reason, Jsonb(sanitize_metadata(requested_by or {"type": "api"})), execution_id)
            )
            append_event(conn, execution_id, "execution.cancel_requested", category="control", metadata={"reason": reason}, attempt_no=(job or {}).get("attempts"))
        if job and job["status"] in {"queued", "retry"}:
            conn.execute(
                "UPDATE amp.jobs SET status = 'cancelled', lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL, updated_at = now() WHERE id = %s",
                (job["id"],),
            )
            conn.execute(
                "UPDATE amp.executions SET status = 'cancelled', cancel_effective_at = now(), completed_at = now(), updated_at = now() WHERE id = %s",
                (execution_id,),
            )
            append_event(conn, execution_id, "execution.cancelled", category="control", metadata={"reason": reason})
            result = {"found": True, "status": "cancelled", "terminal": True}
        else:
            result = {"found": True, "status": execution["status"], "cancel_requested": True, "terminal": False}
        conn.commit()
        return result


def effective_cancel(job: dict, reason: str = "cancelled") -> bool:
    with connection() as conn:
        execution = conn.execute(
            "SELECT * FROM amp.executions WHERE id = %s FOR UPDATE", (job["execution_id"],)
        ).fetchone()
        if not execution or execution["status"] in TERMINAL_EXECUTIONS:
            conn.commit(); return False
        current = conn.execute(
            "SELECT * FROM amp.jobs WHERE id = %s FOR UPDATE", (job["id"],)
        ).fetchone()
        if not current or current["status"] != "running" or current["lease_token"] != job["lease_token"]:
            conn.commit(); return False
        conn.execute(
            "UPDATE amp.jobs SET status = 'cancelled', lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL, updated_at = now() WHERE id = %s",
            (job["id"],),
        )
        conn.execute(
            "UPDATE amp.executions SET status = 'cancelled', cancel_effective_at = now(), completed_at = now(), updated_at = now() WHERE id = %s",
            (job["execution_id"],),
        )
        append_event(conn, job["execution_id"], "execution.cancelled", category="control", metadata={"reason": reason}, attempt_no=job.get("attempts"))
        conn.commit()
        return True


def register_worker(worker_id: str, boot_id: uuid.UUID, service_version: str, state: str, current_job_id: uuid.UUID | None = None) -> None:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO amp.worker_instances(worker_id, boot_id, service_version, state, current_job_id)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (worker_id) DO UPDATE SET boot_id = EXCLUDED.boot_id,
              service_version = EXCLUDED.service_version, state = EXCLUDED.state,
              current_job_id = EXCLUDED.current_job_id, last_seen_at = now()
            """, (worker_id, boot_id, service_version, state, current_job_id)
        )
        conn.commit()


def heartbeat_worker(worker_id: str, state: str, current_job_id: uuid.UUID | None = None) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE amp.worker_instances SET state = %s, current_job_id = %s, last_seen_at = now() WHERE worker_id = %s",
            (state, current_job_id, worker_id),
        )
        conn.commit()


def transition_success(job: dict, result: str) -> bool:
    with connection() as conn:
        execution = conn.execute("SELECT * FROM amp.executions WHERE id = %s FOR UPDATE", (job["execution_id"],)).fetchone()
        if not execution or execution["status"] in TERMINAL_EXECUTIONS or execution["cancel_requested_at"] is not None:
            conn.commit(); return False
        current = conn.execute("SELECT * FROM amp.jobs WHERE id = %s FOR UPDATE", (job["id"],)).fetchone()
        if not current or current["status"] != "running" or current["lease_token"] != job["lease_token"]:
            conn.commit(); return False
        conn.execute("SELECT id FROM amp.conversations WHERE id = %s FOR UPDATE", (job["conversation_id"],)).fetchone()
        conn.execute("UPDATE amp.jobs SET status = 'succeeded', lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL, updated_at = now() WHERE id = %s", (job["id"],))
        conn.execute("UPDATE amp.executions SET status = 'succeeded', result = %s, completed_at = now(), updated_at = now() WHERE id = %s", (result, job["execution_id"]))
        seq = conn.execute("SELECT COALESCE(MAX(sequence_no), 0) + 1 AS next_sequence FROM amp.messages WHERE conversation_id = %s", (job["conversation_id"],)).fetchone()["next_sequence"]
        conn.execute("INSERT INTO amp.messages(id, conversation_id, execution_id, role, content, sequence_no) VALUES (%s, %s, %s, 'assistant', %s, %s) ON CONFLICT (execution_id) WHERE role = 'assistant' DO NOTHING", (uuid.uuid4(), job["conversation_id"], job["execution_id"], result, seq))
        append_event(conn, job["execution_id"], "execution.succeeded", category="lifecycle", attempt_no=job.get("attempts"), outcome="succeeded")
        external = execution.get("reply_channel")
        if external:
            conn.execute("INSERT INTO amp.outbox_events(id, execution_id, event_type, reply_channel, payload) VALUES (%s, %s, 'execution.succeeded', %s, %s) ON CONFLICT (execution_id, event_type) DO NOTHING", (uuid.uuid4(), job["execution_id"], external, Jsonb({"execution_id": str(job["execution_id"]), "speech": result, "ok": True})))
        conn.execute("UPDATE amp.conversations SET updated_at = now() WHERE id = %s", (job["conversation_id"],))
        conn.commit(); return True


def transition_failure(job: dict, error_code: str, error_message: str, retry_delay: float, retryable: bool = True) -> str:
    with connection() as conn:
        execution = conn.execute("SELECT * FROM amp.executions WHERE id = %s FOR UPDATE", (job["execution_id"],)).fetchone()
        if not execution:
            conn.commit(); return "stale"
        current = conn.execute("SELECT * FROM amp.jobs WHERE id = %s FOR UPDATE", (job["id"],)).fetchone()
        if not current or current["status"] != "running" or current["lease_token"] != job["lease_token"]:
            conn.commit(); return "stale"
        if execution["cancel_requested_at"] is not None:
            conn.execute("UPDATE amp.jobs SET status = 'cancelled', lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL, updated_at = now() WHERE id = %s", (job["id"],))
            conn.execute("UPDATE amp.executions SET status = 'cancelled', cancel_effective_at = now(), completed_at = now(), updated_at = now() WHERE id = %s", (job["execution_id"],))
            append_event(conn, job["execution_id"], "execution.cancelled", category="control", metadata={"reason": "cancel_requested"}, attempt_no=job.get("attempts"))
            conn.commit(); return "cancelled"
        terminal = (not retryable) or current["attempts"] >= current["max_attempts"]
        fingerprint = fingerprint_error("worker", error_code)
        if terminal:
            if error_code in {"deadline_exceeded", "step_limit_exceeded", "tool_call_limit_exceeded", "output_limit_exceeded"}:
                append_event(conn, job["execution_id"], "execution.limit_exceeded", category="control", metadata={"error_code": error_code}, attempt_no=job.get("attempts"), outcome="failed", error_code=error_code, is_retryable=False, error_fingerprint=fingerprint)
            conn.execute("UPDATE amp.jobs SET status = 'dead', lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL, last_error_code = %s, last_error = %s, updated_at = now() WHERE id = %s", (error_code, error_message, job["id"]))
            conn.execute("UPDATE amp.executions SET status = 'failed', error_code = %s, error_message = %s, error_fingerprint = %s, error_retryable = %s, completed_at = now(), updated_at = now() WHERE id = %s", (error_code, error_message, fingerprint, retryable, job["execution_id"]))
            append_event(conn, job["execution_id"], "execution.failed", category="lifecycle", metadata={"error_class": "runtime"}, attempt_no=job.get("attempts"), outcome="failed", error_code=error_code, is_retryable=retryable, error_fingerprint=fingerprint)
            result = "dead"
        else:
            conn.execute("UPDATE amp.jobs SET status = 'retry', available_at = now() + (%s * interval '1 second'), lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL, last_error_code = %s, last_error = %s, updated_at = now() WHERE id = %s", (retry_delay, error_code, error_message, job["id"]))
            conn.execute("UPDATE amp.executions SET status = 'queued', updated_at = now() WHERE id = %s", (job["execution_id"],))
            append_event(conn, job["execution_id"], "job.retry_scheduled", category="control", metadata={"error_code": error_code, "retry_delay": retry_delay}, attempt_no=job.get("attempts"), outcome="retry", error_code=error_code, is_retryable=retryable, error_fingerprint=fingerprint)
            result = "retry"
        conn.commit(); return result
