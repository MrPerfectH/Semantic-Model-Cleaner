"""Report usage presentation leaves policy data and analysis evidence intact."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def test_policy_ui_is_retired_but_backend_is_preserved():
    source = ROOT / 'src/semantic_model_cleaner'
    template = (source / 'templates/index_v2.html').read_text(encoding='utf-8')
    navigation = (source / 'static/workspace-navigation.js').read_text(encoding='utf-8')
    assert 'policy-workspace.js' not in template
    assert not (source / 'static/policy-workspace.js').exists()
    assert 'Review policy' not in navigation
    assert 'report-usage.js' in template
    assert (source / 'review_policy.py').exists()
    assert '/api/review-policy/decisions' in (source / 'webapp.py').read_text(encoding='utf-8')


@pytest.mark.skipif(not shutil.which('node'), reason='Node required')
def test_report_usage_projection_and_states():
    result = subprocess.run([shutil.which('node'), str(ROOT / 'tests/js/report-usage.cjs'), str(ROOT)],
                            capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stdout + result.stderr
