"""Reject incomplete or mismatched native VSIX releases before publishing anything."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tomllib
from xml.etree import ElementTree
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]


def verify_packages(paths, targets, *, extension, engine_version, revision):
    found = set()
    for path in map(Path, paths):
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        expected = f'{checksum}  {path.name}'
        if path.with_suffix('.vsix.sha256').read_text(encoding='ascii').strip() != expected:
            raise ValueError(f'Checksum mismatch: {path.name}')
        with ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError(f'Duplicate archive entries: {path.name}')
            package = json.loads(archive.read('extension/package.json'))
            engine = json.loads(archive.read('extension/engine/manifest.json'))
            identity = ElementTree.fromstring(archive.read('extension.vsixmanifest')).find('.//{*}Identity')
            if identity is None:
                raise ValueError(f'Missing VSIX identity: {path.name}')
            target = f'{engine["platform"]}-{engine["arch"]}'
            if target not in targets or target in found:
                raise ValueError(f'Unexpected or duplicate target: {target}')
            found.add(target)
            for field, xml_field in [('name', 'Id'), ('publisher', 'Publisher'), ('version', 'Version')]:
                if package.get(field) != extension[field] or identity.get(xml_field) != extension[field]:
                    raise ValueError(f'Extension {field} mismatch: {path.name}')
            filename = f'{extension["name"]}-{extension["version"]}-{target}.vsix'
            if path.name != filename or identity.get('TargetPlatform') != target:
                raise ValueError(f'Platform/package filename mismatch: {path.name}')
            if (engine.get('engineVersion') != engine_version or engine.get('protocol') != 1
                    or engine.get('sourceRevision') != revision or engine.get('sourceDirty') is not False):
                raise ValueError(f'Engine version/source identity mismatch or dirty build: {path.name}')
            executable = 'smc-engine.exe' if engine['platform'] == 'win32' else 'smc-engine'
            if engine.get('executable') != executable:
                raise ValueError(f'Unexpected engine executable: {path.name}')
            required = [f'extension/engine/{executable}', 'extension/engine/licenses/Python-LICENSE.txt',
                        'extension/engine/_internal/semantic_model_cleaner/templates/index_v2.html']
            if any(name not in names or archive.getinfo(name).file_size == 0 for name in required):
                raise ValueError(f'Missing bundled runtime/assets/notices: {path.name}')
            if engine['platform'] != 'win32' and not archive.getinfo(required[0]).external_attr >> 16 & 0o111:
                raise ValueError(f'Engine executable permission missing: {path.name}')
            schema_prefix = 'extension/engine/_internal/semantic_model_cleaner/schemas/'
            if not any(name.startswith(schema_prefix) for name in names):
                raise ValueError(f'Missing bundled schemas: {path.name}')
    if found != set(targets):
        raise ValueError(f'Missing native packages: {sorted(set(targets) - found)}')
    return sorted(found)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', action='append', required=True)
    parser.add_argument('packages', type=Path, nargs='+')
    args = parser.parse_args()
    extension = json.loads((ROOT / 'vscode-extension/package.json').read_text())
    engine_version = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    targets = verify_packages(args.packages, args.target, extension=extension,
                             engine_version=engine_version, revision=revision)
    print('Verified native packages: ' + ', '.join(targets))


if __name__ == '__main__':
    main()
