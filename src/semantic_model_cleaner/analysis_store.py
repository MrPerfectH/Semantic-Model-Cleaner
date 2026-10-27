"""Content-verified local analysis reuse; JSON data only, never Python pickles."""
from dataclasses import fields, is_dataclass
from functools import lru_cache
import gzip
import hashlib
import json
import os
import sys
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
import tempfile
import zlib

from . import __version__

FORMAT = 1
MAX_BYTES = 128 * 1024 * 1024
MAX_COMPRESSED = 8 * 1024 * 1024


def _json(value):
    return json.dumps(value, ensure_ascii=True, separators=(',', ':')).encode('utf-8')


def _immutable_key(value):
    if value is None or type(value) in (str, int, float, bool):
        return (type(value).__name__, value)
    if isinstance(value, tuple):
        return ('tuple', tuple(_immutable_key(v) for v in value))
    raise TypeError('Mutable value')


def _pack(value):
    shared, indices = [], {}

    def intern(key, build):
        if key not in indices:
            indices[key] = len(shared)
            shared.append(build())
        return {'t': 'ref', 'v': indices[key]}

    def pack(value):
        if value is None or type(value) in (str, int, float, bool):
            return value
        if isinstance(value, Path):
            return {'t': 'path', 'v': str(value)}
        if is_dataclass(value):
            def record():
                return {'t': 'record', 'n': type(value).__name__,
                        'v': {f.name: pack(getattr(value, f.name)) for f in fields(value)}}
            try:
                key = ('record', type(value).__name__, tuple(_immutable_key(getattr(value, f.name)) for f in fields(value)))
            except TypeError:
                return record()
            return intern(key, record)
        if isinstance(value, dict):
            def mapping():
                return {'t': 'dict', 'v': [[pack(k), pack(v)] for k, v in value.items()]}
            # Repeated serialized Report locations dominate large analyses. Only
            # immutable leaves are shared, and decoding still copies each map.
            if len(value) >= 8 and all(isinstance(k, str) for k in value):
                try:
                    key = ('dict', tuple((k, _immutable_key(v)) for k, v in value.items()))
                except TypeError:
                    pass
                else:
                    return intern(key, mapping)
            return mapping()
        if isinstance(value, (list, tuple, set, frozenset)):
            return {'t': type(value).__name__, 'v': [pack(v) for v in value]}
        raise TypeError(f'Unsupported analysis cache value: {type(value).__name__}')

    root = pack(value)
    return {'t': 'shared', 'v': root, 'shared': shared} if shared else root


@lru_cache(maxsize=1)
def _record_classes():
    from . import analyzer
    return {name: (cls, {f.name for f in fields(cls)}) for name, cls in vars(analyzer).items()
            if isinstance(cls, type) and is_dataclass(cls) and cls.__module__ == analyzer.__name__}


def _unpack(value):
    shared = value.get('shared', []) if isinstance(value, dict) else []
    memo = {}

    def record(value):
        cls, expected = _record_classes()[value['n']]
        contents = value['v']
        if set(contents) != expected:
            raise ValueError('Incompatible cached record')
        return cls, {k: unpack(v) for k, v in contents.items()}

    def unpack(value):
        if not isinstance(value, dict):
            return value
        tag, contents = value['t'], value['v']
        if tag == 'shared':
            return unpack(contents)
        if tag == 'ref':
            if contents not in memo:
                stored = shared[contents]
                memo[contents] = record(stored) if stored['t'] == 'record' else unpack(stored)
            result = memo[contents]
            # Reusing a serialized leaf must not couple caller mutations.
            if isinstance(result, dict):
                return dict(result)
            cls, fields_ = result
            return cls(**fields_)
        if tag == 'dict':
            return {unpack(k): unpack(v) for k, v in contents}
        if tag == 'path':
            return Path(contents)
        if tag == 'record':
            cls, fields_ = record(value)
            return cls(**fields_)
        constructors = {'list': list, 'tuple': tuple, 'set': set, 'frozenset': frozenset}
        return constructors[tag](unpack(v) for v in contents)

    return unpack(value)


@lru_cache(maxsize=1)
def _engine():
    root = Path(__file__).parent
    dependencies = []
    for package in ('jsonschema', 'referencing'):
        try:
            dependencies.append(version(package))
        except PackageNotFoundError:
            dependencies.append('bundled')
    digest = hashlib.sha256(_json([__version__, sys.version, dependencies]))
    if getattr(sys, 'frozen', False):
        with Path(sys.executable).open('rb') as stream:
            digest.update(hashlib.file_digest(stream, 'sha256').digest())
    for path in sorted([*root.glob('*.py'), *(root / 'schemas').rglob('*.json')]):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def fingerprint(workspace, options):
    """Hash current contents, paths, discovery and bindings, never just stats."""
    from . import analyzer
    roots = sorted({Path(path).resolve() for name in ('model_paths', 'report_paths') for path in options[name]})
    digest = hashlib.sha256(_json([FORMAT, _engine(), _pack({key: value for key, value in options.items()
                        if key not in {'cache', 'progress', 'model_search_roots', 'report_search_roots'}})]))
    observed = hashlib.sha256()

    def stamp(path):
        info = path.stat()
        return (info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino)

    for root in roots:
        if not root.is_dir() or root.is_symlink():
            raise ValueError('Unavailable cache scope')
        digest.update(str(root).encode())
        for path in sorted(root.rglob('*')):
            if path.is_symlink():
                raise ValueError('Symlink cache scope')
            before = stamp(path)
            digest.update(_json([path.relative_to(root).as_posix(), before[0]]))
            observed.update(_json(before))
            if path.is_file():
                with path.open('rb') as stream:
                    digest.update(hashlib.file_digest(stream, 'sha256').digest())
                if stamp(path) != before:
                    raise ValueError('Input changed while its fingerprint was being read')
    searches = {Path(workspace).resolve(), *(path.parent for path in roots)}
    for name in ('model_search_roots', 'report_search_roots'):
        searches.update(Path(path).resolve() for path in options.get(name) or [])
    if any(not path.is_dir() for path in searches):
        raise ValueError('Unavailable discovery root')
    reports = analyzer.discover_reports(sorted(searches))
    models = analyzer.discover_models(sorted(searches))
    digest.update(_json([[str(path) for path in models], [str(path) for path in reports]]))
    for report in reports:
        binding = report / 'definition.pbir'
        if binding.exists():
            before = stamp(binding)
            digest.update(binding.read_bytes())
            observed.update(_json(before))
            if stamp(binding) != before:
                raise ValueError('Binding changed while its fingerprint was being read')
        else:
            digest.update(b'missing-binding')
    return digest.hexdigest(), observed.hexdigest()


def _directory(options):
    state = Path(os.environ.get('SMC_USER_DIR', str(Path.home() / '.semantic-model-cleaner'))).resolve()
    roots = [Path(path).resolve() for name in ('model_paths', 'report_paths') for path in options[name]]
    directory = (state / 'analysis-cache').resolve()
    if any(directory.is_relative_to(root) for root in roots):
        raise ValueError('Cache must be outside selected artifacts')
    return directory


def _load(path, key):
    if path.is_symlink() or path.stat().st_size > MAX_COMPRESSED:
        return None
    with gzip.open(path, 'rb') as stream:
        content = stream.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        return None
    stored = json.loads(content)
    if stored['format'] != FORMAT or stored['key'] != key \
            or hashlib.sha256(_json(stored['payload'])).hexdigest() != stored['digest']:
        return None
    result = _unpack(stored['payload'])
    if not isinstance(result, dict) or not {'items', 'coverage', 'dependency_graphs', 'report_references'} <= result.keys():
        return None
    return result


def _save(path, key, result):
    payload = _pack(result)
    content = _json(dict(format=FORMAT, key=key, payload=payload, digest=hashlib.sha256(_json(payload)).hexdigest()))
    if len(content) > MAX_BYTES:
        return
    compressed = gzip.compress(content, compresslevel=1, mtime=0)
    if len(compressed) > MAX_COMPRESSED:
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='pending-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(compressed)
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    entries = sorted(path.parent.glob('*.json.gz'), key=lambda p: p.stat().st_mtime_ns, reverse=True)
    for old in entries[32:]:
        old.unlink(missing_ok=True)


def _prepare_parse_cache(options, key):
    cache = options.get('cache')
    if cache is not None and (key is None or getattr(cache, '_content_key', None) != key):
        for name in ('model', 'extensions', 'reports', 'graphs', 'suggestions'):
            getattr(cache, name).clear()
        cache._content_key = key


def analyze(workspace, options, calculate):
    """Return an independent decoded result only after two matching snapshots."""
    try:
        snapshot = fingerprint(workspace, options)
        key = snapshot[0]
        path = _directory(options) / (key + '.json.gz')
    except (OSError, ValueError):
        _prepare_parse_cache(options, None)
        return calculate()
    try:
        cached = _load(path, key)
    except (OSError, ValueError, KeyError, IndexError, TypeError, EOFError, RecursionError, zlib.error):
        cached = None
    if cached is not None:
        if fingerprint(workspace, options) == snapshot:
            if options.get('progress'):
                options['progress']('Reusing content-verified analysis')
            return cached
        raise ValueError('Input changed while cached analysis was being read; retry on a stable scope.')
    _prepare_parse_cache(options, key)
    result = calculate()
    if fingerprint(workspace, options) != snapshot:
        raise ValueError('Input changed while analysis was running; retry on a stable scope.')
    try:
        _save(path, key, result)
    except (OSError, ValueError, TypeError, RecursionError):
        pass  # Cache failures never prevent a fresh result.
    return result
