# Third-party notices

ShopShift's own code is MIT-licensed. Binary releases also contain independent
software under the licenses described below. Their copyright and license terms
remain in force; the MIT license does not replace them.

**ShopShift uses Qt and PySide6 under LGPL version 3.** You may inspect, debug,
reverse engineer to debug your modifications, replace, and relink these libraries.
ShopShift imposes no additional restriction on those rights. Qt/PySide source code
is not modified by ShopShift. PyInstaller adjusts binary load paths when packaging.

Each desktop bundle contains `licenses/manifest.json`, exact installed Python
package metadata, full license/copyright notices, and notices from the upstream
native dependency source archives. The manifest records package versions, source
URLs, SHA-256 hashes, and archive sizes. PySide's wheel does not itself include all
license texts, so the release helper obtains them from the matching official sources.
Linux distro libraries from `/lib` and `/usr/lib` are not bundled; the package
records those external dependencies in `external-system-libraries.json`.

The accompanying `ShopShift-<version>-<os>-<arch>-corresponding-sources.tar.gz` release asset
provides Qt 6.11.2 (qtbase and qtwayland), PySide6/Shiboken6 6.11.2, OR-Tools 9.15,
its native dependency sources (including COIN-OR and Eigen), and CPython sources.
The OR-Tools source archive contains the dependency build definitions and patches.
The manifest records the exact sources included. Download the asset matching your
desktop archive's OS and architecture from the
[same ShopShift release](https://github.com/rad1092/shopshift/releases) at no charge.
Keep it available wherever you redistribute a binary. Source archives include
components that are not used; their presence does not imply those components ship
as executable code in the app.

| Component | Principal license / role |
| --- | --- |
| CPython | PSF License and included notices; interpreter |
| PySide6 Essentials, Shiboken6, Qt Core/Gui/Widgets/PrintSupport/Test and desktop platform support | LGPL-3.0 (or upstream alternative licenses); GUI, print, smoke QA |
| OR-Tools | Apache-2.0; CP-SAT scheduling suggestions |
| COIN-OR CoinUtils, Osi, Clp, Cgl, Cbc | EPL-1.0/EPL-2.0 notices as included; native libraries shipped by the official OR-Tools wheel |
| Eigen | MPL-2.0; native OR-Tools dependency |
| Abseil, RE2, Protobuf, pybind11, pybind11-abseil/protobuf, SCIP, SoPlex, HiGHS, Boost | Their included Apache/BSD/MIT/Boost notices; OR-Tools native dependencies |
| NumPy, pandas, dateutil, six, immutabledict, absl-py, protobuf, typing_extensions | Their included BSD/MIT/Apache notices; OR-Tools Python dependencies |
| openpyxl, et_xmlfile, defusedxml | MIT/PSF notices as included; spreadsheet input |
| tzdata | Apache-2.0 and public-domain IANA data; explicit time zones |
| PyInstaller bootloader | GPL with the upstream bootloader distribution exception; packaging |
| Qt and CPython embedded third-party libraries | Their included notices (for example FreeType, HarfBuzz, JPEG, PNG, zlib, PCRE2, ICU, Expat, OpenSSL, libffi, bzip2, liblzma) |

Only the required Qt desktop modules/plugins are bundled. Qt Designer, Linguist,
Qt WebEngine, Qt PDF, QML, Qt Quick, and the virtual keyboard are excluded. The
presence of GPL license texts in upstream source archives does not claim that
GPL-only tools are part of the ShopShift runtime.

The portable layout intentionally keeps Qt's native libraries separate from the
launcher. See [distribution and replacement instructions](docs/DISTRIBUTION.md).
The entire application source and rebuild scripts are available at
<https://github.com/rad1092/shopshift>.

Authoritative references: [Qt licensing obligations](https://www.qt.io/development/open-source-lgpl-obligations),
[Qt for Python licensing](https://doc.qt.io/qtforpython-6/licenses.html),
[OR-Tools license](https://github.com/google/or-tools/blob/v9.15/LICENSE), and
[PyInstaller license / exception](https://pyinstaller.org/en/stable/license.html).
