# Changelog

## 0.2.0 — unreleased

- Times on screen read like a shop calendar, *Mon 10/05 08:00* (Korean *10/05 (월) 08:00*); the time zone is shown once in the header. Editing fields still take ISO times with offsets.
- Lateness, overlaps and early starts are worded in minutes and hours (*finishes 30 min after its due time*, *납기보다 30분 늦게 끝남*) on screen and in validator messages. Issues carry `amount` and `subject` for this; CSV columns stay in seconds.
- Choosing 한국어 switches the whole window: menus, labels, combo boxes, table contents, issue list and dialogs. No more two-language strings on one line.
- Late bars are orange; the operations table colors late states.
- The timeline starts at the first working hour instead of midnight, and Day detail fits the first working day to the visible width.
- Two priority sliders, Due dates and Finish early, weight the suggestion objective (`suggest(..., lateness_weight, makespan_weight)`, 0–10).
- `AGENTS.md` is now `CONTRIBUTING.md`.

## 0.1.0 — 2026-10-08

Initial bounded release: local production planning with ERP CSV/XLSX column mappings, stable-ID reimport preserving decisions, resource availability, manual locks, conflict explanations, OR-Tools suggestions with independent validation, scenario comparison, undo, daily exports, local projects and backups. English and Korean major controls and quickstarts. Native archives are unsigned and not notarized; see distribution and verification documentation.

Pre-release review fixes include shared persistence admission before desktop mutations, refusal of compact backups that cannot be saved canonically, and separate test/smoke CI steps so a Windows test failure cannot be hidden by a subsequent successful command.
