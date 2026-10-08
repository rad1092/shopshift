"""Keep desktop QtGui plugins; omit optional PDF/QML/virtual-keyboard modules."""
from pathlib import PurePosixPath

from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)


def required_plugin(source):
    path = PurePosixPath(source.replace('\\', '/'))
    if 'plugins' not in path.parts:
        return True
    family = path.parts[path.parts.index('plugins') + 1]
    if family in {'platforms', 'platformthemes', 'styles', 'xcbglintegrations',
                  'wayland-decoration-client', 'wayland-graphics-integration-client',
                  'wayland-shell-integration', 'egldeviceintegrations'}:
        return True
    if family == 'platforminputcontexts':
        return 'virtualkeyboard' not in path.name.lower()
    if family == 'imageformats':
        return any(name in path.name.lower() for name in ('qgif.', 'qico.', 'qjpeg.', 'qicns.',
                                                        'qmacheif.', 'qmacjp2.'))
    return False


binaries = [(source, target) for source, target in binaries if required_plugin(source)]
