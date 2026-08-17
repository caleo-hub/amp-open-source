from __future__ import annotations

import logging
import asyncio
import inspect
import signal
import threading
import time
import uuid

from langchain_core.messages import HumanMessage
from langgraph.types import Command
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres import AsyncPostgresStore

from ..config.settings import (GRAPH_VERSION, JOB_HEARTBEAT_SECONDS, JOB_LEASE_SECONDS, STATE_VERSION, RUNTIME_MAX_OUTPUT_CHARS, RUNTIME_MAX_STEPS, AMP_AGENT_VERSION)
from ..agent.graph import build_graph
from ..agent.history import build_history
from ..observability import bind_context, configure_json_logging, configure_telemetry, execution_span, log_event
from ..persistence.repositories import claim_job, complete_job, fail_job, get_execution_input, heartbeat, run_retention
from ..persistence.checkpoints import delete_terminal_threads_async
from ..persistence.chat import pending_approval_decision
from ..persistence.runtime import (ExecutionCancelled, RuntimeControlError, RuntimeLimitExceeded, assert_execution_active, effective_cancel, heartbeat_worker, record_event, register_worker)
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


async def _stream_graph(graph, input_data, config: dict, execution_id: uuid.UUID):
    """Run the graph through LangGraph's native async v3 stream."""
    stream = graph.astream_events(
        input_data,
        config=config,
        version="v3",
        durability="sync",
    )
    # LangGraph v3 returns the async run handle through a coroutine.  Await
    # it before subscribing to the protocol events; iterating the coroutine
    # directly leaves the Pregel stream un-awaited and loses the run output.
    if inspect.isawaitable(stream):
        stream = await stream
    async for event in stream:
        if event.get("type") != "event":
            continue
        method = event.get("method")
        if method not in {"values", "updates", "custom", "interrupts", "debug", "messages", "messages-tuple", "tasks", "checkpoints", "events", "subgraphs"}:
            continue
        params = event.get("params") or {}
        namespace = params.get("namespace") or []
        metadata = {"sequence": event.get("seq"), "namespace": list(namespace)}
        if event.get("data") is not None:
            metadata["data"] = event.get("data")
        if params and set(params) != {"namespace"}:
            metadata["params"] = params
        record_event(execution_id, f"stream.{method}", metadata=metadata, outcome="observed")
    output = stream.output()
    if inspect.isawaitable(output):
        output = await output
    return output


async def run_job(graph, job: dict) -> None:
    input_data = get_execution_input(job["execution_id"])
    if not input_data: raise RuntimeError("Mensagem de entrada não encontrada.")
    execution_id = uuid.UUID(str(job["execution_id"]))
    if job.get("lease_token"):
        assert_execution_active(execution_id, job.get("lease_token"))
    config = {"configurable": {"thread_id": str(input_data.get("checkpoint_thread_id") or job["conversation_id"])}, "recursion_limit": RUNTIME_MAX_STEPS * 2}
    snapshot = await graph.aget_state(config)
    snapshot_values = (snapshot.values or {}) if snapshot else {}
    snapshot_execution_id = snapshot_values.get("execution_id") if snapshot_values else None
    if snapshot and snapshot.next and str(snapshot_execution_id) != str(execution_id):
        raise RuntimeError("Checkpoint pendente de outra execução nesta conversa.")
    if snapshot and snapshot.next and str(snapshot_execution_id) == str(execution_id):
        approval = pending_approval_decision(execution_id)
        result = await _stream_graph(graph, Command(resume=(approval or {}).get("decision")), config, execution_id)
    elif snapshot and snapshot_values.get("messages"):
        # The checkpoint is the canonical transcript for subsequent turns.
        # amp.messages remains a compatibility projection for legacy adapters.
        initial = {
            "messages": [HumanMessage(content=input_data["content"])],
            "execution_id": str(execution_id),
            "conversation_id": str(job["conversation_id"]),
            "workspace_id": str(input_data["workspace_id"]),
            "input_message_id": str(input_data["input_message_id"]),
            "graph_version": GRAPH_VERSION,
            "state_version": STATE_VERSION,
            "profile": "fast",
            "channel": input_data.get("source") or "chat",
            "tool_policy": allowed_tool_names(input_data.get("source")),
        }
        result = await _stream_graph(graph, initial, config, execution_id)
    else:
        history, history_meta = build_history(uuid.UUID(str(job["conversation_id"])), input_data["sequence_no"], input_data.get("history_max_messages") or 20, input_data.get("history_max_estimated_tokens") or 6000)
        if not history or getattr(history[-1], "content", None) != input_data["content"]:
            history.append(HumanMessage(content=input_data["content"]))
        initial = {"messages": history, "profile": "fast", "state_version": STATE_VERSION, "execution_id": str(execution_id), "conversation_id": str(job["conversation_id"]), "input_message_id": str(input_data["input_message_id"]), "graph_version": GRAPH_VERSION, "channel": input_data.get("source") or "chat", "tool_policy": allowed_tool_names(input_data.get("source")), **history_meta}
        result = await _stream_graph(graph, initial, config, execution_id)
    if job.get("lease_token"):
        assert_execution_active(execution_id, job.get("lease_token"))
    snapshot = await graph.aget_state(config)
    if snapshot and snapshot.next:
        from ..persistence.runtime import mark_waiting_approval
        mark_waiting_approval(job)
        return
    content = _last_content(result)
    if not content: raise RuntimeError("O grafo terminou sem uma resposta textual.")
    if len(content) > RUNTIME_MAX_OUTPUT_CHARS:
        raise RuntimeLimitExceeded("output_limit_exceeded")
    if not complete_job(job, content): raise RuntimeControlError("stale")


async def handle_claimed_job(graph, job: dict, worker_id: str, heartbeat_handle: Heartbeat) -> None:
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
                conversation_id=str(job["conversation_id"]),
            ) as span:
                try:
                    await run_job(graph, job)
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


async def run_worker() -> None:
    worker_id = f"worker-{uuid.uuid4()}"; boot_id = uuid.uuid4(); stop_event = threading.Event(); last_retention = 0.0
    configure_json_logging()
    configure_telemetry("amp-worker")
    register_worker(worker_id, boot_id, AMP_AGENT_VERSION, "starting")
    def stop_handler(signum, frame):
        del signum, frame; stop_event.set()
    signal.signal(signal.SIGTERM, stop_handler); signal.signal(signal.SIGINT, stop_handler)
    from ..config.settings import database_settings
    dsn = database_settings().dsn("langgraph,public")
    async with AsyncPostgresSaver.from_conn_string(dsn) as checkpointer, AsyncPostgresStore.from_conn_string(dsn) as store:
        await checkpointer.setup()
        await store.setup()
        graph = build_graph(checkpointer, store)
        while not stop_event.is_set():
            heartbeat_worker(worker_id, "idle")
            if time.monotonic() - last_retention > 3600:
                try:
                    run_retention(); await delete_terminal_threads_async(checkpointer)
                except Exception: logger.exception("retention.failed")
                last_retention = time.monotonic()
            job = claim_job(worker_id, JOB_LEASE_SECONDS)
            if not job:
                await asyncio.sleep(1); continue
            heartbeat_worker(worker_id, "running", job["id"]); heartbeat_handle = Heartbeat(job); heartbeat_handle.start()
            await handle_claimed_job(graph, job, worker_id, heartbeat_handle)
    heartbeat_worker(worker_id, "stopped")

if __name__ == "__main__":
    asyncio.run(run_worker())
