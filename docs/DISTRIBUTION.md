# Installation, verification, and rebuilding

ShopShift is an offline desktop app for one planner. Portable releases need no
Python installation, administrator access, account, or local server. Extract the
whole archive; moving only the executable will break its libraries. Projects are
saved where you choose, outside the app directory. Back up project files before
replacing the app directory during an upgrade.

| Release | Install / start | Tested CI environment |
| --- | --- | --- |
| macOS arm64 `.tar.gz` | Extract in Finder or with `tar -xzf`; move `ShopShift.app` to your Applications folder; open the app | macOS 14 Apple Silicon |
| Windows x86_64 `.zip` | Extract all; open `ShopShift/ShopShift.exe` | Windows Server 2022 GitHub runner |
| Linux x86_64 `.tar.gz` | `tar -xzf`; run `ShopShift/ShopShift` | Ubuntu 24.04 with X11/Xvfb |

CI environments are evidence of those configurations, not a claim that every
Windows/Linux distribution is covered. Linux requires desktop system libraries
including GL/EGL, xkbcommon, and XCB; it is not a statically linked universal Linux
binary. No Intel macOS or Linux arm64 package is supplied by this matrix.

On Ubuntu 24.04, the desktop prerequisites used by CI can be installed with:

```sh
sudo apt-get install libegl1 libopengl0 libgl1 libdbus-1-3 libfontconfig1 libfreetype6 libglib2.0-0t64 libcups2t64 libx11-xcb1 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-xinerama0 libxcb-xfixes0 fonts-noto-cjk
```

Linux libraries originating in `/lib` or `/usr/lib` remain system dependencies;
they are not redistributed in ShopShift. The bundle and build report record their
names in `external-system-libraries.json` / `external_system_libraries`. Qt and
other libraries from the pinned Python wheels remain bundled. Install prerequisites
once using your distribution's package manager; running the app uses no network.

**These releases are not Developer ID signed, Authenticode signed, or notarized.**
macOS binaries have only a local ad-hoc signature, required by the platform; it
does not identify a trusted publisher. Gatekeeper/SmartScreen can warn or block
launches. Use the OS's per-app review/open controls if you choose to trust the
verified release, or build from source. Do not disable system security globally.

Download the archive, its build report, and the matching `SHA256SUMS-*.txt` from
[the release](https://github.com/rad1092/shopshift/releases). On macOS/Linux use
`shasum -a 256 <archive>`; on Windows use
`Get-FileHash <archive> -Algorithm SHA256`. Compare the entire hash. Checksums detect
corruption; they are not publisher signatures. The build report identifies the
exact source commit, dependency versions, packaging size, and smoke results.
A report with `working_tree_dirty: true` is a local development build and must not
be represented as an exact-commit release.

## Build and run the same validation

Install Python 3.12.13 and [uv](https://docs.astral.sh/uv/), then in a source checkout:

```sh
uv sync --frozen --extra dev --python 3.12.13
uv run --no-sync pytest -q
uv run --no-sync python -m shopshift --smoke-test build/source-smoke
uv run --no-sync python scripts/build_release.py --test-wheel
```

On a headless Linux desktop, prefix GUI commands with `xvfb-run -a`. Build each
platform on that platform; PyInstaller is not used as a cross-compiler. The helper
fetches upstream dependency source/notices, freezes the app with one process,
creates the archive, extracts it into a new temporary directory, launches that
installed copy, and checks JSON plus a screenshot. It also builds wheel/sdist and,
with `--test-wheel`, installs the wheel into a clean virtual environment and runs
its smoke test. The app runtime never downloads dependencies.

`release/` contains packages, corresponding sources, build reports, and checksum
files. `build/release-smoke/` contains execution evidence. The GitHub workflow
uploads these separately, runs at most two operating systems concurrently, and
does not publish a release automatically. Tests and packaged smoke must succeed
on the exact release commit before the resulting artifacts are published.

The bundled `licenses/manifest.json` lists every runtime Python dependency and
native source/notice download. Full corresponding sources and license texts are
also shipped in `ShopShift-<version>-<os>-<arch>-corresponding-sources.tar.gz`;
preserve the source asset matching each desktop archive on mirrors. The per-OS
manifest includes the dependencies from that platform's build. Download receipts
verify a cached archive has not changed.
Source URLs and hashes are recorded; upstream downloads use HTTPS. The helper
refuses an unaudited Qt/OR-Tools version, rather than silently reusing an old native
license inventory. A dependency update requires reviewing that inventory again.

## Replace or rebuild LGPL libraries

You are allowed to modify Qt/PySide, relink the application, and reverse engineer
it for debugging those modifications. The application imposes no restriction on
these rights and performs no anti-tamper or library-signature checks. Rebuilding
from the published MIT source is supported and avoids binary ABI ambiguity.

For a compatible replacement, close ShopShift, copy the app directory, and replace
the matching Qt/PySide/Shiboken shared libraries and plugins inside that copy:

- Windows/Linux: `ShopShift/_internal/PySide6`, plus Shiboken libraries under
  `_internal`. Preserve directory names and all dependencies.
- macOS: `ShopShift.app/Contents/Frameworks` (including its PySide6/Qt framework
  tree) and the matching `Contents/Resources` links. Preserve symlinks and framework
  structure. After replacing code, ad-hoc sign your own copy with
  `codesign --force --deep --sign - ShopShift.app` if required by macOS.

Use the same architecture, Python ABI, and compatible Qt/PySide ABI. Test your
copy with `--smoke-test <empty-directory>` and your own representative projects.
If ABI compatibility is uncertain, rebuild Qt/PySide following their included
source instructions, install those builds in a new development virtual
environment, and rerun the published PyInstaller specification (after collecting
notices for your modified dependencies). Native library load paths are rewritten
by PyInstaller, so a source rebuild is usually easier than manual replacement.

Relevant upstream documentation: [PyInstaller spec files](https://pyinstaller.org/en/stable/spec-files.html),
[symbolic-link distribution requirements](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#requirements-imposed-by-symbolic-links-in-frozen-application),
[Qt for Python source builds](https://doc.qt.io/qtforpython-6/building_from_source/index.html).

## 한국어 설치 요약

배포 압축 전체를 풀고 macOS에서는 `ShopShift.app`, Windows에서는
`ShopShift.exe`, Linux에서는 `ShopShift`를 실행합니다. Python이나 서버 설치는
필요하지 않습니다. 프로젝트 파일은 앱 폴더 밖에 저장하고 별도로 백업하세요.
이 배포본은 개발자 인증 서명 및 공증이 없으므로 운영체제 경고가 나타날 수
있습니다. 제공된 SHA-256 값과 소스 커밋을 확인하고, 시스템 보안을 전체 해제하지
마세요. 라이선스와 수정 가능한 Qt/PySide 라이브러리는 배포본에 함께 들어 있습니다.
