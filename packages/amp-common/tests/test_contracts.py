from amp_common import RuntimeContext


def test_runtime_context_is_strict() -> None:
    context = RuntimeContext(tenant_id="t1", user_id="u1", thread_id="th1", run_id="r1")
    assert context.run_id == "r1"
