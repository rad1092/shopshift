# A replaceable-library one-directory bundle, never a self-extracting executable.
import sys
import tomllib
import json
from importlib.metadata import packages_distributions
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata

root = Path(SPECPATH)
release_version = tomllib.loads((root / 'pyproject.toml').read_text())['project']['version']
license_root = root / 'build' / 'release-licenses'
if not (license_root / 'manifest.json').is_file():
    raise RuntimeError('Run scripts/build_release.py; generated dependency notices are required.')

metadata = copy_metadata('shopshift', recursive=True)
datas = metadata + collect_data_files('tzdata') + [
    (str(license_root), 'licenses'),
    (str(root / 'THIRD_PARTY_NOTICES.md'), '.'),
    (str(root / 'LICENSE'), '.'),
]
for name in ['README.md', 'CHANGELOG.md', 'PRIVACY.md']:
    if (root / name).is_file():
        datas.append((str(root / name), '.'))
datas.append((str(root / 'docs'), 'docs'))

analysis = Analysis(
    [str(root / 'scripts' / 'frozen_entry.py')],
    pathex=[str(root / 'src')],
    binaries=collect_dynamic_libs('ortools'),
    datas=datas,
    hiddenimports=['PySide6.QtPrintSupport', 'PySide6.QtTest', 'ortools.sat.python.cp_model',
                   'google.protobuf', 'defusedxml.ElementTree'],
    hookspath=[str(root / 'scripts' / 'hooks')],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'matplotlib', 'tkinter', 'IPython',
              'pytest', '_pytest', 'hypothesis', 'setuptools', 'pip', 'pygments',
              'numpy.f2py', 'pandas.tests',
              'pluggy', 'iniconfig', 'trove_classifiers',
              'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuickWidgets',
              'PySide6.QtPdf', 'PySide6.QtWebEngineCore', 'PySide6.QtNetwork',
              'PySide6.QtSql', 'PySide6.QtMultimedia'],
    noarchive=False,
)
# Distro desktop libraries stay with the host's package manager. Their exact
# build and source/license inventory is outside our audited wheel inventory.
# Resolve symlinks before checking: wheel/uv libraries remain bundled even when
# the checkout itself is linked elsewhere. Keep the CPython runtime in all cases.
external_system_libraries = []
if sys.platform.startswith('linux'):
    system_roots = {Path(path).resolve() for path in ('/lib', '/lib64', '/usr/lib', '/usr/lib64')}
    retained_binaries = []
    for target, source, kind in analysis.binaries:
        origin = Path(source).resolve()
        is_system = any(origin.is_relative_to(directory) for directory in system_roots)
        if is_system and not origin.name.startswith('libpython'):
            external_system_libraries.append(target)
        else:
            retained_binaries.append((target, source, kind))
    analysis.binaries = retained_binaries
external_manifest = root / 'build' / 'external-system-libraries.json'
external_manifest.write_text(json.dumps(sorted(set(external_system_libraries)), indent=2) + '\n')
analysis.datas.append(('external-system-libraries.json', str(external_manifest), 'DATA'))

# Fail if an optional build/test dependency slipped into frozen Python modules
# without its distribution notice being accounted for.
normalize = lambda value: value.lower().replace('_', '-').replace('.', '-')
notices = json.loads((license_root / 'manifest.json').read_text())
covered = {normalize(item['name']) for item in notices['packages']}
module_distributions = packages_distributions()
actual = {normalize(distribution) for module, source, kind in analysis.pure
          for distribution in module_distributions.get(module.split('.')[0], [])}
if actual - covered:
    raise RuntimeError(f'Bundled Python distributions lack notices: {sorted(actual - covered)}')

# Prevent accidental redistribution of Qt development utilities/GPL-only plugins.
for target, source, kind in analysis.binaries:
    if any(part in target.lower() for part in ('virtualkeyboard', 'qtwebengine', 'qtpdf', 'qtquick', 'qtqml')):
        raise RuntimeError(f'Unexpected optional Qt runtime: {target}')

archive = PYZ(analysis.pure)
exe = EXE(archive, analysis.scripts, [], exclude_binaries=True, name='ShopShift',
          debug=False, strip=False, upx=False, console=sys.platform.startswith('linux'),
          argv_emulation=False, target_arch=None, codesign_identity=None, entitlements_file=None)
collection = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False, name='ShopShift')
if sys.platform == 'darwin':
    app = BUNDLE(collection, name='ShopShift.app', icon=None,
                 bundle_identifier='io.github.rad1092.shopshift',
                 info_plist={'CFBundleShortVersionString': release_version,
                             'CFBundleVersion': release_version,
                             'NSHighResolutionCapable': True})
