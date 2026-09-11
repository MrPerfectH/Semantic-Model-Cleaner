"""Write ownership must remain unambiguous when report display names collide."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from semantic_model_cleaner.webapp import app


NODE = shutil.which('node')
TEMPLATE = Path(__file__).parents[1] / 'src/semantic_model_cleaner/templates/index_v2.html'


def test_inventory_page_exposes_named_selection_and_filter_controls():
    page = app.test_client().get('/?ui=v2').get_data(as_text=True)
    assert 'aria-label="Select all items on this page"' in page
    assert 'aria-label="Select all tables on this page"' in page
    assert 'aria-label="Report filter"' in page
    assert 'aria-label="Page filter"' in page


@pytest.mark.skipif(NODE is None, reason='Node required to execute browser ownership helper')
def test_report_ownership_uses_exact_source_or_unique_name_and_fails_closed():
    source = TEMPLATE.read_text()
    start = source.index('function getReportPathByName(')
    end = source.index('\nfunction summarizeReportPreview', start)
    function = source[start:end]
    script = '''
let chosenReports = [
  {name: 'Executive', path: '/projects/one/Executive.Report'},
  {name: 'Executive', path: '/projects/two/Executive.Report'},
  {name: 'Regional', path: '/projects/Regional.Report'}
];
''' + function + '''
const results = [
  getReportPathByName('Executive'),
  getReportPathByName('Regional'),
  getReportPathByName('Executive', '/projects/two/Executive.Report/definition/reportExtensions.json'),
  getReportPathByName('Regional', '/projects/Regional.Report-OTHER/definition/report.json'),
  getReportPathByName('Missing')
];
chosenReports = [{name: 'Regional', path: '/projects/Regional.Report'}];
results.push(getReportPathByName('Missing'));
chosenReports = [{name: 'Executive', path: 'C:\\\\Models\\\\Executive.Report'}];
results.push(getReportPathByName('Executive', 'c:/models/executive.report/definition/report.json'));
console.log(JSON.stringify(results));
'''
    result = subprocess.run([NODE, '-e', script], check=True, text=True, capture_output=True)
    assert json.loads(result.stdout) == [
        None,
        '/projects/Regional.Report',
        '/projects/two/Executive.Report',
        None,
        None,
        None,
        'C:\\Models\\Executive.Report',
    ]
