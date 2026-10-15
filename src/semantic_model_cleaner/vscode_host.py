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
    # Optional host features; older extensions omit this and keep the in-page scope.
    features = os.environ.pop('SMC_VSCODE_FEATURES', '')
    if not re.fullmatch(r'[a-z,]{0,64}', features):
        raise ValueError('Invalid VS Code host configuration. Launch from the extension.')
    app.config['SMC_WEBVIEW_ANCESTORS'] = ancestors
    app.config['SMC_LOCAL_TOKEN'] = token
    app.config['SMC_VSCODE_HOST_SCOPE'] = 'scope' in features.split(',')


def serve(app):
    from waitress import create_server

    # Bind atomically to an OS-assigned port; there is no free-port/rebind race.
    server = create_server(app, host='127.0.0.1', port=0, threads=4)
    app.config['SMC_WEBVIEW_PORT'] = int(server.effective_port)

    # Watch the parent pipe through a private descriptor and point standard input
    # at the null device. On Windows a blocking read on the inherited stdin pipe
    # stalls every later subprocess launch (git build stamp, git checks) that
    # queries the standard handles, which hung the first page load.
    parent = os.fdopen(os.dup(sys.stdin.fileno()), 'rb', buffering=0)
    null = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, sys.stdin.fileno())
    os.close(null)

    def parent_lifetime():
        # The extension owns this pipe. An extension-host crash closes it too.
        try:
            while parent.read(1):
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
