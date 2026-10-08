# Release verification

The source suite currently has **202 passing tests** on macOS 27.0.1 arm64 with Python 3.12.13. All source, test and release scripts pass Ruff. The independent acceptance review and realistic workload measurements are in [QA_REVIEW.md](QA_REVIEW.md); repeated import and official OR-Tools comparisons are in [FIT.md](FIT.md).

## Native GUI

On 2026-10-08, 13 GUI tests passed against the actual macOS Cocoa platform in 1.91 seconds. They exercise real QTest drag, keyboard activation, start/lock editing, undo, saved/reopened scenarios, import review cancellation, failed imports/saves, close/save cancellation, calendar gaps/overnight/DST rejection, safe retirement, solver worker review, rejected fake solver success and Korean controls. This was not an offscreen-only run.

A separate Cocoa launch completed the packaged-smoke workflow in 0.698 seconds: demo solve, independent validation, repeated import preserving locks, save/reload/backup, CSV/HTML, native window and undo. See [native-smoke.json](native-smoke.json) and [Mac screenshot](screenshots/macos-workbench.png).

The external CUA app-selection call failed to return and was stopped. It provided no accessibility or manual-use evidence. Native Qt tests continued independently. Controls expose accessible names and labels and offer keyboard equivalents, but no screen-reader user session or human planner usability study has been performed. Korean covers major controls and quickstart; diagnostic details remain partly English.

## Cross-platform release gate

The [Test and package workflow](https://github.com/rad1092/shopshift/actions/workflows/ci.yml) runs Linux X11/Xvfb, Windows and macOS. Each job runs tests, source GUI smoke, builds a portable archive, extracts it into a fresh directory, launches that packaged executable, installs the wheel into a clean virtual environment, and repeats smoke. Every published build report must identify the same clean source commit as the successful workflow.

Cross-platform results are pending until the workflow on the release commit is green. The GitHub release notes and attached build reports are the authoritative immutable evidence for a published version; do not infer success merely from this workflow definition. Each report includes native library inventory, dependency versions, package size, solver status and smoke checks. Checksums accompany assets. Binary releases are unsigned and not notarized.

## Limits of the evidence

All fixtures are synthetic. Measured runtimes are single local observations, not performance guarantees. The independent oracle checks the defined fixed-resource, nonpreemptive model; it cannot establish material availability or real production readiness. Abrupt-process save tests do not simulate power failure. A feasible solver candidate can have a wide optimality gap and is never applied automatically. No commercial competitor's onboarding time was measured.
