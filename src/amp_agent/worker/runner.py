from __future__ import annotations

import logging
import signal
import threading
import time
import uuid

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres import PostgresSaver

from ..config.settings import (GRAPH_VERSION, JOB_HEARTBEAT_SECONDS, JOB_LEASE_SECONDS, STATE_VERSION, RUNTIME_MAX_STEPS, AMP_AGENT_VERSION)
from ..agent.graph import build_graph
from ..agent.history import build_history
from ..observability import bind_context, configure_json_logging, configure_telemetry, execution_span, log_event
from ..persistence.repositories import claim_job, complete_job, fail_job, get_execution_input, heartbeat, run_retention
from ..persistence.checkpoints import delete_terminal_threads
from ..persistence.runtime import (ExecutionCancelled, RuntimeControlError, RuntimeLimitExceeded, assert_execution_active, effective_cancel, heartbeat_worker, register_worker)
from ..tools.policy import allowed_tool_names

logger = logging.getLogger("amp-worker")


def _safe_failure_message(exc: Exception, code: str = "worker_error") -> str:
    return f"{code}: falha durante a execução do worker."


class Heartbeat:
    def __init__(self, job: dict):
        self.job = job; self.stop_event = threading.Event(); self.thread = threading.Thread(target=self._run, daemon=True); self.valid = True
    def start(self) -> None: self.thread.start()
    def _run(self) -> None:
        while not self.stop_event.wait(JOB_HEARTBEAT_SECONDS):
            self.valid = heartbeat(self.job["id"], self.job["lease_token"], JOB_LEASE_SECONDS)
            if not self.valid:
                logger.warning("worker.lease_lost", extra={"amp_context": {"execution_id": str(self.job["execution_id"]), "job_id": str(self.job["id"])}}); return
    def stop(self) -> None:
        self.stop_event.set(); self.thread.join(timeout=2)


def _last_content(state: dict) -> str:
    messages = state.get("messages", []) if state else []
    return str(getattr(messages[-1], "content", messages[-1])) if messages else ""


def _stream_graph(graph, input_data, config: dict, execution_id: uuid.UUID):
    """Run the graph through LangGraph's typed v3 stream and persist safe projections."""
    stream = graph.stream_events(
        input_data,
        config=config,
        version="v3",
        durability="sync",
    )
    for event in stream:
        if event.get("type") != "event":
            continue
        method = event.get("method")
        if method not in {"values", "updates", "custom", "interrupts", "debug"}:
            continue
        params = event.get("params") or {}
        namespace = params.get("namespace") or []
        record_event(
            execution_id,
            f"stream.{method}",
            metadata={
                "sequence": event.get("seq"),
                "namespace": list(namespace),
            },
            outcome="observed",
        )
    return stream.output


def run_job(graph, job: dict) -> None:
    input_data = get_execution_input(job["execution_id"])
    if not input_data: raise RuntimeError("Mensagem de entrada não encontrada.")
    execution_id = uuid.UUID(str(job["execution_id"]))
    if job.get("lease_token"):
        assert_execution_active(execution_id, job.get("lease_token"))
    config = {"configurable": {"thread_id": str(input_data.get("checkpoint_thread_id") or job["conversation_id"])}, "recursion_limit": RUNTIME_MAX_STEPS * 2}
    snapshot = graph.get_state(config)
    snapshot_values = (snapshot.values or {}) if snapshot else {}
    snapshot_execution_id = snapshot_values.get("execution_id") if snapshot_values else None
    if snapshot and snapshot.next and str(snapshot_execution_id) != str(execution_id):
        raise RuntimeError("Checkpoint pendente de outra execução nesta conversa.")
    if snapshot and snapshot.next and str(snapshot_execution_id) == str(execution_id):
        result = _stream_graph(graph, None, config, execution_id)
    else:
        history, history_meta = build_history(uuid.UUID(str(job["conversation_id"])), input_data["sequence_no"], input_data.get("history_max_messages") or 20, input_data.get("history_max_estimated_tokens") or 6000)
        if not history or getattr(history[-1], "content", None) != input_data["content"]:
            history.append(HumanMessage(content=input_data["content"]))
        initial = {"messages": history, "profile": "fast", "state_version": STATE_VERSION, "execution_id": str(execution_id), "conversation_id": str(job["conversation_id"]), "input_message_id": str(input_data["input_message_id"]), "graph_version": GRAPH_VERSION, "channel": input_data.get("source") or "chat", "tool_policy": allowed_tool_names(input_data.get("source")), **history_meta}
        result = _stream_graph(graph, initial, config, execution_id)
    if job.get("lease_token"):
        assert_execution_active(execution_id, job.get("lease_token"))
    content = _last_content(result)
    if not content: raise RuntimeError("O grafo terminou sem uma resposta textual.")
    if not complete_job(job, content): raise RuntimeControlError("stale")


def handle_claimed_job(graph, job: dict, worker_id: str, heartbeat_handle: Heartbeat) -> None:
    """Run one leased job with correlation context active for every log."""
    with bind_context(
        execution_id=str(job["execution_id"]),
        thread_id=str(job["conversation_id"]),
        run_id=str(job["execution_id"]),
        assistant_id=(str(job["agent_id"]) if job.get("agent_id") else None),
        job_id=str(job["id"]),
        worker_id=worker_id,
    ):
        try:
            with execution_span(
                str(job["execution_id"]),
                str(job["id"]),
                job.get("attempts"),
            ) as span:
                try:
                    run_job(graph, job)
                    span.set_attribute("amp.outcome", "succeeded")
                except ExecutionCancelled:
                    span.set_attribute("amp.outcome", "cancelled")
                    effective_cancel(job)
                except RuntimeLimitExceeded as exc:
                    span.set_attribute("amp.outcome", "limit_exceeded")
                    fail_job(job, exc.code, _safe_failure_message(exc, exc.code), 0, retryable=False)
                except RuntimeControlError:
                    span.set_attribute("amp.outcome", "stale")
                except Exception as exc:
                    span.set_attribute("amp.outcome", "failed")
                    logger.error(
                        "execution.failed",
                        extra={
                            "amp_context": {
                                "attempt_no": job.get("attempts"),
                                "error_class": type(exc).__name__,
                            }
                        },
                    )
                    delay = min(300.0, 5.0 * (2 ** max(job["attempts"] - 1, 0)))
                    fail_job(job, "worker_error", _safe_failure_message(exc), delay, retryable=True)
        finally:
            heartbeat_handle.stop()
            heartbeat_worker(worker_id, "idle")


def run_worker() -> None:
    worker_id = f"worker-{uuid.uuid4()}"; boot_id = uuid.uuid4(); stop_event = threading.Event(); last_retention = 0.0
    configure_json_logging()
    configure_telemetry("amp-worker")
    register_worker(worker_id, boot_id, AMP_AGENT_VERSION, "starting")
    def stop_handler(signum, frame):
        del signum, frame; stop_event.set()
    signal.signal(signal.SIGTERM, stop_handler); signal.signal(signal.SIGINT, stop_handler)
    from ..config.settings import database_settings
    dsn = database_settings().dsn("langgraph,public")
    with PostgresSaver.from_conn_string(dsn) as checkpointer:
        graph = build_graph(checkpointer)
        while not stop_event.is_set():
            heartbeat_worker(worker_id, "idle")
            if time.monotonic() - last_retention > 3600:
                try:
                    run_retention(); delete_terminal_threads(checkpointer)
                except Exception: logger.exception("retention.failed")
                last_retention = time.monotonic()
            job = claim_job(worker_id, JOB_LEASE_SECONDS)
            if not job:
                stop_event.wait(1); continue
            heartbeat_worker(worker_id, "running", job["id"]); heartbeat_handle = Heartbeat(job); heartbeat_handle.start()
            handle_claimed_job(graph, job, worker_id, heartbeat_handle)
    heartbeat_worker(worker_id, "stopped")

if __name__ == "__main__":
    run_worker()
