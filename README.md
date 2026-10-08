# ShopShift

**Keep the ERP. Review tomorrow's shop plan offline.**

ShopShift is a desktop scheduling workbench for one planner at a small shop. Import a daily CSV/XLSX export, preserve manual starts and locks by stable operation ID, see why a plan conflicts, compare a scenario, and print or export a daily work list. The app has no account, server, telemetry, ERP write access or machine control.

This is a bounded first release, not a replacement ERP. It is useful when fixed machines, fixed operators, precedence and explicit calendars describe your planning problem. See [product limits](docs/PRODUCT.md) and the [evidence behind the scope](docs/FIT.md).

## Get started

Download an archive for your operating system from [Releases](https://github.com/rad1092/shopshift/releases). Extract the whole archive before launching. macOS archives contain `ShopShift.app`; Windows/Linux archives contain a `ShopShift` folder with its executable and supporting libraries. Binaries are unsigned and not notarized. Requirements, verification and library replacement instructions are in [Distribution](docs/DISTRIBUTION.md).

Or install from source with Python 3.12 or 3.13:

```sh
python -m venv .venv
# Activate .venv using the command for your operating system.
python -m pip install .
shopshift --demo
```

For reproducible development with [uv](https://docs.astral.sh/uv/):

```sh
uv sync --locked --extra dev
uv run shopshift --demo
uv run pytest
```

[한국어 빠른 시작](docs/QUICKSTART.ko.md) · [Import format](docs/IMPORTS.md) · [Validator API](docs/API.md) · [Privacy](docs/PRIVACY.md)

## Daily workflow

1. Create a project with a time zone and planning horizon, or open the synthetic demo.
2. Import the ERP export. Map operation ID, job, machine and run duration; optionally map operator, setup, predecessors, release, due and label. Choose the duration unit.
3. Review new, changed and retained rows. New resources start with weekday 08:00–12:00 / 13:00–17:00 availability. Edit those calendars to match the shop.
4. Request a suggestion or place tasks manually. Drag a task or use its edit controls; lock committed starts. Undo is available.
5. Review conflicts and late operations. Copy a scenario before exploring alternatives, and compare the resulting times.
6. Export the selected day's CSV/printable HTML or print the plan, then save the project.
7. Tomorrow, import the next export using the saved mapping. Existing starts and locks survive in every scenario. Changed durations/resources can create conflicts that need review. Missing rows are retained because an export may be partial.

Suggestions use official OR-Tools CP-SAT, one worker and a time budget. Every candidate is checked again by an independent validator. The objective minimizes total per-operation tardiness plus makespan in seconds, with equal weights. Optimality is only for that model and objective. Status and review are explicit; no result becomes a production commitment automatically.

## Boundaries

One operation runs continuously through setup and run time and reserves its assigned machine and optional operator for the entire duration. It cannot cross calendar holes or be automatically split. The model excludes material/inventory constraints, alternate machines, employee skills, sequence-dependent setup, subcontracting, live machine state and multiple planners. Uncertain work may still be easier to manage on a whiteboard.

Projects/backups are local, unencrypted JSON. Previous saves are retained as `.bak`. Read-only CSV/HTML snapshots are intended for sharing or discussion and can become stale. See [Privacy](docs/PRIVACY.md).

## Development and verification

```sh
uv run ruff check .
QT_QPA_PLATFORM=offscreen uv run pytest
uv run shopshift --smoke-test artifacts/smoke
uv run python scripts/comparison_ortools.py
```

Qt offscreen is optional on a desktop and useful in headless CI. Release builds run tests and launch the extracted packaged app and an installed wheel on Linux, Windows and macOS. Test evidence and measured scope validation are in `docs/` and workflow artifacts; see [verification notes](docs/VERIFICATION.md).

Application source: MIT. Bundled Qt/PySide libraries use their own licenses, including LGPLv3; third-party dependencies are not relicensed by this repository. Runtime notices and corresponding-source archives accompany binary releases. See [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md).
