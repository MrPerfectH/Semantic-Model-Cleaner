import io
import sys

from semantic_model_cleaner import windows_launcher


class _FakeSocket:
    def __init__(self, outcomes):
        self._outcomes = outcomes
        self._bound_port = None
        self.options = []

    def setsockopt(self, *args):
        self.options.append(args)

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


def test_windows_port_probe_requests_exclusive_address_use(monkeypatch):
    probe = _FakeSocket([5001])
    monkeypatch.setattr(windows_launcher.sys, "platform", "win32")
    monkeypatch.setattr(windows_launcher.socket, "SO_EXCLUSIVEADDRUSE", 4242, raising=False)
    monkeypatch.setattr(windows_launcher.socket, "socket", lambda *_args, **_kwargs: probe)

    assert windows_launcher._pick_available_port("127.0.0.1", 5001) == 5001
    assert probe.options == [(windows_launcher.socket.SOL_SOCKET, 4242, 1)]


def test_redirected_cp1252_console_does_not_crash_on_unicode_banner(monkeypatch):
    stdout_bytes = io.BytesIO()
    stderr_bytes = io.BytesIO()
    stdout = io.TextIOWrapper(stdout_bytes, encoding="cp1252", errors="strict")
    stderr = io.TextIOWrapper(stderr_bytes, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    monkeypatch.setitem(
        windows_launcher.webapp._state,
        "workspace",
        r"C:\Semantic Model Cleaner β\Zażółć",
    )
    monkeypatch.setitem(
        windows_launcher.webapp._state,
        "model_search_roots",
        [r"C:\Semantic Model Cleaner β\Zażółć"],
    )
    monkeypatch.setitem(
        windows_launcher.webapp._state,
        "report_search_roots",
        [r"C:\Semantic Model Cleaner β\Zażółć"],
    )

    windows_launcher._configure_console_output()
    windows_launcher.webapp.print_startup_banner(
        "127.0.0.1", 61234, debug=False, mode="desktop"
    )

    output = stdout_bytes.getvalue().decode("cp1252")
    assert stdout.line_buffering is True
    assert stdout.write_through is True
    assert "URL       : http://127.0.0.1:61234" in output
    assert "Mode      : desktop" in output
    assert r"\u2500" in output
    assert r"Za\u017có\u0142\u0107" in output
