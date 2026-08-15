import logging
import signal
import threading
import time
import uuid

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres import PostgresSaver

from .config import (
    GRAPH_VERSION,
    JOB_HEARTBEAT_SECONDS,
    JOB_LEASE_SECONDS,
    STATE_VERSION,
)
from .graph import build_graph
from .repositories import (
    claim_job,
    complete_job,
    fail_job,
    get_execution_input,
    heartbeat,
    run_retention,
)


logger = logging.getLogger("amp-worker")


def _safe_failure_message(exc: Exception) -> str:
    """Return a diagnostic that cannot include credentials or prompt content."""
    return f"{type(exc).__name__}: falha durante a execução do worker."


class Heartbeat:
    def __init__(self, job: dict):
        self.job = job
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.valid = True

    def start(self) -> None:
        self.thread.start()

    def _run(self) -> None:
        while not self.stop_event.wait(JOB_HEARTBEAT_SECONDS):
            self.valid = heartbeat(
                self.job["id"],
                self.job["lease_token"],
                JOB_LEASE_SECONDS,
            )
            if not self.valid:
                logger.warning("Lease perdido para job %s", self.job["id"])
                return

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=2)


def _last_content(state: dict) -> str:
    messages = state.get("messages", []) if state else []
    if not messages:
        return ""
    return str(getattr(messages[-1], "content", messages[-1]))


def run_job(graph, job: dict) -> None:
    input_data = get_execution_input(job["execution_id"])
    if not input_data:
        raise RuntimeError("Mensagem de entrada não encontrada.")

    config = {
        "configurable": {
            "thread_id": str(job["conversation_id"]),
        }
    }
    snapshot = graph.get_state(config)
    snapshot_execution_id = None
    snapshot_values = (snapshot.values or {}) if snapshot else {}
    if snapshot_values:
        snapshot_execution_id = snapshot_values.get("execution_id")
    current_execution_id = str(job["execution_id"])
    if snapshot and snapshot.next and snapshot_execution_id != current_execution_id:
        raise RuntimeError("Checkpoint pendente de outra execução nesta conversa.")
    if snapshot and snapshot.next and snapshot_execution_id == current_execution_id:
        result = graph.invoke(None, config=config, durability="sync")
    elif snapshot and snapshot_values.get("messages") and snapshot_execution_id == current_execution_id:
        result = snapshot.values
    else:
        result = graph.invoke(
            {
                "messages": [HumanMessage(content=input_data["content"])],
                "profile": "fast",
                "state_version": STATE_VERSION,
                "execution_id": str(job["execution_id"]),
                "conversation_id": str(job["conversation_id"]),
                "input_message_id": str(input_data["input_message_id"]),
                "graph_version": GRAPH_VERSION,
            },
            config=config,
            durability="sync",
        )

    if not _last_content(result):
        raise RuntimeError("O grafo terminou sem uma resposta textual.")
    if not complete_job(job, _last_content(result)):
        raise RuntimeError("Lease inválido ao finalizar o job.")


def run_worker() -> None:
    worker_id = f"worker-{uuid.uuid4()}"
    stop_event = threading.Event()
    last_retention = 0.0

    def stop_handler(signum, frame):
        del signum, frame
        stop_event.set()

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    from .config import database_settings
    dsn = database_settings().dsn("langgraph,public")
    with PostgresSaver.from_conn_string(dsn) as checkpointer:
        graph = build_graph(checkpointer)
        while not stop_event.is_set():
            if time.monotonic() - last_retention > 3600:
                try:
                    run_retention()
                except Exception:
                    logger.exception("Falha na retenção periódica")
                last_retention = time.monotonic()

            job = claim_job(worker_id, JOB_LEASE_SECONDS)
            if not job:
                stop_event.wait(1)
                continue

            heartbeat_handle = Heartbeat(job)
            heartbeat_handle.start()
            try:
                run_job(graph, job)
            except Exception as exc:
                # Do not log exception text: database/HTTP errors can contain
                # DSNs, passwords, prompts, or provider responses.
                logger.error("Falha no job %s (%s)", job["id"], type(exc).__name__)
                delay = min(300.0, 5.0 * (2 ** max(job["attempts"] - 1, 0)))
                fail_job(job, "worker_error", _safe_failure_message(exc), delay)
            finally:
                heartbeat_handle.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_worker()
