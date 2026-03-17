from semantic_model_cleaner import windows_launcher


class _FakeSocket:
    def __init__(self, outcomes):
        self._outcomes = outcomes
        self._bound_port = None

    def setsockopt(self, *_args):
        return None

    def bind(self, address):
        _host, port = address
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        self._bound_port = port or outcome

    def getsockname(self):
        return ("127.0.0.1", self._bound_port)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_pick_available_port_prefers_requested_port(monkeypatch):
    outcomes = [5001]
    monkeypatch.setattr(
        windows_launcher.socket,
        "socket",
        lambda *_args, **_kwargs: _FakeSocket(outcomes),
    )

    port = windows_launcher._pick_available_port("127.0.0.1", 5001)

    assert port == 5001


def test_pick_available_port_falls_back_when_port_is_busy(monkeypatch):
    outcomes = [OSError("busy"), 6200]
    monkeypatch.setattr(
        windows_launcher.socket,
        "socket",
        lambda *_args, **_kwargs: _FakeSocket(outcomes),
    )

    resolved = windows_launcher._pick_available_port("127.0.0.1", 5001)

    assert resolved == 6200
