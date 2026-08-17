import asyncio
import importlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

api_module = importlib.import_module("amp_agent.api.app")
chat_module = importlib.import_module("amp_agent.api.chat")


class EventStreamTests(unittest.TestCase):
    def test_event_stream_emits_events_and_heartbeat_until_terminal(self):
        execution_id = uuid4()
        event = {
            "sequence_no": 4,
            "event_name": "node.started",
            "execution_id": execution_id,
            "metadata": {"node": "router"},
        }

        async def collect():
            with (
                patch.object(api_module, "list_execution_events", side_effect=[[event], []]),
                patch.object(
                    api_module,
                    "get_execution",
                    side_effect=[{"status": "running"}, {"status": "succeeded"}],
                ),
                patch.object(api_module.asyncio, "sleep", new=AsyncMock()),
            ):
                return [
                    chunk
                    async for chunk in api_module._execution_event_stream(execution_id, 0)
                ]

        chunks = asyncio.run(collect())
        self.assertEqual(len(chunks), 2)
        self.assertIn("id: 4", chunks[0])
        self.assertIn("event: node.started", chunks[0])
        payload = json.loads(chunks[0].split("data: ", 1)[1].split("\n", 1)[0])
        self.assertEqual(payload["sequence_no"], 4)
        self.assertEqual(chunks[1], ": heartbeat\n\n")

    def test_event_stream_starts_after_requested_cursor(self):
        execution_id = uuid4()
        with (
            patch.object(api_module, "list_execution_events", return_value=[]) as list_events,
            patch.object(api_module, "get_execution", return_value={"status": "succeeded"}),
        ):
            chunks = asyncio.run(
                anext_collect(api_module._execution_event_stream(execution_id, 12))
            )
        self.assertEqual(chunks, [])
        list_events.assert_called_once_with(execution_id, 12, 100)

    def test_event_stream_accepts_paged_event_repository_response(self):
        execution_id = uuid4()
        event = {"sequence_no": 9, "event_name": "execution.succeeded", "execution_id": execution_id}
        with (
            patch.object(api_module, "list_execution_events", return_value={"items": [event]}),
            patch.object(api_module, "get_execution", return_value={"status": "succeeded"}),
        ):
            chunks = asyncio.run(anext_collect(api_module._execution_event_stream(execution_id, 0)))
        self.assertIn("id: 9", chunks[0])

    def test_interrupt_decisions_are_distinct(self):
        self.assertEqual(chat_module._resume_decision(True), {"type": "approve"})
        self.assertEqual(chat_module._resume_decision(False), {"type": "reject"})
        self.assertEqual(chat_module._resume_decision({"note_key": "x"}), {"type": "edit", "arguments": {"note_key": "x"}})


async def anext_collect(stream):
    return [chunk async for chunk in stream]


if __name__ == "__main__":
    unittest.main()
