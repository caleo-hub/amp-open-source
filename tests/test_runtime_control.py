import base64
import json
import logging
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from amp_agent.observability.sanitize import fingerprint_error, sanitize_metadata
from amp_agent.observability.context import bind_context, current_context
from amp_agent.observability.logging import JsonFormatter
from amp_agent.config.settings import RUNTIME_MAX_SECONDS, RUNTIME_MAX_STEPS, RUNTIME_MAX_TOOL_CALLS


class RuntimeControlTests(unittest.TestCase):
    def test_sanitizer_removes_secrets_and_bounds_values(self):
        payload = sanitize_metadata({"password": "super-secret", "nested": {"authorization": "Bearer abc"}, "url": "https://user:pass@example.test", "text": "x" * 1000})
        self.assertEqual(payload["password"], "[REDACTED]")
        self.assertEqual(payload["nested"]["authorization"], "[REDACTED]")
        self.assertIn("[REDACTED]", payload["url"])
        self.assertLessEqual(len(payload["text"]), 256)

    def test_error_fingerprint_does_not_depend_on_exception_text(self):
        first = fingerprint_error("model", "model_timeout", TimeoutError("secret one"))
        second = fingerprint_error("model", "model_timeout", TimeoutError("secret two"))
        self.assertEqual(first, second)

    def test_default_runtime_policy_is_bounded(self):
        self.assertEqual((RUNTIME_MAX_SECONDS, RUNTIME_MAX_STEPS, RUNTIME_MAX_TOOL_CALLS), (120, 12, 4))

    def test_cursor_payload_is_versioned_and_url_safe(self):
        raw = {"v": 1, "workspace_id": "local", "status": None, "created_at": "2026-01-01T00:00:00+00:00", "id": "abc"}
        cursor = base64.urlsafe_b64encode(json.dumps(raw, separators=(",", ":")).encode()).decode().rstrip("=")
        self.assertNotIn("=", cursor)
        restored = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        self.assertEqual(restored["v"], 1)

    def test_correlation_context_is_added_to_json_logs(self):
        record = logging.LogRecord(
            "amp-test", logging.INFO, __file__, 1, "event.test", (), None
        )
        record.amp_context = {"execution_id": "execution-1"}

        with bind_context(request_id="request-1", thread_id="thread-1"):
            payload = json.loads(JsonFormatter().format(record))

        self.assertEqual(payload["request_id"], "request-1")
        self.assertEqual(payload["thread_id"], "thread-1")
        self.assertEqual(payload["execution_id"], "execution-1")

    def test_correlation_context_does_not_leak(self):
        self.assertEqual(current_context(), {})
        with bind_context(request_id="outer"):
            self.assertEqual(current_context()["request_id"], "outer")
            with bind_context(request_id="inner", run_id="run-1"):
                self.assertEqual(current_context()["request_id"], "inner")
                self.assertEqual(current_context()["run_id"], "run-1")
            self.assertEqual(current_context(), {"request_id": "outer"})
        self.assertEqual(current_context(), {})


if __name__ == "__main__":
    unittest.main()
