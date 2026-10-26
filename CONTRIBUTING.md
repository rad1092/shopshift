# Contributing

These rules also guide AI coding agents working in this repository.

- Work only in this repository; do not modify other projects or global configuration.
- Offline, single-planner scheduling. No telemetry, server, accounts, ERP writes or automatic commitments.
- Python 3.12, PySide6 Essentials, official OR-Tools CP-SAT (one worker), openpyxl.
- Every solver result must pass the independent validator. The engine stores integer UTC seconds with an explicit IANA display zone.
- Everything a planner reads on screen goes through `src/shopshift/i18n.py`: `T(english, korean)` for text, `when()` for times, `duration()` for lengths, `describe()` for issues. Fixed widget texts are registered with `MainWindow._bind` so a language change re-sets them. Do not put two languages on one line.
- Keep synthetic fixtures small; commit benchmark generators and measured logs instead of large dumps.
- A public release may contain only authored code, synthetic data, and redistributable dependencies and licenses.

```sh
uv sync --locked --extra dev
uv run pytest
uv run ruff check src tests
```
