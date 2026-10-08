"""Collect wheel/native notices and exact Qt/OR-Tools dependency sources.

Downloads occur at build time only. No network access is used by ShopShift itself.
Archive bytes are hashed; cached downloads are rechecked against their receipt.
Only notice files are extracted, never archive paths or executable files.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import ssl
import sys
import tarfile
import urllib.request
from importlib import metadata
from pathlib import Path, PurePosixPath

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = 'https://github.com/rad1092/shopshift'
# Audited against the official v9.15 cmake/dependencies/CMakeLists.txt. Archives
# retain upstream patches/build instructions as well as copyleft-covered sources.
ORTOOLS_SOURCES = {
    'or-tools': ('google/or-tools', 'v9.15'),
    'abseil-cpp': ('abseil/abseil-cpp', '20250814.1'),
    'protobuf-native': ('protocolbuffers/protobuf', 'v33.1'),
    're2': ('google/re2', '2025-08-12'),
    'pybind11': ('pybind/pybind11', 'v2.13.6'),
    'pybind11-abseil': ('pybind/pybind11_abseil', 'v202402.0'),
    'pybind11-protobuf': ('pybind/pybind11_protobuf', 'f02a2b7653bc50eb5119d125842a3870db95d251'),
    'highs': ('ERGO-Code/HiGHS', 'v1.12.0'),
    'soplex': ('scipopt/soplex', 'v8.0.0'),
    'scip': ('scipopt/scip', 'v10.0.0'),
    'coinutils': ('Mizux/CoinUtils', 'cmake/2.11.12'),
    'osi': ('Mizux/Osi', 'cmake/0.108.11'),
    'clp': ('Mizux/Clp', 'cmake/1.17.10'),
    'cgl': ('Mizux/Cgl', 'cmake/0.60.9'),
    'cbc': ('Mizux/Cbc', 'cmake/2.10.12'),
    'zlib': ('madler/zlib', 'v1.3.1'),
}


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def download(url: str, target: Path) -> dict:
    receipt = target.with_suffix(target.suffix + '.receipt.json')
    if target.exists() and receipt.exists():
        record = json.loads(receipt.read_text())
        if record['url'] == url and record['sha256'] == digest(target):
            return record
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + '.partial')
    print(f'Downloading source/notice: {target.name}', flush=True)
    try:
        with urllib.request.urlopen(url, timeout=60) as response, partial.open('wb') as output:
            shutil.copyfileobj(response, output)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    record = {'file': target.name, 'url': url, 'sha256': digest(target), 'bytes': target.stat().st_size}
    receipt.write_text(json.dumps(record, indent=2) + '\n')
    return record


def notice_name(path: PurePosixPath) -> bool:
    lower = path.name.lower()
    return (any(word in lower for word in ('license', 'licence', 'copying', 'copyright', 'notice', 'authors'))
            or 'licenses' in [part.lower() for part in path.parts]
            or lower in {'qt_attribution.json', 'qt_attribution_test.json'})


def archive_notices(archive: Path, target: Path) -> int:
    count = 0
    with tarfile.open(archive, 'r:*') as source:
        members = source.getmembers()
        names = {member.name: member for member in members}
        selected = {member.name for member in members if member.isfile()
                    and notice_name(PurePosixPath(member.name))}
        # Qt's attribution records sometimes point at README or source files
        # whose names do not contain "license".
        for member in members:
            if member.isfile() and member.name.endswith('qt_attribution.json'):
                try:
                    records = json.load(source.extractfile(member))
                    if isinstance(records, dict):
                        records = [records]
                    for record in records:
                        for name in record.get('LicenseFile', '').split():
                            path = str(PurePosixPath(member.name).parent / name)
                            if path in names:
                                selected.add(path)
                except (ValueError, TypeError, AttributeError):
                    pass
        for name in sorted(selected):
            member = names[name]
            parts = PurePosixPath(name).parts[1:]
            if not member.isfile() or not parts or '..' in parts or member.size > 2_000_000:
                continue
            output = target.joinpath(*parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(member) as stream, output.open('wb') as out:
                shutil.copyfileobj(stream, out)
            count += 1
    if not count:
        raise RuntimeError(f'No license notices found in {archive.name}')
    return count


def runtime_distributions() -> list:
    pending, seen, result = ['shopshift'], set(), []
    while pending:
        name = pending.pop()
        canonical = canonicalize_name(name)
        if canonical in seen:
            continue
        seen.add(canonical)
        dist = metadata.distribution(name)
        result.append(dist)
        for text in dist.requires or []:
            requirement = Requirement(text)
            if requirement.marker is None or requirement.marker.evaluate({'extra': ''}):
                pending.append(requirement.name)
    # The bootloader is redistributed and has an explicit distribution exception.
    result.append(metadata.distribution('pyinstaller'))
    # Some native/data hooks retain packaging.version at runtime.
    result.append(metadata.distribution('packaging'))
    return sorted(result, key=lambda d: d.metadata['Name'].lower())


def collect(output: Path, cache: Path) -> dict:
    qt_version = metadata.version('PySide6-Essentials')
    ortools_version = metadata.version('ortools')
    if ortools_version != '9.15.6755' or qt_version != '6.11.2':
        raise RuntimeError('Native source inventory audited for OR-Tools 9.15.6755 / Qt 6.11.2; update it first.')
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    packages = []
    for dist in runtime_distributions():
        name = canonicalize_name(dist.metadata['Name'])
        destination = output / 'python-packages' / name
        destination.mkdir(parents=True)
        # METADATA preserves authors, homepage, license expression and classifiers.
        (destination / 'METADATA.txt').write_text(dist.read_text('METADATA') or '', encoding='utf-8')
        files = []
        for file in dist.files or []:
            relative = PurePosixPath(str(file).replace('\\', '/'))
            if '..' in relative.parts or not notice_name(relative):
                continue
            source = Path(dist.locate_file(file))
            if source.is_file():
                target = destination.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                files.append(str(target.relative_to(output)))
        packages.append({'name': dist.metadata['Name'], 'version': dist.version, 'license_files': files,
                         'license_expression': dist.metadata.get('License-Expression'),
                         'project_urls': dist.metadata.get_all('Project-URL') or []})
    sources = []
    archives = []
    major_minor = '.'.join(qt_version.split('.')[:2])
    for module in ('qtbase', 'qtwayland'):
        name = f'{module}-everywhere-src-{qt_version}.tar.xz'
        url = f'https://download.qt.io/official_releases/qt/{major_minor}/{qt_version}/submodules/{name}'
        archives.append((module, url, name))
    pyside = f'pyside-setup-everywhere-src-{qt_version}.tar.xz'
    archives.append(('pyside-shiboken', f'https://download.qt.io/official_releases/QtForPython/pyside6/'
                     f'PySide6-{qt_version}-src/{pyside}', pyside))
    for name, (repository, revision) in ORTOOLS_SOURCES.items():
        archives.append((name, f'https://codeload.github.com/{repository}/tar.gz/{revision}',
                         f'{name}-{revision.replace("/", "-")}.tar.gz'))
    archives.extend([
        ('eigen', 'https://gitlab.com/libeigen/eigen/-/archive/3.4.0/eigen-3.4.0.tar.gz', 'eigen-3.4.0.tar.gz'),
        ('bzip2', 'https://sourceware.org/pub/bzip2/bzip2-1.0.8.tar.gz', 'bzip2-1.0.8.tar.gz'),
        ('cpython', f'https://www.python.org/ftp/python/{sys.version.split()[0]}/'
                    f'Python-{sys.version.split()[0]}.tar.xz', f'Python-{sys.version.split()[0]}.tar.xz'),
    ])
    for name, url, filename in archives:
        path = cache / filename
        record = download(url, path)
        record['component'] = name
        record['notice_count'] = archive_notices(path, output / 'native' / name)
        sources.append(record)
    extra_notices = {
        'boost-1.87.0.txt': 'https://raw.githubusercontent.com/boostorg/boost/boost-1.87.0/LICENSE_1_0.txt',
        f'openssl-{ssl.OPENSSL_VERSION.split()[1]}.txt':
            f'https://raw.githubusercontent.com/openssl/openssl/openssl-{ssl.OPENSSL_VERSION.split()[1]}/LICENSE.txt',
        'libffi.txt': 'https://raw.githubusercontent.com/libffi/libffi/v3.4.6/LICENSE',
        'xz-liblzma.txt': 'https://raw.githubusercontent.com/tukaani-project/xz/v5.8.1/COPYING',
        'xz-0BSD.txt': 'https://raw.githubusercontent.com/tukaani-project/xz/v5.8.1/COPYING.0BSD',
    }
    for filename, url in extra_notices.items():
        record = download(url, cache / filename)
        shutil.copyfile(cache / filename, output / filename)
        sources.append(record)
    manifest = {'application_source': SOURCE_URL, 'python': sys.version.split()[0],
                'packages': packages, 'sources': sources,
                'native_source_basis': 'OR-Tools v9.15 dependency declarations and Qt 6.11.2 source distributions',
                'modifications': 'No local dependency source changes; PyInstaller adjusts binary load paths.'}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


if __name__ == '__main__':
    collect(ROOT / 'build' / 'release-licenses', ROOT / 'build' / 'upstream-sources')
