"""Publication must reject damaged or mixed native packages before uploading any."""
import hashlib
import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile, ZipInfo

import pytest


ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('verify_vscode_packages', ROOT / 'scripts/verify_vscode_packages.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
EXTENSION = {'name': 'semantic-model-cleaner', 'publisher': 'MrPerfectH', 'version': '0.1.8'}
REVISION = 'a' * 40


def package(directory, target='win32-x64', *, overrides=None, mode=0o755, omitted=()):
    directory.mkdir(parents=True, exist_ok=True)
    platform, arch = target.split('-')
    executable = 'smc-engine.exe' if platform == 'win32' else 'smc-engine'
    engine = dict(engineVersion='0.4.0b10', protocol=1, platform=platform, arch=arch,
                  executable=executable, sourceRevision=REVISION, sourceDirty=False)
    engine.update(overrides or {})
    entries = {
        'extension/package.json': json.dumps(EXTENSION),
        'extension/engine/manifest.json': json.dumps(engine),
        'extension.vsixmanifest': '<PackageManifest><Metadata><Identity '
            f'Id="{EXTENSION["name"]}" Publisher="{EXTENSION["publisher"]}" '
            f'Version="{EXTENSION["version"]}" TargetPlatform="{target}" /></Metadata></PackageManifest>',
        f'extension/engine/{executable}': 'runtime fixture',
        'extension/engine/licenses/Python-LICENSE.txt': 'license fixture',
        'extension/engine/_internal/semantic_model_cleaner/templates/index_v2.html': '<html>fixture</html>',
        'extension/engine/_internal/semantic_model_cleaner/schemas/manifest.json': '{}',
    }
    path = directory / f'{EXTENSION["name"]}-{EXTENSION["version"]}-{target}.vsix'
    with ZipFile(path, 'w') as archive:
        for name, value in entries.items():
            if name not in omitted:
                entry = ZipInfo(name)
                entry.external_attr = (0o100000 | mode) << 16
                archive.writestr(entry, value)
    checksum(path)
    return path


def checksum(path):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix('.vsix.sha256').write_text(f'{digest}  {path.name}\n')


def verify(paths, targets=('win32-x64', 'linux-x64')):
    return release.verify_packages(paths, targets, extension=EXTENSION,
                                   engine_version='0.4.0b10', revision=REVISION)


def test_complete_native_release_passes(tmp_path):
    paths = [package(tmp_path, target) for target in ['win32-x64', 'linux-x64']]
    assert verify(paths) == ['linux-x64', 'win32-x64']


def test_missing_or_duplicate_platform_cannot_publish(tmp_path):
    one = package(tmp_path)
    with pytest.raises(ValueError, match='Missing native packages'):
        verify([one])
    with pytest.raises(ValueError, match='duplicate target'):
        verify([one, one])


@pytest.mark.parametrize('overrides', [
    {'sourceDirty': True}, {'sourceDirty': None}, {'sourceRevision': 'b' * 40},
    {'engineVersion': 'old'}, {'protocol': 2}, {'executable': '../external'},
    {'arch': 'arm64'},
])
def test_mixed_stale_or_unreviewed_engine_is_rejected(tmp_path, overrides):
    path = package(tmp_path, overrides=overrides)
    with pytest.raises(ValueError):
        verify([path], ['win32-x64'])


def test_corrupted_package_cannot_publish(tmp_path):
    path = package(tmp_path)
    with path.open('ab') as stream:
        stream.write(b'corruption')
    with pytest.raises(ValueError, match='Checksum mismatch'):
        verify([path], ['win32-x64'])


def test_missing_runtime_asset_is_rejected_even_with_valid_checksum(tmp_path):
    path = package(tmp_path, omitted=['extension/engine/smc-engine.exe'])
    with pytest.raises(ValueError, match='Missing bundled'):
        verify([path], ['win32-x64'])


def test_unix_engine_must_be_executable_after_extraction(tmp_path):
    path = package(tmp_path, 'linux-x64', mode=0o644)
    with pytest.raises(ValueError, match='executable permission'):
        verify([path], ['linux-x64'])
