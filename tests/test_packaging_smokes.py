"""Packaging probes must exercise, and reject failures in, transitive schemas."""
import importlib.util
import hashlib
import json
from pathlib import Path
import socket

import pytest

from semantic_model_cleaner import metadata_validation


spec = importlib.util.spec_from_file_location(
    'windows_packaging_smoke', Path(__file__).parents[1] / 'packaging/windows/smoke.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def test_downloaded_windows_archive_checksum_is_enforced(tmp_path):
    archive = tmp_path / 'semantic-model-cleaner-windows-x64-0.4.0b1.zip'
    archive.write_bytes(b'packaged beta')
    expected = hashlib.sha256(archive.read_bytes()).hexdigest()
    sidecar = tmp_path / (archive.name + '.sha256')
    sidecar.write_text(f'{expected}  {archive.name}\n', encoding='ascii')
    assert smoke._verify_checksum(archive, sidecar) == expected
    archive.write_bytes(b'tampered')
    with pytest.raises(RuntimeError, match='SHA-256 mismatch'):
        smoke._verify_checksum(archive, sidecar)


def test_browser_analysis_requires_completed_usable_result():
    result = {'items': [{'name': 'Revenue'}]}
    job = smoke._require_completed_analysis({'job': {'status': 'completed', 'result': result}})
    assert job['result'] == result


@pytest.mark.parametrize('payload, message', [
    ({'job': {'status': 'running'}}, 'ended with running'),
    ({'job': {'status': 'failed', 'error': 'scan failed'}}, 'scan failed'),
    ({'job': {'status': 'completed', 'result': {'items': []}}}, 'usable results'),
    ({'accepted': True}, 'did not contain a job'),
])
def test_browser_analysis_rejects_accepted_incomplete_or_failed_jobs(payload, message):
    with pytest.raises(RuntimeError, match=message):
        smoke._require_completed_analysis(payload)


@pytest.mark.parametrize('broken', [None, 'skip_transitive_errors', 'accept_unknown_schema'])
def test_launcher_schema_probe_detects_real_validation_and_regressions(tmp_path, monkeypatch, broken):
    report = tmp_path / 'Disposable.Report'
    report.mkdir()
    requests = []

    def deny_network(*args, **kwargs):
        raise AssertionError('Packaging schema fixtures must validate offline')

    monkeypatch.setattr(socket, 'socket', deny_network)
    monkeypatch.setattr(socket, 'create_connection', deny_network)

    def request(path, body=None):
        requests.append((path, body))
        if body is not None:
            assert body == {'model_paths': [], 'report_paths': [str(report)]}
            return json.dumps({'job': {'id': 'isolated-smoke'}}).encode()
        result = metadata_validation.validate_report_paths([report])
        for record in result['files']:
            if broken == 'skip_transitive_errors' and 'PackagingInvalid/' in record['path']:
                record.update(status='valid', errors=[])
            if broken == 'accept_unknown_schema' and record['path'].endswith('packaging-unknown.json'):
                record.update(status='valid', reason='')
        return json.dumps({'job': {'status': 'completed', 'result': {'schemaValidation': result}}}).encode()

    if broken:
        with pytest.raises(RuntimeError, match='Transitive schema error|Unknown schema'):
            smoke._schema_smoke(request, [], [str(report)], timeout=1)
    else:
        bundle = smoke._schema_smoke(request, [], [str(report)], timeout=1)
        assert bundle['schema_count'] > 0
        assert bundle['network_access'] is False
    assert [path for path, _ in requests] == [
        '/api/analysis-jobs', '/api/analysis-jobs/isolated-smoke']
    assert len(list(report.rglob('*.json'))) == 3
