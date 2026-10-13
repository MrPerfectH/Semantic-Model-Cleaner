"""Opt-in desktop VS Code host protocol. Never used by ordinary web launches."""
import json
import os
import re
import sys
import threading


def validate_ancestors(values):
    """Accept concrete desktop webview origins, never a CSP source expression."""
    if not isinstance(values, list) or not 1 <= len(values) <= 4:
        raise ValueError('Expected 1 to 4 exact VS Code ancestor origins.')
    patterns = (
        r'https://[a-z0-9-]+\.vscode-cdn\.net',
        r'vscode-webview://[a-z0-9-]+',
        r'vscode-file://vscode-app',
    )
    if any(not isinstance(value, str) or not any(re.fullmatch(pattern, value)
               for pattern in patterns) for value in values):
        raise ValueError('Only exact desktop VS Code ancestor origins are allowed.')
    if not any(value != 'vscode-file://vscode-app' for value in values):
        raise ValueError('A concrete webview origin is required.')
    return tuple(dict.fromkeys(values))


def configure_host(app):
    """Secrets travel through the owned child's environment, never argv or URLs."""
    try:
        ancestors = validate_ancestors(json.loads(os.environ.pop('SMC_VSCODE_ANCESTORS', 'null')))
        token = os.environ.pop('SMC_VSCODE_TOKEN', '')
        if not re.fullmatch(r'[0-9a-f]{64}', token):
            raise ValueError('A fresh 256-bit VS Code launch token is required.')
    except (ValueError, TypeError) as error:
        raise ValueError('Invalid VS Code host configuration. Launch from the extension.') from error
    app.config['SMC_WEBVIEW_ANCESTORS'] = ancestors
    app.config['SMC_LOCAL_TOKEN'] = token


def serve(app):
    from waitress import create_server

    # Bind atomically to an OS-assigned port; there is no free-port/rebind race.
    server = create_server(app, host='127.0.0.1', port=0, threads=4)
    app.config['SMC_WEBVIEW_PORT'] = int(server.effective_port)

    def parent_lifetime():
        # The extension owns this pipe. An extension-host crash closes it too.
        try:
            while sys.stdin.buffer.read(1):
                pass
        finally:
            os._exit(0)

    threading.Thread(target=parent_lifetime, daemon=True, name='vscode-parent').start()
    print('SMC_VSCODE_READY ' + json.dumps({'port': int(server.effective_port), 'protocol': 1}),
          flush=True)
    try:
        server.run()
    finally:
        server.close()
