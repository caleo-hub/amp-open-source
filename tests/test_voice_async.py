import sys
import time
import importlib
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from fastapi.testclient import TestClient

api_module = importlib.import_module("amp_agent.api.app")
from amp_agent.tools.policy import CHANNEL_TOOL_POLICY


class VoiceAsyncTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api_module.app)
        self.conversation_id = uuid4()
        self.execution_id = uuid4()

    def test_voice_submits_without_waiting(self):
        execution = {"id": self.execution_id, "conversation_id": self.conversation_id, "request_id": "alexa-async-001", "status": "queued"}
        with patch.object(api_module, "VOICE_API_KEY", "secret"), patch.object(api_module, "existing_execution_or_none", return_value=None), patch.object(api_module, "create_conversation", return_value={"id": self.conversation_id}), patch.object(api_module, "enqueue_message", return_value={"execution": execution}), patch.object(api_module, "wait_for_execution") as wait:
            response = self.client.post("/voice", headers={"X-AMP-Voice-Key": "secret"}, json={"text": "pesquise notícias de inteligência artificial", "timestamp": int(time.time()), "request_id": "alexa-async-001"})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "accepted")
        self.assertEqual(response.json()["execution_id"], str(self.execution_id))
        wait.assert_not_called()

    def test_voice_status_mapping(self):
        for persisted, expected in (("queued", "processing"), ("running", "processing"), ("succeeded", "completed"), ("failed", "failed"), ("cancelled", "failed")):
            row = {"id": self.execution_id, "status": persisted, "result": "resultado"}
            with patch.object(api_module, "VOICE_API_KEY", "secret"), patch.object(api_module, "get_execution", return_value=row):
                response = self.client.get(f"/voice/executions/{self.execution_id}", headers={"X-AMP-Voice-Key": "secret"})
            self.assertEqual(response.json()["status"], expected)

    def test_voice_tool_policy_is_explicit(self):
        self.assertEqual(CHANNEL_TOOL_POLICY["voice"], {"system_status", "pesquisar_web"})


if __name__ == "__main__":
    unittest.main()
