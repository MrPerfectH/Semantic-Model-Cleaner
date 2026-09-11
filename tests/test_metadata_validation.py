"""Declared-schema checks use the pristine, pinned bundle without networking."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

import pytest
from referencing import Registry

from semantic_model_cleaner import metadata_validation as metadata

FIXTURES = Path(__file__).parent / 'fixtures' / 'schema-validation'
BASE = 'https://developer.microsoft.com/json-schemas/fabric/item/report/definition/'


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def snapshot(document, path='report-1/definition/pages/Overview/page.json'):
    return metadata.validate_metadata({path: json.dumps(document)})


def test_bundle_has_pinned_source_license_and_complete_local_references():
    info = metadata.bundle_info()
    assert info['commit'] == '83ce11373faada0d01e76264a5cceb0ba70003e6'
    assert info['schema_count'] == 97
    assert info['network_access'] is False
    assert info['format_assertions'] is False
    assert 'Microsoft Corporation' in (metadata.BUNDLE_ROOT / 'LICENSE').read_text()


def test_declared_page_and_transitive_visual_schema_pass_without_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError('Validation must not use a network socket')
    monkeypatch.setattr(socket, 'create_connection', deny)
    monkeypatch.setattr(socket, 'socket', deny)
    assert metadata.validate_document(fixture('page-valid.json'))['status'] == 'valid'
    assert metadata.validate_document(fixture('visual-valid.json'))['status'] == 'valid'


def test_transitive_embedded_schema_error_has_exact_instance_path():
    visual = fixture('visual-valid.json')
    visual['visual']['visualType'] = 42
    result = metadata.validate_document(visual)
    assert result['status'] == 'invalid'
    assert any(error['path'] == '/visual/visualType' and error['keyword'] == 'type'
               for error in result['errors'])


@pytest.mark.parametrize('document,reason', [
    ({'name': 'Overview', 'version': '2.1.0'}, 'missing_schema'),
    ({'$schema': 'https://attacker.invalid/collect'}, 'unknown_schema'),
    ({'$schema': BASE + 'page/99.0.0/schema.json'}, 'unknown_schema'),
    ({'$schema': ''}, 'invalid_schema_declaration'),
    ({'$schema': 7}, 'invalid_schema_declaration'),
])
def test_unknown_or_missing_declarations_are_not_passed_or_inferred(document, reason):
    result = metadata.validate_document(document, path='definition/page.json')
    assert result['status'] == 'not_validated'
    assert result['reason'] == reason


@pytest.mark.parametrize('name', [
    'visualConfiguration/1.8.0/schema-embedded.json',
    'visualConfiguration/2.0.0/schema.json',
    'visualContainer/1.8.0/schema.json',
    'visualContainerMobileState/1.5.0/schema.json',
])
def test_upstream_identity_conflicts_and_dependents_do_not_use_wrong_schema(name):
    result = metadata.validate_document({'$schema': BASE + name})
    assert result['status'] == 'not_validated'
    assert 'identity_conflict' in result['reason']


def test_snapshot_distinguishes_invalid_json_unknown_schema_and_excluded_tmdl():
    result = metadata.validate_metadata({
        'model/definition/tables/Sales.tmdl': b'table Sales',
        'report-1/definition.pbir': b'{bad',
        'report-1/definition/page.json': b'{"name":"Overview"}',
    })
    assert result['counts'] == {'valid': 0, 'invalid': 1, 'not_validated': 1}
    assert result['ok'] is False
    assert result['complete'] is False
    assert result['files'][0]['reason'] == 'invalid_json'


def test_before_after_detects_new_and_resolved_errors_at_equal_counts():
    before_doc = fixture('page-valid.json')
    before_doc['width'] = 'bad'
    after_doc = fixture('page-valid.json')
    after_doc['height'] = 'bad'
    difference = metadata.compare_validation(snapshot(before_doc), snapshot(after_doc))
    assert difference['ok'] is False
    assert [error['path'] for error in difference['new_errors']] == ['/height']
    assert [error['path'] for error in difference['resolved_errors']] == ['/width']


def test_unchanged_preexisting_errors_are_not_new():
    document = fixture('page-valid.json')
    document['width'] = 'bad'
    before = snapshot(document)
    document['displayName'] = 'Renamed'
    result = metadata.compare_validation(before, snapshot(document))
    assert result['ok'] is True
    assert result['new_errors'] == []


def test_removing_declaration_loses_validation_and_cannot_look_like_a_fix():
    document = fixture('page-valid.json')
    before = snapshot(document)
    del document['$schema']
    result = metadata.compare_validation(before, snapshot(document))
    assert result['ok'] is False
    assert result['lost_validation']
    assert result['changed_not_validated']
    assert result['comparison_complete'] is False


def test_unchanged_unknown_file_is_tolerated_but_changed_unknown_is_explicit():
    document = {'name': 'Overview'}
    before = snapshot(document)
    assert metadata.compare_validation(before, before)['ok'] is True
    document['name'] = 'Other'
    result = metadata.compare_validation(before, snapshot(document))
    assert result['ok'] is False
    assert result['changed_not_validated']


def test_error_limit_marks_evidence_incomplete():
    document = {'$schema': BASE + 'page/2.1.0/schema.json'}
    result = metadata.validate_metadata({'page.json': json.dumps(document)}, error_limit=1)
    assert result['files'][0]['truncated'] is True
    assert result['complete'] is False
    assert len(result['files'][0]['errors']) == 1
    comparison = metadata.compare_validation(result, result)
    assert comparison['ok'] is False
    assert comparison['truncated'] is True


def test_absent_runtime_registry_reference_is_not_reported_as_valid(monkeypatch):
    manifest, schemas, _, unsupported = metadata._bundle()
    monkeypatch.setattr(metadata, '_bundle', lambda: (manifest, schemas, Registry(), unsupported))
    result = metadata.validate_document(fixture('visual-valid.json'))
    assert result['status'] == 'not_validated'
    assert result['reason'] == 'unresolved_bundled_reference'


def test_bundle_checksum_failure_is_explicit(tmp_path, monkeypatch):
    manifest = {'schemas': [{'path': 'schema.json', 'sha256': hashlib.sha256(b'original').hexdigest(),
                             'uri': BASE + 'fake', 'id': BASE + 'fake'}]}
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    (tmp_path / 'schema.json').write_text('{}')
    monkeypatch.setattr(metadata, 'BUNDLE_ROOT', tmp_path)
    metadata._bundle.cache_clear()
    try:
        with pytest.raises(metadata.SchemaBundleError, match='checksum mismatch'):
            metadata.bundle_info()
    finally:
        metadata._bundle.cache_clear()


def test_path_identity_keeps_same_named_reports_separate():
    document = fixture('page-valid.json')
    before = metadata.validate_metadata({'report-1/page.json': json.dumps(document),
                                         'report-2/page.json': json.dumps(document)})
    changed = deepcopy(document)
    changed['width'] = 'invalid'
    after = metadata.validate_metadata({'report-1/page.json': json.dumps(document),
                                        'report-2/page.json': json.dumps(changed)})
    assert metadata.compare_validation(before, after)['new_errors'][0]['file'] == 'report-2/page.json'
