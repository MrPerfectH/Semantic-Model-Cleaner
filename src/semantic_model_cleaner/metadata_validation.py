"""Offline validation of explicitly declared Microsoft report schemas.

No schema is inferred from a filename, version property, or report layout. The
registry contains only the bundled, pinned Microsoft schemas; it cannot fetch
unknown references or send local metadata to a remote service.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from functools import lru_cache
import hashlib
from itertools import islice
import json
import os
from pathlib import Path
from urllib.parse import urldefrag, urljoin

from jsonschema import validators
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource, Unresolvable

BUNDLE_ROOT = Path(__file__).parent / 'schemas' / 'microsoft-report'
METADATA_SUFFIXES = frozenset({'.json', '.pbir', '.pbism'})


class SchemaBundleError(ValueError):
    """The packaged schema bundle is incomplete or changed unexpectedly."""


def _offline_only(uri: str):
    raise NoSuchResource(ref=uri)


def _references(value, base):
    if isinstance(value, dict):
        base = urljoin(base, value.get('$id', ''))
        if '$ref' in value:
            yield urldefrag(urljoin(base, value['$ref']))[0]
        for child in value.values():
            yield from _references(child, base)
    elif isinstance(value, list):
        for child in value:
            yield from _references(child, base)


@lru_cache(maxsize=1)
def _bundle():
    manifest = json.loads((BUNDLE_ROOT / 'manifest.json').read_text(encoding='utf-8'))
    canonical = {}
    for entry in manifest['schemas']:
        path = BUNDLE_ROOT / entry['path']
        if not path.resolve().is_relative_to(BUNDLE_ROOT.resolve()):
            raise SchemaBundleError('Schema manifest path escapes the bundled directory.')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise SchemaBundleError(f'Bundled schema checksum mismatch: {entry["path"]}')
        schema = json.loads(raw)
        if schema.get('$id') != entry['id']:
            raise SchemaBundleError(f'Bundled schema identity mismatch: {entry["path"]}')
        validators.validator_for(schema).check_schema(schema)
        canonical[entry['uri']] = schema
    schemas = dict(canonical)
    unsupported = {}
    for uri, schema in canonical.items():
        identity = schema['$id']
        if identity == uri:
            continue
        if identity in canonical:
            unsupported[uri] = 'upstream_schema_identity_conflict'
        elif identity in schemas and schemas[identity] != schema:
            raise SchemaBundleError(f'Ambiguous bundled alias: {identity}')
        else:
            # Unambiguous hyphen/dot embedded names are both declared upstream.
            schemas[identity] = schema
    references = {uri: set(_references(schema, uri)) for uri, schema in schemas.items()}
    for uri, refs in references.items():
        missing = refs - schemas.keys()
        if missing:
            raise SchemaBundleError('Missing bundled schema reference: ' + ', '.join(sorted(missing)))
    while True:
        dependent = {uri: 'upstream_dependency_identity_conflict' for uri, refs in references.items()
                     if uri not in unsupported and refs & unsupported.keys()}
        if not dependent:
            break
        unsupported.update(dependent)
    registry = Registry(retrieve=_offline_only)
    for uri, schema in schemas.items():
        if uri not in unsupported:
            registry = registry.with_resource(uri, Resource.from_contents(schema))
    return manifest, schemas, registry, unsupported


def bundle_info() -> dict:
    manifest, schemas, _, unsupported = _bundle()
    return {'repository': manifest['repository'], 'commit': manifest['commit'],
            'schema_count': len(manifest['schemas']), 'registered_uris': len(schemas) - len(unsupported),
            'unavailable_schemas': sorted(unsupported),
            'network_access': False, 'format_assertions': False}


def _pointer(parts) -> str:
    return ''.join('/' + str(part).replace('~', '~0').replace('/', '~1') for part in parts)


def validate_document(document, *, path: str = '', error_limit: int = 100) -> dict:
    """Validate one decoded document only against its exact bundled $schema.

    ``not_validated`` is explicit absence of evidence, never a passing result.
    Errors include instance/schema JSON pointers; no runtime/schema fetch occurs.
    """
    if error_limit < 1:
        raise ValueError('error_limit must be positive')
    declared = document.get('$schema') if isinstance(document, dict) else None
    result = {'path': path, 'schema': declared if isinstance(declared, str) else None,
              'status': 'not_validated', 'reason': '', 'errors': [], 'truncated': False}
    if declared is None:
        return {**result, 'reason': 'missing_schema'}
    if not isinstance(declared, str) or not declared:
        return {**result, 'reason': 'invalid_schema_declaration'}
    _, schemas, registry, unsupported = _bundle()
    if declared in unsupported:
        return {**result, 'reason': unsupported[declared]}
    schema = schemas.get(declared)
    if schema is None:
        return {**result, 'reason': 'unknown_schema'}
    validator = validators.validator_for(schema)(schema, registry=registry)
    try:
        errors = list(islice(validator.iter_errors(document), error_limit + 1))
    except (Unresolvable, NoSuchResource) as exc:
        return {**result, 'reason': 'unresolved_bundled_reference', 'detail': str(exc)}
    result['errors'] = [
        {'path': _pointer(error.absolute_path), 'schema_path': _pointer(error.absolute_schema_path),
         'keyword': str(error.validator), 'message': error.message[:800],
         'message_truncated': len(error.message) > 800,
         'detail_hash': hashlib.sha256(error.message.encode()).hexdigest()}
        for error in errors[:error_limit]
    ]
    result['errors'].sort(key=lambda error: (error['path'], error['schema_path'], error['message']))
    result['truncated'] = len(errors) > error_limit
    result['status'] = 'invalid' if errors else 'valid'
    result['reason'] = 'schema_errors' if errors else 'declared_schema_valid'
    return result


def validate_metadata(files: Mapping[str, bytes | str], *, error_limit: int = 100) -> dict:
    """Validate a metadata snapshot, keyed by stable artifact-relative paths.

    Non-JSON metadata (including TMDL) is deliberately excluded. JSON syntax
    failures are reported separately from successfully executed schema checks.
    ``ok`` alone does not establish coverage; inspect ``complete`` and counts.
    """
    if error_limit < 1:
        raise ValueError('error_limit must be positive')
    records = []
    for path, content in sorted(files.items()):
        if Path(path).suffix.lower() not in METADATA_SUFFIXES:
            continue
        raw = content.encode('utf-8') if isinstance(content, str) else content
        fingerprint = hashlib.sha256(raw).hexdigest()
        try:
            document = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            records.append({'path': path, 'schema': None, 'status': 'invalid',
                            'reason': 'invalid_json', 'content_hash': fingerprint,
                            'errors': [{'path': '', 'schema_path': '', 'keyword': 'json_syntax',
                                        'message': str(exc)}], 'truncated': False})
            continue
        result = validate_document(document, path=path, error_limit=error_limit)
        records.append({**result, 'content_hash': fingerprint})
    counts = Counter(record['status'] for record in records)
    return {'ok': counts['invalid'] == 0,
            'complete': bool(records) and counts['not_validated'] == 0
                        and not any(record['truncated'] or record['reason'] == 'invalid_json' for record in records),
            'counts': {key: counts[key] for key in ('valid', 'invalid', 'not_validated')},
            'files': records, 'bundle': bundle_info()}


def compare_validation(before: dict, after: dict) -> dict:
    """Compare stable-path summaries without treating pre-existing errors as new.

    Changed documents without a supported declaration, schema downgrades and
    truncated evidence are reported explicitly; callers choose their policy.
    """
    old = {record['path']: record for record in before['files']}
    new = {record['path']: record for record in after['files']}

    def errors(records):
        found = {}
        for path, record in records.items():
            for error in record['errors']:
                key = (path, record['schema'], error['path'], error['schema_path'],
                       error['keyword'], error.get('detail_hash', error['message']))
                found[key] = {'file': path, 'schema': record['schema'], **error}
        return found

    old_errors, new_errors = errors(old), errors(new)
    introduced = [new_errors[key] for key in new_errors.keys() - old_errors.keys()]
    resolved = [old_errors[key] for key in old_errors.keys() - new_errors.keys()]
    changed_unknown = [path for path, record in new.items()
                       if record['status'] == 'not_validated'
                       and (path not in old or record['content_hash'] != old[path]['content_hash'])]
    lost = [path for path, record in old.items() if record['status'] != 'not_validated'
            and path in new and new[path]['status'] == 'not_validated']
    truncated = any(record['truncated'] for record in [*old.values(), *new.values()])
    complete = not changed_unknown and not truncated
    return {'ok': not introduced and not lost and complete,
            'comparison_complete': complete, 'truncated': truncated,
            'new_errors': sorted(introduced, key=lambda error: (error['file'], error['path'], error['message'])),
            'resolved_errors': sorted(resolved, key=lambda error: (error['file'], error['path'], error['message'])),
            'lost_validation': sorted(lost), 'changed_not_validated': sorted(changed_unknown)}


def validate_report_paths(report_paths, *, workspace=None, progress=None):
    """Read report metadata one file at a time; never retain a whole raw workspace."""
    records = []
    paths = sorted({Path(p).resolve() for p in report_paths})
    files = [(root, path) for root in paths for path in sorted(root.rglob('*'))
             if path.is_file() and path.suffix.lower() in METADATA_SUFFIXES
             and '.pbi' not in path.relative_to(root).parts]
    for index, (root, path) in enumerate(files):
        if progress and index % 20 == 0:
            progress('Checking declared report schemas', index, len(files))
        key = (Path(os.path.relpath(path, workspace)).as_posix() if workspace else
               f'report-{paths.index(root)+1}/{path.relative_to(root).as_posix()}')
        result = validate_metadata({key: path.read_bytes()})
        records.extend(result['files'])
    counts = Counter(record['status'] for record in records)
    return {'ok': counts['invalid'] == 0,
            'complete': bool(records) and counts['not_validated'] == 0
                        and not any(r['truncated'] or r['reason'] == 'invalid_json' for r in records),
            'counts': {key: counts[key] for key in ('valid', 'invalid', 'not_validated')},
            'files': records, 'bundle': bundle_info()}
