# ERP export contract

Use CSV (UTF-8, optionally with BOM, comma separated) or XLSX (first worksheet). Export **values**, not formulas. The header row must contain unique, nonempty column names. The mapping dialog connects your column names to these fields; mappings and duration units are saved in the project.

| Field | Required | Meaning |
| --- | --- | --- |
| id | yes | Stable upstream operation ID, unique in the file |
| job | yes | Job/order identifier for grouping |
| machine | yes | Fixed machine identifier |
| run | yes | Nonnegative runtime in the selected seconds/minutes/hours unit |
| setup | no | Nonnegative fixed setup duration in the same unit |
| operator | no | Fixed operator identifier, or empty for no operator requirement |
| predecessors | no | Semicolon-separated operation IDs; each must finish before this operation starts |
| release | no | Earliest allowed start in ISO date/time |
| due | no | Soft due date/time; lateness is visible and part of suggestion objective |
| label | no | Description displayed in the workbench |

Setup plus run must be positive and at most 31 days. Fractional values must resolve exactly to whole seconds; `1.5` minutes = 90 seconds. The app rejects silent rounding, negative values, nonfinite numbers and scientific notation. All mapped duration cells use the one selected unit; mixed units cannot be inferred from plain numbers. Do not use localized commas or thousands separators in numeric cells.

Dates must include a date and time, such as `2026-10-05T08:00`, or an explicit offset, such as `2026-10-05T08:00:00+09:00`. An ISO local datetime uses the project IANA time zone. Date-only values and fractional seconds are rejected rather than interpreted or rounded. Ambiguous or nonexistent DST wall times are rejected unless an explicit offset identifies an instant. Calendars and solver arithmetic use UTC seconds so overnight shifts and offset changes remain consistent.

A repeated ID updates mapped fields while preserving every scenario's manual start and lock. Unmapped optional fields retain existing values; mapped blank optional fields clear the corresponding value. Omitted IDs remain in the project. A renamed ID creates a new operation; the old ID remains until explicitly removed. Review dependencies before removing a completed operation.

New resource identifiers receive visible default weekday windows of 08:00–12:00 and 13:00–17:00 in the project time zone. Default calendar generation requires a positive horizon of at most 366 days. These are a starting template, not knowledge of your shop. Review and edit machine/operator calendars before treating any plan as useful.

The importer refuses duplicate IDs, missing required fields, duplicate mappings, formulas, spreadsheet error cells, corrupt ZIP/XML and malformed CSV. It returns a copied project only after the entire import succeeds. Cancellation or any error leaves the original project intact. Missing predecessors/cycles and resource conflicts are explained by the separate validator; imports do not silently repair them.

Bounds: 20 MiB input, 10,000 data rows (including blank rows), 10,000 merged operations, 2,000 combined machine/operator resources, 100,000 total calendar windows, 64 columns, 4,096 characters per cell. Operation, job, machine and operator identifiers must fit on one line of at most 200 characters. XLSX expanded content is limited to 80 MiB and 2,000 ZIP members. Operations above the practical workload demonstrated in verification may load but have slow validation/rendering/solving. The app does not promise scheduling performance up to the ingestion limit.

The daily CSV and printable HTML are read-only work lists, not round-trip ERP exports. A selected day includes overlapping overnight work and all unscheduled operations. Validation warnings accompany the plan. CSV text beginning with spreadsheet formula characters is prefixed with an apostrophe; HTML escapes all user text. Both formats mark the plan as a draft requiring review before production.

See `examples/` for synthetic day-one/day-two exports. There are no real company or employee details in the examples.
