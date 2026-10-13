# Local HTTP access

Semantic Model Cleaner is a single-user application on the same computer as the
Power BI Project. The Windows launcher and Python web launcher accept only
`--host 127.0.0.1` (the default) or `--host localhost`. Remote binding, reverse
proxies, tunneling, and multi-user hosting are unsupported for this beta. The
request boundary also rejects non-loopback peers when the Flask application is
embedded in another WSGI server. Forwarded headers do not grant access.

## Browser boundary

Every application launch generates a random token in process memory. Each layout
receives it in its HTML and sends it as `X-SMC-Token` on every API request,
including reads, discovery, cancellation, and downloads. Downloads use
authenticated fetch followed by a browser blob download. Tokens never go in
URLs, cookies, log messages, or persistent files. A restarted server requires
reloading an open tab; stale tokens fail closed with HTTP 403.

Before any route executes:

- Flask validates Host against `localhost` and `127.0.0.1`. Untrusted
  hosts cannot bootstrap a token or reach filesystem APIs. The supported
  launchers bind IPv4; IPv6 Host values are rejected.
- If Origin is present, its scheme, hostname, and port must match the request
  origin exactly. `null`, malformed origins, other loopback ports, and a different
  loopback hostname are rejected.
- If browser Fetch Metadata is present, only same-origin or user-initiated
  `none` sites are accepted. API requests must have fetch mode `cors` or
  `same-origin` and destination `empty`. Cross-site, same-site-but-other-origin,
  navigation, no-CORS, and embedded requests cannot access the APIs or bootstrap.
- All `/api/` routes require the launch token, except `GET /api/session`, the
  same-origin bootstrap. Mutating methods additionally require JSON content
  type. Form requests and missing/invalid tokens fail before route side effects.

There is no permissive CORS configuration. Foreign preflights are rejected.
Responses prohibit framing with CSP `frame-ancestors 'none'` and
`X-Frame-Options: DENY`, prohibit cross-origin resource inclusion, and suppress
referrers. HTML and API responses are marked `Cache-Control: no-store`.

The boundary assumes a browser enforcing the same-origin policy and custom
request-header restrictions. Older browsers without Fetch Metadata still cannot
read the token cross-origin or send it in a simple form request. This is browser
request protection, not authentication between users or against a malicious
local process, browser extension, or script already executing within the app's
own origin. The application must remain bound to loopback.

## Local automation

Prefer `smc check`, `smc plan`, `smc apply`, `smc verify`, and `smc restore` for
file-based automation. They run independently of the web app and do not require
a token.

A trusted local HTTP client can explicitly bootstrap:

```python
import json
from urllib.request import ProxyHandler, Request, build_opener

base = "http://127.0.0.1:5001"
http = build_opener(ProxyHandler({}))
with http.open(base + "/api/session") as response:
    token = json.load(response)["token"]

request = Request(
    base + "/api/discover",
    data=b"{}",
    headers={"Content-Type": "application/json", "X-SMC-Token": token},
)
with http.open(request) as response:
    discovery = json.load(response)
```

Do not log or put the token into command arguments or URLs. Keep it in client
memory, use the same origin throughout, and bootstrap again after a server
restart. The bootstrap is available to local scripts without an Origin header;
browser requests with an Origin header must satisfy the exact-origin check.
Old uncredentialed HTTP scripts and direct API download navigation now receive
403. API access through the supported UI and updated package smoke clients
follows the protocol automatically.

## Protected state changes

The boundary applies centrally to all API routes, including routes added later.
The audited routes include:

- Discovery (`GET` and `POST /api/discover`) and connected-report searches.
- Demo preparation, synchronous analysis, comparison, analysis-job creation,
  and `DELETE /api/analysis-jobs/<id>` cancellation.
- Saved-plan creation and all operations under `/api/plans/<id>/<operation>`:
  apply, restore, verify, and interrupted-lock recovery.
- Review findings, review-policy updates, review-decision addition/removal, and
  naming previews.
- Legacy action, DAX, migration, move, rename, stale cleanup, report-issue, and
  reference-repair routes. Their existing reviewed-plan restrictions remain.

Tests use disposable data for saved-plan rejection and authenticated round
trips. Domain API tests send real credentials via their test client; boundary
tests use the raw Flask client to verify absent and hostile credentials. The
Windows and wheel smoke clients bootstrap through the actual HTTP protocol.

## Opt-in desktop VS Code embedding

The extension launch protocol is separate from normal browser launches. Only
`--vscode --host 127.0.0.1 --port 0`, with a valid in-memory launch configuration,
enables it. An OS-assigned port avoids a free-port/rebind race. The parent owns
stdin; EOF stops the server if the extension host disappears.

The extension supplies a fresh 256-bit token and the exact measured desktop
webview ancestor origins through environment variables (removed after reading).
Only concrete `https://<id>.vscode-cdn.net`, `vscode-webview://<id>` and the desktop
shell `vscode-file://vscode-app` sources are accepted, never wildcards, arbitrary
websites, scheme-only sources or user-provided CSP text. The server's HTML CSP
lists these ancestors and omits X-Frame-Options only for successful root HTML.
Every ancestor must satisfy that CSP. Cross-site iframe navigation is allowed
only for `GET /`, with Fetch Mode `navigate` and Destination `iframe`; a supplied
Origin must be one of the exact ancestors or the app origin. HTML navigation
without an Origin still relies on the browser's enforced frame-ancestors policy.

All API and resource requests retain the ordinary Origin and Fetch Metadata
checks. There is no CORS grant. Host must additionally match the chosen loopback
port. `/api/vscode/ready` requires the token and returns protocol version 1 plus
its SHA-256 instance fingerprint, so the extension cannot accidentally reuse a
foreign server. The readiness route is unavailable in normal host mode.

The preview supports local desktop VS Code only; remote/browser hosts are
rejected before startup. See the [extension README](../vscode-extension/README.md)
for installation, lifetime, dialog and test details. Defaults remain unchanged
unless the explicit host flag is used; merely setting environment variables
cannot enable embedding.
