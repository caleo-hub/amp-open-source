from amp_example_agent import graph


def test_graph_invokes() -> None:
    assert graph.invoke({"message": "hello"}) == {"message": "hello"}
