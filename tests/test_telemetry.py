import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from amp_agent.observability import telemetry


class ExecutionSpanTests(unittest.TestCase):
    def setUp(self):
        self.exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.tracer = provider.get_tracer("test")

    def test_execution_span_contains_only_control_plane_attributes(self):
        with patch.object(telemetry.trace, "get_tracer", return_value=self.tracer):
            with telemetry.execution_span("execution-1", "job-1", 2) as span:
                span.set_attribute("amp.outcome", "succeeded")

        finished = self.exporter.get_finished_spans()
        self.assertEqual(len(finished), 1)
        self.assertEqual(finished[0].name, "amp.execution")
        self.assertEqual(finished[0].attributes["amp.execution_id"], "execution-1")
        self.assertEqual(finished[0].attributes["amp.job_id"], "job-1")
        self.assertEqual(finished[0].attributes["amp.attempt"], 2)
        self.assertNotIn("prompt", finished[0].attributes)

    def test_execution_span_records_exception_and_error_status(self):
        with self.assertRaisesRegex(RuntimeError, "boom"):
            with patch.object(telemetry.trace, "get_tracer", return_value=self.tracer):
                with telemetry.execution_span("execution-2", "job-2"):
                    raise RuntimeError("boom")

        span = self.exporter.get_finished_spans()[0]
        self.assertEqual(span.status.status_code.name, "ERROR")
        exception_types = {
            event.attributes.get("exception.type")
            for event in span.events
            if event.name == "exception"
        }
        self.assertIn("RuntimeError", exception_types)


if __name__ == "__main__":
    unittest.main()
