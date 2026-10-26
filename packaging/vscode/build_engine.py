"""Build an engine on the target OS/architecture, then stage it for VSIX packaging."""
from __future__ import annotations

import json
from importlib import metadata
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import sysconfig
import tomllib

from packaging.requirements import Requirement


ROOT = Path(__file__).resolve().parents[2]


def copy_notices(stage: Path, dependencies: list[str]) -> None:
    notices = stage / 'licenses'
    notices.mkdir()
    candidates = [Path(sysconfig.get_path('stdlib')) / 'LICENSE.txt',
                  Path(sys.base_prefix) / 'LICENSE.txt']
    python_license = next((file for file in candidates if file.is_file()), None)
    if python_license is None:
        raise RuntimeError('Python license not found; include the runtime license before distributing.')
    shutil.copy2(python_license, notices / 'Python-LICENSE.txt')
    pending = [*dependencies, 'pyinstaller']
    seen = set()
    while pending:
        requirement = Requirement(pending.pop())
        if requirement.marker and not requirement.marker.evaluate({'extra': ''}):
            continue
        distribution = metadata.distribution(requirement.name)
        name = distribution.metadata['Name']
        if name in seen:
            continue
        seen.add(name)
        pending.extend(distribution.requires or [])
        for item in distribution.files or []:
            if any(word in item.name.lower() for word in ('license', 'licence', 'copying', 'copyright')):
                source = Path(distribution.locate_file(item))
                if source.is_file():
                    destination = notices / name / str(item)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)


def main() -> None:
    machine = platform.machine().lower()
    arch = {'amd64': 'x64', 'x86_64': 'x64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(machine)
    if sys.platform not in {'win32', 'darwin', 'linux'} or arch is None:
        raise SystemExit(f'Unsupported engine build host: {sys.platform}-{machine}')
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
    version = project['version']
    build = ROOT / 'build' / 'vscode-engine'
    build.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
               '--console', '--name', 'smc-engine', '--paths', str(ROOT / 'src'),
               '--distpath', str(build / 'dist'), '--workpath', str(build / 'work'),
               '--specpath', str(build)]
    for directory in ('templates', 'static', 'schemas', 'demo_workspace'):
        source = ROOT / 'src' / 'semantic_model_cleaner' / directory
        command += ['--add-data', f'{source}{":" if sys.platform != "win32" else ";"}semantic_model_cleaner/{directory}']
    subprocess.run(command + [str(Path(__file__).with_name('entrypoint.py'))], cwd=ROOT, check=True)
    stage = ROOT / 'vscode-extension' / 'engine'
    shutil.rmtree(stage, ignore_errors=True)
    shutil.copytree(build / 'dist' / 'smc-engine', stage)
    shutil.copy2(ROOT / 'LICENSE', stage / 'LICENSE')
    copy_notices(stage, project['dependencies'])
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True))
    manifest = dict(engineVersion=version, protocol=1, platform=sys.platform, arch=arch,
                    executable='smc-engine.exe' if sys.platform == 'win32' else 'smc-engine',
                    sourceRevision=revision, sourceDirty=dirty)
    (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(f'Staged engine {version} for {sys.platform}-{arch}: {stage}')


if __name__ == '__main__':
    main()
