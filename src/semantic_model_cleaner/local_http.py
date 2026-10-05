"""Browser request boundary for the single-user, loopback-only HTTP interface."""
import argparse
import ipaddress
import secrets
from urllib.parse import urlsplit

from flask import jsonify, request


TOKEN_HEADER = 'X-SMC-Token'


def loopback_host(value: str) -> str:
    """Both launchers support only local IPv4 binding for this desktop beta."""
    if value not in {'127.0.0.1', 'localhost'}:
        raise argparse.ArgumentTypeError('Use 127.0.0.1 or localhost; remote binding is disabled for this local-only beta.')
    return value


def _origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path or parsed.query or parsed.fragment):
        raise ValueError('Invalid origin')
    port = parsed.port if parsed.port is not None else (443 if parsed.scheme == 'https' else 80)
    return parsed.scheme, parsed.hostname.lower(), port


def install_local_http_boundary(app):
    # No cookies, URL parameters, log messages, or persistent token files.
    app.config['SMC_LOCAL_TOKEN'] = secrets.token_urlsafe(32)
    # Match the IPv4-only launcher contract. Bracketed IPv6 host matching
    # differs between Werkzeug versions and can match unintended IPv6 hosts.
    app.config['TRUSTED_HOSTS'] = ['localhost', '127.0.0.1']

    def reject(message):
        return jsonify(ok=False, code='LOCAL_REQUEST_REJECTED', error=message), 403

    @app.before_request
    def protect_local_request():
        # Trusted-host checking is performed by Flask during request routing.
        # Also refuse remote peers if an embedding WSGI host binds more broadly.
        if request.remote_addr:
            try:
                if not ipaddress.ip_address(request.remote_addr).is_loopback:
                    return reject('This application accepts local connections only.')
            except ValueError:
                return reject('This application accepts local connections only.')
        origin = request.headers.get('Origin')
        if origin is not None:
            try:
                if _origin(origin) != _origin(request.host_url.rstrip('/')):
                    return reject('Cross-origin requests are not allowed.')
            except ValueError:
                return reject('Cross-origin requests are not allowed.')
        site = request.headers.get('Sec-Fetch-Site')
        if site is not None and site not in {'same-origin', 'none'}:
            return reject('Cross-site browser requests are not allowed.')
        if request.headers.get('Sec-Fetch-Dest') in {'iframe', 'frame', 'object', 'embed'}:
            return reject('Embedding this application is not allowed.')
        if not request.path.startswith('/api/'):
            return None
        mode = request.headers.get('Sec-Fetch-Mode')
        destination = request.headers.get('Sec-Fetch-Dest')
        if ((mode is not None and mode not in {'cors', 'same-origin'})
                or (destination is not None and destination != 'empty')):
            return reject('Use the local application interface to access this API.')
        if request.endpoint == 'local_http_session' and request.method == 'GET':
            return None
        supplied = request.headers.get(TOKEN_HEADER, '')
        if not secrets.compare_digest(supplied.encode('utf-8'), app.config['SMC_LOCAL_TOKEN'].encode('utf-8')):
            return reject('Local request token missing or invalid. Reload the application and try again.')
        if request.method not in {'GET', 'HEAD', 'OPTIONS'} and not request.is_json:
            return reject('Local API changes require an application/json request.')
        return None

    @app.get('/api/session', endpoint='local_http_session')
    def session():
        # Same-origin browsers and explicit local HTTP clients can bootstrap.
        # Foreign origins cannot read this response (no CORS, plus checks above).
        return jsonify(token=app.config['SMC_LOCAL_TOKEN'])

    @app.after_request
    def local_response_headers(response):
        response.headers['Content-Security-Policy'] = "frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
        response.headers['Referrer-Policy'] = 'no-referrer'
        if request.path == '/' or request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response
