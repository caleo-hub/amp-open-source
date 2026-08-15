import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from amp_agent.repositories import recover_expired_jobs
from amp_agent.worker import run_job


class FakeConn:
    def __init__(self):
        self.calls = []
        self.rows = [{"id": uuid.uuid4(), "execution_id": uuid.uuid4()}]
    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if sql.lstrip().startswith("SELECT id, execution_id"):
            return SimpleNamespace(fetchall=lambda: self.rows)
        return SimpleNamespace(fetchone=lambda: {"id": uuid.uuid4()})


class DurabilityTests(unittest.TestCase):
    def test_expired_lease_is_requeued_and_evented(self):
        conn = FakeConn()
        self.assertEqual(recover_expired_jobs(conn), 1)
        sql = "\n".join(call[0] for call in conn.calls)
        self.assertIn("SET status = 'retry'", sql)
        self.assertIn("SET status = 'queued'", sql)
        self.assertTrue(any("job.lease_expired" in (params or ()) for _, params in conn.calls))

    def test_pending_checkpoint_from_other_execution_is_not_overwritten(self):
        execution_id = uuid.uuid4()
        other_id = uuid.uuid4()
        graph = SimpleNamespace(
            get_state=lambda config: SimpleNamespace(
                values={"execution_id": str(other_id), "messages": []},
                next=("respond",),
            ),
            invoke=lambda *args, **kwargs: self.fail("não deve iniciar novo turno"),
        )
        job = {"execution_id": execution_id, "conversation_id": uuid.uuid4()}
        with patch("amp_agent.worker.get_execution_input", return_value={"content": "oi", "input_message_id": uuid.uuid4()}):
            with self.assertRaisesRegex(RuntimeError, "Checkpoint pendente"):
                run_job(graph, job)


if __name__ == "__main__":
    unittest.main()
