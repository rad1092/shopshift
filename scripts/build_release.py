"""Build and smoke-test a portable app and Python distributions on this OS."""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import venv
import zipfile
from pathlib import Path

from collect_licenses import ROOT, SOURCE_URL, collect, digest


def run(arguments: list[str], *, cwd: Path = ROOT, timeout: int = 900) -> None:
    print('Running:', ' '.join(arguments), flush=True)
    subprocess.run(arguments, cwd=cwd, check=True, timeout=timeout,
                   env={**os.environ, 'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1',
                        'MKL_NUM_THREADS': '1'})


def version() -> str:
    import tomllib
    return tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']


def identity() -> tuple[str, bool]:
    try:
        sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        dirty = bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'],
                                           cwd=ROOT, text=True).strip())
        return sha, dirty
    except subprocess.CalledProcessError:
        return 'uncommitted', True


def verify_smoke(path: Path) -> dict:
    results = list(path.glob('*.json'))
    screenshots = list(path.glob('*.png'))
    if not (path / 'smoke.json').is_file() or not screenshots:
        raise RuntimeError(f'Smoke did not produce JSON and a screenshot: {path}')
    if json.loads((path / 'smoke.json').read_text(encoding='utf-8')).get('passed') is not True:
        raise RuntimeError(f'Smoke success flag missing: {path}')
    reports = []
    for report in results:
        data = json.loads(report.read_text(encoding='utf-8'))
        if data.get('ok') is False or data.get('success') is False or data.get('passed') is False:
            raise RuntimeError(f'Smoke failed: {report.name}: {data}')
        reports.append({'file': report.name, 'result': data})
    if not any(image.stat().st_size > 1000 for image in screenshots):
        raise RuntimeError('Smoke screenshot is empty')
    return {'reports': reports, 'screenshots': [image.name for image in screenshots]}


def executable(install: Path) -> Path:
    if sys.platform == 'darwin':
        return install / 'ShopShift.app' / 'Contents' / 'MacOS' / 'ShopShift'
    return install / 'ShopShift' / ('ShopShift.exe' if sys.platform == 'win32' else 'ShopShift')


def validate_sdist(path: Path) -> None:
    import tomllib
    config = tomllib.loads((ROOT / 'pyproject.toml').read_text())
    approved = {name.strip('/') for name in config['tool']['hatch']['build']['targets']['sdist']['include']}
    approved.add('PKG-INFO')  # Generated core package metadata, not a checkout file.
    forbidden = {'release', 'build', '.venv', '.git', '__pycache__', '.pytest_cache', '.ruff_cache'}
    with tarfile.open(path) as distribution:
        for member in distribution:
            relative = Path(member.name).parts[1:]
            if relative and (relative[0] not in approved or forbidden.intersection(relative)
                             or member.name.endswith('.pyc')):
                raise RuntimeError(f'Unapproved/generated content in source distribution: {member.name}')


def audit_bundle(bundle: Path) -> dict:
    forbidden = ('qtwebengine', 'qtvirtualkeyboard', 'qtpdf', 'qtquick', 'qtqml',
                 'designer.exe', 'linguist.exe', 'qml.exe')
    files = [file for file in bundle.rglob('*') if file.is_file() and not file.is_symlink()]
    violations = [str(file.relative_to(bundle)) for file in files
                  if any(name in file.name.lower() for name in forbidden)
                  and 'licenses' not in file.parts and file.suffix.lower() not in {'.json', '.md', '.txt'}]
    if violations:
        raise RuntimeError(f'Unexpected optional Qt tooling/runtime: {violations}')
    native = [str(file.relative_to(bundle)) for file in files
              if file.suffix.lower() in {'.dll', '.dylib', '.so', '.pyd'} or '.so.' in file.name]
    qt_libraries = [path for path in native if 'qt' in path.lower()]
    # Framework binaries on macOS lack a conventional extension.
    if sys.platform == 'darwin':
        qt_libraries += [str(file.relative_to(bundle)) for file in files if '.framework/' in str(file)]
    if not qt_libraries:
        raise RuntimeError('Expected separately replaceable Qt libraries are missing')
    return {'files': len(files), 'unpacked_bytes': sum(file.stat().st_size for file in files),
            'native_libraries': native, 'replaceable_qt_files': qt_libraries}


def build(output: Path, *, test_wheel: bool, skip_download: bool) -> dict:
    started = time.monotonic()
    output.mkdir(parents=True, exist_ok=True)
    license_root = ROOT / 'build' / 'release-licenses'
    source_cache = ROOT / 'build' / 'upstream-sources'
    if skip_download:
        manifest = json.loads((license_root / 'manifest.json').read_text())
        for source in manifest['sources']:
            if digest(source_cache / source['file']) != source['sha256']:
                raise RuntimeError(f'Cached source failed integrity check: {source["file"]}')
    else:
        manifest = collect(license_root, source_cache)
    native_output = ROOT / 'build' / 'frozen-dist'
    run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--distpath', str(native_output),
         '--workpath', str(ROOT / 'build' / 'pyinstaller'), str(ROOT / 'shopshift.spec')])
    bundle = native_output / ('ShopShift.app' if sys.platform == 'darwin' else 'ShopShift')
    bundle_audit = audit_bundle(bundle)
    system = {'darwin': 'macos', 'win32': 'windows'}.get(sys.platform, 'linux')
    arch = {'amd64': 'x86_64', 'aarch64': 'arm64'}.get(platform.machine().lower(), platform.machine().lower())
    stem = f'ShopShift-{version()}-{system}-{arch}'
    if sys.platform == 'win32':
        archive = output / f'{stem}.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as target:
            for file in sorted(bundle.rglob('*')):
                if file.is_file():
                    target.write(file, str(file.relative_to(bundle.parent)))
    else:
        # tar preserves symbolic links and executable modes used by Qt/macOS frameworks.
        archive = output / f'{stem}.tar.gz'
        with tarfile.open(archive, 'w:gz', compresslevel=6, dereference=False) as target:
            target.add(bundle, arcname=bundle.name)
    smoke_output = ROOT / 'build' / 'release-smoke'
    if smoke_output.exists():
        shutil.rmtree(smoke_output)
    smoke_output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='shopshift-installed-') as directory:
        install = Path(directory)
        if sys.platform == 'win32':
            with zipfile.ZipFile(archive) as source:
                source.extractall(install)
        else:
            with tarfile.open(archive) as source:
                source.extractall(install, filter='data')
        # Remove Python import overrides: this must use the packaged interpreter.
        environment = dict(os.environ)
        for name in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV'):
            environment.pop(name, None)
        environment.update({'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1'})
        with (smoke_output / 'packaged-launch.log').open('w') as log:
            subprocess.run([str(executable(install)), '--smoke-test', str(smoke_output / 'packaged')],
                           cwd=install, env=environment, check=True, timeout=180,
                           stdout=log, stderr=subprocess.STDOUT)
        packaged_smoke = verify_smoke(smoke_output / 'packaged')
    python_dist = ROOT / 'build' / 'python-dist'
    if python_dist.exists():
        shutil.rmtree(python_dist)
    # Build requirements must already be installed by the locked development environment.
    run([sys.executable, '-m', 'build', '--no-isolation', '--outdir', str(python_dist)])
    wheel = next(python_dist.glob('*.whl'))
    validate_sdist(next(python_dist.glob('*.tar.gz')))
    with zipfile.ZipFile(wheel) as distribution:
        if 'shopshift/__main__.py' not in distribution.namelist():
            raise RuntimeError('Wheel is missing the application entry point')
    wheel_smoke = None
    if test_wheel:
        with tempfile.TemporaryDirectory(prefix='shopshift-wheel-') as directory:
            environment_path = Path(directory)
            venv.EnvBuilder(with_pip=True).create(environment_path)
            python = environment_path / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
            constraints = environment_path / 'runtime-constraints.txt'
            constraints.write_text('\n'.join(f"{item['name']}=={item['version']}"
                                             for item in manifest['packages']
                                             if item['name'].lower() not in {'shopshift', 'pyinstaller'}) + '\n')
            run([str(python), '-m', 'pip', 'install', '--constraint', str(constraints), str(wheel)],
                cwd=environment_path)
            run([str(python), '-I', '-m', 'shopshift', '--smoke-test', str(smoke_output / 'wheel')],
                cwd=environment_path, timeout=180)
            wheel_smoke = verify_smoke(smoke_output / 'wheel')
    for distribution in python_dist.iterdir():
        shutil.copyfile(distribution, output / distribution.name)
    # Installed package notices and native dependency versions may differ by OS.
    # Keep each inventory paired with its platform's archive/checksum manifest.
    sources_archive = output / f'{stem}-corresponding-sources.tar.gz'
    with tarfile.open(sources_archive, 'w:gz', compresslevel=1) as target:
        for source in manifest['sources']:
            target.add(source_cache / source['file'], arcname=f'upstream/{source["file"]}')
        target.add(license_root / 'manifest.json', arcname='manifest.json')
        target.add(ROOT / 'THIRD_PARTY_NOTICES.md', arcname='THIRD_PARTY_NOTICES.md')
        target.add(ROOT / 'docs' / 'DISTRIBUTION.md', arcname='DISTRIBUTION.md')
    sha, dirty = identity()
    if os.environ.get('GITHUB_SHA') and (sha != os.environ['GITHUB_SHA'] or dirty):
        raise RuntimeError('CI release source does not match its clean workflow commit')
    report = {'version': version(), 'source': SOURCE_URL, 'commit': sha, 'working_tree_dirty': dirty,
              'platform': platform.platform(), 'python': sys.version.split()[0], 'architecture': arch,
              'developer_signed': False, 'notarized': False,
              'macos_signature': 'ad-hoc only' if sys.platform == 'darwin' else None,
              'seconds': round(time.monotonic() - started, 2),
              'bundle': bundle_audit, 'packaged_smoke': packaged_smoke, 'wheel_smoke': wheel_smoke,
              'external_system_libraries': json.loads(
                  (ROOT / 'build' / 'external-system-libraries.json').read_text()),
              'dependencies': [{'name': item['name'], 'version': item['version']} for item in manifest['packages']]}
    report_path = output / f'{stem}-build-report.json'
    report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    shutil.copyfile(ROOT / 'THIRD_PARTY_NOTICES.md', output / 'THIRD_PARTY_NOTICES.md')
    sums = []
    for file in sorted(output.iterdir()):
        if file.is_file() and not file.name.startswith('SHA256SUMS'):
            sums.append(f'{digest(file)}  {file.name}')
    (output / f'SHA256SUMS-{system}-{arch}.txt').write_text('\n'.join(sums) + '\n')
    print(json.dumps({'archive': archive.name, 'compressed_bytes': archive.stat().st_size,
                      'unpacked_bytes': bundle_audit['unpacked_bytes'], 'commit': sha,
                      'dirty': dirty, 'report': str(report_path)}, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'release')
    parser.add_argument('--test-wheel', action='store_true', help='Install wheel in a clean environment and smoke test')
    parser.add_argument('--skip-download', action='store_true', help='Reuse and verify the generated notice/source cache')
    arguments = parser.parse_args()
    build(arguments.output.resolve(), test_wheel=arguments.test_wheel, skip_download=arguments.skip_download)
