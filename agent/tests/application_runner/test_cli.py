import json

from application_runner import cli


class _TransientFailureRunner:
    def __init__(self):
        self.calls = 0

    def run_next(self, worker_id, lease_minutes):
        self.calls += 1
        if self.calls == 1:
            raise ConnectionError("temporary TLS disconnect")
        raise KeyboardInterrupt


def test_watch_queue_retries_transient_failure(monkeypatch, capsys):
    sleeps = []
    monkeypatch.setattr(cli.time, "sleep", sleeps.append)
    runner = _TransientFailureRunner()

    result = cli._watch_queue(
        runner,
        worker_id="test-worker",
        lease_minutes=30,
        poll_seconds=10,
    )

    output = capsys.readouterr()
    retry = json.loads(output.err.strip())
    assert result == 0
    assert runner.calls == 2
    assert sleeps == [10]
    assert retry["status"] == "retrying"
    assert retry["error_type"] == "ConnectionError"
    assert retry["retry_seconds"] == 10
