# Bounded product decision

ShopShift is an offline workbench for one planner at a small make-to-order shop that must retain its ERP. It imports copies of operations, reviews calendar/resource/dependency conflicts, preserves manual decisions by stable operation ID, and produces read-only plans for discussion. Nothing is written back to an ERP or machine.

The useful repeated loop is import → review added/changed operations → preserve locks → inspect new conflicts → copy a scenario → request and independently validate a suggestion → review changes → export a daily plan → save → reopen → repeat tomorrow. Stable operation IDs must come from the upstream system. A changed ID represents a new operation. Missing export rows are retained, never assumed cancelled.

## Scheduling model

- Fixed machine, optional fixed operator. Each has an explicit availability calendar.
- One machine and one operator can do one operation at a time. Operator is occupied for the entire operation.
- Setup plus run duration forms a single uninterrupted operation. No splitting across lunch, closed time or another shift.
- Precedence can span jobs. Release is hard; due date is soft. Dates use integer UTC seconds and an IANA display zone. Ambiguous/nonexistent local times require correction or explicit offsets.
- Suggestions use the official OR-Tools CP-SAT engine with one worker and a time limit. Objective: sum of operation tardiness seconds plus schedule makespan seconds, with equal weights. This is not job-priority optimization.
- Manual locks fix start times. Imports preserve starts and locks even when upstream duration or resource changes cause a conflict. Review those conflicts; preservation is not a guarantee of feasibility.
- A separate pure Python validator checks every returned candidate before it can be applied. A solver's successful return alone is insufficient.

## Explicit boundaries

This release does not model material availability, inventory, alternative machines, employee skills, subcontracting, sequence-dependent setup, machine capacity greater than one, multi-planner collaboration, live shopfloor state, or automatic execution. Uncertain durations and frequent breakdowns can make a whiteboard preferable. A feasible mathematical plan is not a production commitment. Correct imported data and a human review remain necessary.

## Acceptance

A usable release must include CSV/XLSX mappings and repeat import review, visible import errors without partial mutations, editable calendars, keyboard equivalent of drag, undo, scenario comparisons, late-operation information, safe save and explicit backup restore, daily exports, Korean quickstart, documented solver status, executable packaged smoke on each supported OS, and independently checked invariant tests.

One standalone application is counted as the product. Its reusable `shopshift.validator.validate` API is an included library, not another product.
