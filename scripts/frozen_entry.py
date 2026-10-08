"""PyInstaller entry point; absolute import also works outside the source tree."""
import multiprocessing

multiprocessing.freeze_support()

from shopshift.__main__ import main  # noqa: E402

if __name__ == '__main__':
    raise SystemExit(main())
