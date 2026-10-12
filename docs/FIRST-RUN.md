# First plan, saved result, and next-day reimport

Use the release app's synthetic demo or run `shopshift --demo` from your source
installation. No ERP connection is required. This exercise is for a planner who
already has an export, fixed resources and explicit working calendars.

1. Request a suggestion in the demo. Inspect the validation results and late
   operations before using the plan. A solver status describes this bounded
   model, not a promise that the real shop can deliver the work.
2. Select a scheduled operation, record its ID and start, and lock it. Save the
   project in a new folder, close it, and reopen the saved `.shopshift` file.
3. Import the same export again with the same operation IDs. The start and lock
   should survive; omitted rows remain because an export may be partial.
4. Export a daily CSV and printable HTML, then open both. They are reviewable
   work lists; they are not files for writing back into the ERP.

For your own first import, start with a copy containing only a few operations.
Map `id`, `job`, `machine` and `run`, and explicitly select minutes, hours or
seconds. Stable operation IDs are essential. Review the new resources' default
weekday calendars before solving. See [the exact import contract](IMPORTS.md)
and the synthetic `examples/erp_day1.csv` and `erp_day2.csv` in the checkout.

## When the result is surprising

| Symptom | Next step |
| --- | --- |
| `python` not found or unsupported Python | Use a supported 3.12/3.13 executable, or the runtime-included release. |
| `shopshift` not found | Invoke the executable inside `.venv` as shown in the README. |
| No feasible suggestion | Check locks, predecessors and continuous availability. Operations cannot cross lunch breaks or split automatically. |
| Duplicate operations after reimport | Check whether upstream IDs changed. A renamed ID is a new operation. |
| Import rejects dates | Supply a full local date/time in the project zone or an explicit UTC offset; date-only cells are unsupported. |
| Linux app does not start | Install the X11/XCB runtime libraries in [Distribution](DISTRIBUTION.md); extracting the app alone does not supply system libraries. |

## Reproduced release check

On 2026-10-12, the public `ShopShift-0.1.0-macos-arm64.tar.gz` checksum was verified
and the extracted app's `--smoke-test` ran in a native macOS 27.0.1 arm64 window.
It passed solver/independent-validator agreement, repeat-import lock retention,
save/reopen/backup, CSV/HTML output, real timeline drag/undo and Korean controls.
The source suite also passed 241 tests. This is synthetic workflow evidence;
it does not measure real shop adoption or manually validate every OS dialog.
