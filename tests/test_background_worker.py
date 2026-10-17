from scripts import background_worker as worker


def test_child_exit_stops_peer_and_fails_container(monkeypatch):
    class Child:
        def __init__(self, code):
            self.code = code
            self.terminated = False

        def poll(self):
            return self.code

        def terminate(self):
            self.terminated = True
            self.code = -15

        def wait(self, timeout):
            return self.code

    children = [Child(1), Child(None)]
    commands = []

    def spawn(command):
        commands.append(command)
        return children[len(commands) - 1]

    monkeypatch.setattr(worker.subprocess, 'Popen', spawn)
    monkeypatch.setattr(worker.signal, 'signal', lambda *args: None)
    assert worker.main() == 1
    assert children[1].terminated
    assert [command[-1] for command in commands] == ['scripts.workflow_worker', 'scripts.integration_worker']
