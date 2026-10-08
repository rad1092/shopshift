"""Desktop entry point and deterministic packaged smoke test."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description="ShopShift offline scheduling workbench")
    parser.add_argument("project", nargs="?", help="Project JSON file to open")
    parser.add_argument("--version", action="version", version="ShopShift 0.1.0")
    parser.add_argument("--smoke-test", metavar="DIRECTORY", help="Run packaged GUI smoke and save evidence")
    parser.add_argument("--demo", action="store_true", help="Open the synthetic shop example")
    args = parser.parse_args(argv)
    from PySide6.QtWidgets import QApplication, QMessageBox

    from .demo import demo_project
    from .gui import MainWindow
    from .storage import load_project

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("ShopShift")
    app.setOrganizationName("ShopShift")
    if args.smoke_test:
        from .smoke import run_smoke
        return run_smoke(app, Path(args.smoke_test))
    project = None
    if args.project:
        try:
            project = load_project(Path(args.project))
        except (ValueError, OSError) as exc:
            QMessageBox.critical(None, "Cannot open project", str(exc))
            return 1
    elif args.demo:
        project = demo_project()
    window = MainWindow(project)
    if args.project:
        window.set_project(project, Path(args.project))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
