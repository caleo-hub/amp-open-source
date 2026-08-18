import importlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

chat = importlib.import_module("amp_agent.persistence.chat")
runner = importlib.import_module("amp_agent.worker.runner")
api_chat = importlib.import_module("amp_agent.api.chat")


class ChatStreamProtocolTests(unittest.TestCase):
    def test_message_tuple_is_unwrapped_without_losing_delta(self):
        method, params, key = chat.normalize_protocol_event({
            "method": "messages",
            "seq": 7,
            "params": {
                "namespace": [],
                "data": [{"event": "content-block-delta", "delta": {"type": "text-delta", "text": "Olá"}}, {"langgraph_node": "agent"}],
            },
        })
        self.assertEqual(method, "messages")
        self.assertEqual(key, "native:7")
        self.assertEqual(params["data"]["delta"]["text"], "Olá")
        self.assertEqual(params["metadata"]["langgraph_node"], "agent")

    def test_interrupt_is_projected_to_protocol_input_request(self):
        method, params, _ = chat.normalize_protocol_event({
            "method": "interrupts",
            "params": {"data": [{"id": "approval-1", "value": {"summary": "Salvar nota"}}]},
        })
        self.assertEqual(method, "input.requested")
        self.assertEqual(params["data"]["interrupt_id"], "approval-1")
        self.assertEqual(params["data"]["payload"]["summary"], "Salvar nota")

    def test_stringified_interrupt_in_values_is_decoded(self):
        method, params, _ = chat.normalize_protocol_event({
            "method": "values",
            "params": {"data": {"interrupts": ["Interrupt(value={'summary': 'Salvar nota'}, id='approval-2')"]}},
        })
        self.assertEqual(method, "values")
        self.assertEqual(params["data"]["interrupts"][0]["id"], "approval-2")
        self.assertEqual(params["data"]["interrupts"][0]["value"]["summary"], "Salvar nota")

    def test_last_content_reads_structured_text_blocks(self):
        class Message:
            content = [{"type": "text", "text": "Resposta "}, {"type": "text", "text": "final"}]
        self.assertEqual(runner._last_content({"messages": [Message()]}), "Resposta final")

    def test_last_content_ignores_non_text_structured_blocks(self):
        class Message:
            content = [{"type": "tool_call", "name": "salvar_nota_local"}]
        self.assertEqual(runner._last_content({"messages": [Message()]}), "")

    def test_ag_ui_projection_keeps_text_deltas_and_client_run_identity(self):
        from uuid import uuid4
        thread_id, execution_id = uuid4(), uuid4()
        events = api_chat._agui_event(
            {"seq": 9, "run_id": execution_id, "method": "messages", "params": {"data": {"event": "content-block-delta", "id": "assistant-1", "delta": {"text": "Olá"}}}},
            thread_id=thread_id,
            client_run_id="copilot-run",
        )
        self.assertEqual(events, [{"type": "TEXT_MESSAGE_CONTENT", "messageId": "assistant-1", "delta": "Olá"}])
        lifecycle = api_chat._agui_event(
            {"seq": 10, "run_id": execution_id, "method": "lifecycle", "params": {"data": {"event": "queued"}}},
            thread_id=thread_id,
            client_run_id="copilot-run",
        )
        self.assertEqual(lifecycle, [])

    def test_ag_ui_error_always_has_a_string_message(self):
        from uuid import uuid4
        event = api_chat._agui_event(
            {"seq": 11, "run_id": uuid4(), "method": "lifecycle", "params": {"data": {"event": "failed"}}},
            thread_id=uuid4(),
            client_run_id="failed-run",
        )[0]
        self.assertEqual(event["type"], "RUN_ERROR")
        self.assertIsInstance(event["message"], str)

    def test_ag_ui_interrupt_is_finished_with_resumable_outcome(self):
        from uuid import uuid4
        event = api_chat._agui_event(
            {"seq": 12, "run_id": uuid4(), "method": "lifecycle", "params": {"data": {"event": "interrupted"}}},
            thread_id=uuid4(),
            client_run_id="paused-run",
            pending_interrupt={
                "interrupt_id": "approval-1",
                "tool_call_id": "tool-1",
                "payload": {"summary": "Salvar nota", "options": ["approve", "reject"]},
            },
        )[0]
        self.assertEqual(event["type"], "RUN_FINISHED")
        self.assertEqual(event["outcome"]["type"], "interrupt")
        self.assertEqual(event["outcome"]["interrupts"][0]["id"], "approval-1")
        self.assertEqual(event["outcome"]["interrupts"][0]["toolCallId"], "tool-1")

    def test_ag_ui_resume_decision_maps_approval_shapes(self):
        self.assertEqual(
            api_chat._agui_resume_decision({"interruptId": "i-1", "status": "resolved", "payload": {"approved": True}}),
            {"type": "approve", "tool_call_id": "i-1"},
        )
        self.assertEqual(
            api_chat._agui_resume_decision({"interrupt_id": "i-1", "payload": {"editedArgs": {"content": "editado"}}}),
            {"type": "edit", "arguments": {"content": "editado"}, "tool_call_id": "i-1"},
        )


if __name__ == "__main__":
    unittest.main()
