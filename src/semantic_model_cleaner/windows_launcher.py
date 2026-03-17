"""Packaged Windows launcher for the local web application."""

from __future__ import annotations

import argparse
import socket
import threading
import time
import webbrowser

from . import webapp


def _pick_available_port(host: str, preferred_port: int) -> int:
    """Use the preferred port when available, otherwise fall back to an open port."""
    for candidate in (preferred_port, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, candidate))
            except OSError:
                continue
            return sock.getsockname()[1]
    raise RuntimeError(f"Could not reserve a local port on host {host!r}")


def _wait_for_server(host: str, port: int, timeout_seconds: float = 15.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            try:
                sock.connect((host, port))
                return True
            except OSError:
                time.sleep(0.1)
    return False


def _open_browser_when_ready(url: str, host: str, port: int) -> None:
    if _wait_for_server(host, port):
        webbrowser.open(url, new=1)


def main() -> None:
    from waitress import serve

    parser = argparse.ArgumentParser(
        description="Semantic Model Cleaner Desktop Launcher"
    )
    parser.add_argument("workspace", nargs="?", default=".",
                        help="Workspace root (default: current directory)")
    parser.add_argument("--models-path", nargs="+",
                        help="Path(s) to search for the single .SemanticModel directory to analyze")
    parser.add_argument("--reports-path", nargs="+",
                        help="Path(s) to search for .Report directories")
    parser.add_argument("--port", type=int, default=5001,
                        help="Preferred port to use (default: 5001)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Host to bind to (default: 127.0.0.1)")
    parser.add_argument("--no-open-browser", action="store_true",
                        help="Start the local server without opening the browser automatically")
    args = parser.parse_args()

    port = _pick_available_port(args.host, args.port)
    webapp.configure_runtime(
        workspace=args.workspace,
        models_path=args.models_path,
        reports_path=args.reports_path,
    )
    webapp.print_startup_banner(args.host, port, debug=False, mode="desktop")

    url = f"http://{args.host}:{port}"
    if not args.no_open_browser:
        threading.Thread(
            target=_open_browser_when_ready,
            args=(url, args.host, port),
            daemon=True,
        ).start()

    serve(webapp.app, host=args.host, port=port, threads=8)


if __name__ == "__main__":
    main()
