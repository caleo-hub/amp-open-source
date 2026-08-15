from . import runner as _runner
from .runner import Heartbeat, run_worker

get_execution_input = _runner.get_execution_input

def run_job(graph, job):
    _runner.get_execution_input = get_execution_input
    return _runner.run_job(graph, job)
