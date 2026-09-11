import json
from pathlib import Path

import pytest

from semantic_model_cleaner import analyzer, webapp


@pytest.mark.parametrize('catalog,expected', [
    ('Retail Analytics', 'Retail Analytics'),
    ('"Retail Analytics"', 'Retail Analytics'),
    ("'Retail Analytics'", 'Retail Analytics'),
    ('"Sales; Europe"', 'Sales; Europe'),
    ('"Sales ""Europe"""', 'Sales "Europe"'),
])
def test_connection_catalog_handles_quoted_values(catalog, expected):
    assert analyzer._connection_catalog('Provider=MSOLAP;Initial Catalog = ' + catalog + ';Mode=ReadOnly') == expected


def test_connection_catalog_does_not_match_inside_another_value():
    assert analyzer._connection_catalog('Other="x;initial catalog=Wrong";Initial Catalog="Right"') == 'Right'
    assert analyzer._connection_catalog('Initial Catalog="Unclosed') == ''


def test_search_recurses_beyond_conventional_reports_and_matches_quoted_model(tmp_path):
    model = tmp_path / 'Models/Sales.SemanticModel'
    model.mkdir(parents=True)
    connected = ['Reports/Top.Report', 'Reports/Region/Deep.Report', 'Division/Reports/Nested.Report']
    hidden = '.worktrees/Other/Reports/Hidden.Report'
    for relative in [*connected, hidden, 'Reports/Unrelated.Report']:
        report = tmp_path / relative
        report.mkdir(parents=True)
        name = 'Other' if relative.endswith('Unrelated.Report') else 'Sales'
        (report / 'definition.pbir').write_text(json.dumps({'datasetReference': {'byConnection': {
            'connectionString': f'Initial Catalog="{name}";Provider=MSOLAP;'}}}))
    client = webapp.app.test_client()
    result = client.post('/api/reports/find-connected', json={'model_path': str(model), 'search_root': str(tmp_path)})
    assert result.status_code == 200
    payload = result.get_json()
    assert payload['scanned_definition_files'] == 4
    assert {Path(r['path']).relative_to(tmp_path).as_posix() for r in payload['reports']} == set(connected)
    assert all(r['status'] == 'connected_by_name' for r in payload['reports'])
    # An explicitly chosen narrow root must not escape into sibling folders.
    narrow = client.post('/api/reports/find-connected', json={'model_path': str(model), 'search_root': str(tmp_path / 'Reports')}).get_json()
    assert len(narrow['reports']) == 2
    assert analyzer.discover_reports([tmp_path / connected[0]]) == [tmp_path / connected[0]]
