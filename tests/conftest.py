from pathlib import Path
import sys

import pytest


SRC_DIR = Path(__file__).resolve().parents[1] / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@pytest.fixture(autouse=True)
def authenticated_domain_api_clients(monkeypatch):
    """Existing domain tests represent a legitimate, bootstrapped UI client.

    Boundary tests use FlaskClient(app) directly to test unauthenticated input.
    This fixture adds credentials, not a production security bypass.
    """
    from flask.testing import FlaskClient
    from werkzeug.datastructures import Headers
    from semantic_model_cleaner import webapp

    class LocalClient(FlaskClient):
        def open(self, *args, **kwargs):
            headers = Headers(kwargs.get('headers'))
            if 'X-SMC-Token' not in headers:
                headers['X-SMC-Token'] = webapp.app.config['SMC_LOCAL_TOKEN']
            if (kwargs.get('method', 'GET').upper() not in {'GET', 'HEAD', 'OPTIONS'}
                    and 'Content-Type' not in headers
                    and not any(key in kwargs for key in ('content_type', 'json', 'data'))):
                headers['Content-Type'] = 'application/json'
            kwargs['headers'] = headers
            return super().open(*args, **kwargs)

    monkeypatch.setattr(webapp.app, 'test_client_class', LocalClient)
