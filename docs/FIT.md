# Fit decision and comparison

**Conditional go for a bounded offline workbench.** The evidence supports trying
one planner's daily ERP-export workflow, not a claim that production scheduling
is an unserved market. ShopShift's proposed value is explicit import reconciliation,
preserved manual starts/locks, and a local file workflow without operating a
database server. Customer adoption, reduced human effort, and willingness to pay
remain untested. This is not a replacement for manufacturing execution software.

## Evidence and counterevidence

A machine-shop poster described a mandated ERP, daily Excel exports, dependencies,
and visual planning. That closely matches the proposed input boundary. A separate
production planner described tedious cascading row changes, then chose Monday.com;
workflow accessibility can matter as much as specialized optimization. These are
two public anecdotes, not interviews, surveys, or demand estimates.
([N1](https://www.reddit.com/r/manufacturing/comments/1ledswu/scheduling_software/),
[N2](https://www.reddit.com/r/manufacturing/comments/1igyxv8/how_do_you_do_your_production_scheduling/))

The Practical Machinist discussion is a useful falsifier: participants describe
whiteboards and job racks as effective where durations are guesses and few jobs
need coordination. ShopShift should lose to those methods when maintaining its
inputs costs more than the conflicts it exposes. A timetable cannot repair poor
estimates or replace communication.
([N3](https://www.practicalmachinist.com/forum/threads/how-do-you-manage-projects-jobs-for-the-shop.441826/))

## Alternatives are substantial

| Alternative | Verified strengths | Why a user might choose ShopShift instead | What has not been established |
| --- | --- | --- | --- |
| Existing spreadsheet / whiteboard | Existing users report useful, flexible workflows; no new migration required. | Explicit cross-resource and precedence checks; reviewable repeated imports. | We have not measured time saved against an expert's spreadsheet. |
| Just Plan It | Finite capacity; drag adjustment; machine and employee planning; shift calendars; Excel/API; reports. [Features](https://www.just-plan-it.com/production-scheduling-features) | A local, single-planner file may suit a user who prefers no hosted account. Vendor states [Azure hosting](https://www.just-plan-it.com/security). | No trial, onboarding time, price comparison, or claim of missing merge/lock features. |
| frePPLe Community | Finite material/capacity planning, CSV/XLSX/API, scenarios, a browser UI. [Editions](https://frepple.com/editions/) | Narrower data model and a desktop process avoid administering a planning server for this bounded use. | No head-to-head planner usability or schedule-quality benchmark. |
| frePPLe Cloud / Enterprise | Broader planning with inventory and interactive planning extensions. [Editions](https://frepple.com/editions/) | Offline preference or the wish to keep scope to exported operations. | Not shown to be less usable, less capable, or more costly overall. |
| MRPeasy | Cloud ERP with scheduling, inventory and manufacturing execution. [Product](https://www.mrpeasy.com/production-scheduling/) | A shop retaining another ERP may prefer a separate planning file. | We did not test coexistence/integration options or claim that migration is mandatory. |
| Official OR-Tools example | Correct compact demonstration of machine exclusivity, precedence, makespan. [Example](https://developers.google.com/optimization/scheduling/job_shop) | ShopShift adds the import/review/persist/export workflow around this established engine. | A sample is not a commercial scheduling competitor; solving its toy instance proves no UX advantage. |

frePPLe is **not cloud-only**. Its documented self-hosted path uses Ubuntu 24
packages or Docker. The container includes a web server and requires a separate
PostgreSQL service; compose deployment is documented. Initial configuration,
database backup and upgrades are real responsibilities, but their labor was not
timed here. An organization already operating this infrastructure may prefer
frePPLe's larger feature set.
([Linux](https://frepple.com/docs/current/installation-guide/linux-binaries.html),
[Docker](https://frepple.com/docs/current/installation-guide/docker-container.html))

frePPLe already has a [guided modeling wizard](https://frepple.com/docs/current/modeling-wizard/index.html)
and [CSV/XLSX import with row error reporting](https://frepple.com/docs/current/user-interface/getting-around/importing-data.html).
Its export format can be reread, and deletion before upload is optional. Therefore
“competitors cannot reimport data” and “competitors have no onboarding” would both
be unjustified claims. ShopShift must demonstrate its own explicit merge contract,
not infer its uniqueness from incomplete competitor documentation.

## Measured official baseline

`scripts/comparison_ortools.py` downloads an exact Google source revision and
verifies SHA-256 before running it. The only runtime wrapper sets one worker,
seed 0, and a ten-second limit, and records the actual solver status. It checks
the resulting text with pure Python pairwise arithmetic that imports neither
ShopShift nor the solver model.

The recorded macOS arm64 / Python 3.12.13 / OR-Tools 9.15.6755 run found **OPTIMAL,
makespan 11**, matching the official toy instance. The separate oracle checked
all eight operations, seven same-machine pairs, five precedence links, exact
durations, and nonnegative starts. Solver time was 0.003373 seconds; execution of
the already-imported example was 0.005262 seconds. These exclude interpreter and
OR-Tools import startup. Download time was recorded separately. See the complete
machine-readable [result](comparison_ortools.json).

These times are one local observation, not a comparative speed claim. The sample
has no calendar holes, employee constraints, dates, file import, manual decisions,
or persistence. Its report prints an optimal-looking label even on a feasible
return path, so the harness records the returned status explicitly. Product
labels must preserve the documented [CP-SAT distinctions](https://developers.google.com/optimization/cp/cp_solver).

## Repeated workflow experiment

The acceptance experiment uses wholly synthetic exports shaped like machining
routers: stable operation ID, job, machine, operator, setup, run, predecessor,
release, due date and description. Dates and quantities are invented. No private
ERP exports are bundled. The scenario is: import day one; make a manual lock;
save; reopen; import reordered day-two rows with duration changes, a new order
and an omitted row; inspect conflicts; compare an alternative; export a daily
list; backup and restore. A changed duration must update its operation but never
quietly move its locked start. An omitted row must remain until deliberately
removed. A duplicate ID or corrupt workbook must reject the transaction.

The [executable harness](../scripts/comparison_workflow.py) completed this loop
through the public APIs on macOS arm64 / Python 3.12.13. Its small
[result log](comparison_workflow.json) records these observations:

- Day one: 12 synthetic work orders, 36 operations, three machines and three
  operator resources; a five-day Chicago horizon with lunch holes. Setup and run
  values include 35.5 minutes, resolved to exact integer seconds.
- Day two: 38 XLSX rows in reverse order, with one changed duration, three new
  operations and one omitted operation. The merged model has 39 operations.
  All 72 existing start/lock records in two scenarios were identical as data
  structures after import. Ten saved field mappings were reused after
  save/reopen; no field definitions were re-entered.
- The harness extended a locked operation to one minute after the next operation
  starts. The original starts remained; the validator reported machine and
  operator overlaps of 60 seconds and a 60-second precedence violation. The three
  new operations remained visibly unscheduled until review.
- The reviewed alternative retained the locked start and independently passed
  full coverage, duration, horizon, release, calendar, 234 resource-pair and 26
  precedence checks. Both two-second searches returned **feasible**, with
  optimality unproven. The initial plan checked 198 resource pairs and 24 links.
- Duplicate IDs and a corrupt workbook were rejected without modifying the
  input project. Daily CSV and printable HTML were generated. Explicit backup
  restore recovered the exact project after the working file was intentionally
  corrupted. This simulates file damage; it is not an operating-system crash test.

| Measured API step | One observed elapsed time |
| --- | ---: |
| Initial CSV import | 1.430 ms |
| Initial suggestion, including validation | 2.001 s |
| Save and reopen initial project | 1.483 ms + 0.418 ms |
| XLSX reimport | 4.289 ms |
| Conflict validation after import | 0.105 ms |
| Revised suggestion, including validation | 2.005 s |
| Daily CSV and HTML exports | 0.574 ms + 0.420 ms |
| Backup and explicit restore | 0.908 ms + 1.893 ms |

These timings exclude generating fixtures, application startup, clicking,
mapping, and human review. They are not first-use timings or a performance
comparison against competitor applications. Temporary exports and projects were
deleted; the generator and compact report remain. GUI paths, actual restart and
accessibility still require separate GUI QA evidence.

Running the same official eight-task instance through ShopShift also returned
**optimal, makespan 11**, with the independent oracle passing. Its 0.169444-second
API time includes the first lazy OR-Tools import in that process, unlike the
official-example timing above, so those two numbers must not be treated as a
speed benchmark.

One meaningful limitation emerged: accepting the new suggestion changed 32 of
36 unlocked existing starts. Import stability is established; suggestion
stability is **not** an optimization objective. Planners must lock commitments
and review the scenario changes before accepting a regenerated plan.

Logical action counts for this protocol are **not mouse-click counts**:

| Stage | Count and definition | Repeated-day implication |
| --- | --- | --- |
| First data setup | 4 actions: create project/horizon/zone; map columns and units; import; review generated resource availability. | Mapping and calendars should persist. |
| First usable plan | 4 actions: request a suggestion; review and accept; adjust/lock a chosen operation; save. | Every suggestion remains optional. |
| Next export | 3 actions: reopen project; choose new export with saved mapping; review added/changed/retained rows and conflicts. | The experiment reused all 10 column mappings. |
| Resolve and distribute | 4 actions: copy scenario; request/review suggestion; export read-only daily plan; save/backup. | Counts vary with data errors and decisions; no fixed time promise. |

These categories describe user intentions. They do not imply fewer interactions
than JPI/frePPLe/Monday; those products were not run. The falsifiable benefit is
zero manual re-entry of saved column definitions and unchanged starts/locks after
reordering/reimport, with new inconsistencies visible for review.

## Runtime and distribution costs

The numeric engine remains OR-Tools, not a new solver. The selected UI dependency
is **PySide6-Essentials**, avoiding the unrelated Addons bundle. Published wheel
sizes for the exact measured versions are below (decimal MB, compressed). Actual
release archives, installed sizes, interpreter and transitive dependencies are
additional and must be measured during packaging.

| Package | macOS arm64 or universal | Windows x64 | Linux x64 | Package license metadata |
| --- | ---: | ---: | ---: | --- |
| OR-Tools 9.15.6755, CPython 3.12 | 21.91 MB | 23.88 MB | 29.84 MB | Apache-2.0 |
| PySide6-Essentials 6.11.2 | 110.80 MB | 76.91 MB | 80.11 MB | LGPL-3.0 / GPL alternatives |
| Shiboken6 6.11.2 | 0.48 MB | 1.23 MB | 0.27 MB | LGPL-3.0 / GPL alternatives |
| openpyxl 3.1.5 | 0.25 MB | 0.25 MB | 0.25 MB | MIT |

[Exact metadata and wheel hashes](comparison_dependencies.json) are generated by
`scripts/comparison_dependencies.py`. PySide's selected wheels require macOS 13+
and Linux x64 glibc 2.34+; Python metadata allows >=3.10,<3.15. Product Python
support is narrower. OR-Tools brings numpy, pandas, protobuf, absl-py,
typing-extensions and immutabledict, so a tiny installer is not a credible claim.

Upstream [OR-Tools](https://github.com/google/or-tools/blob/stable/LICENSE),
[Qt component notices](https://doc.qt.io/qtforpython-6/licenses.html) and all
transitive notices must accompany distribution as applicable. The repository's
license does not replace dependency terms. Dynamic Qt libraries should remain
replaceable in the distribution; the release license inventory and rebuild
instructions are part of packaging acceptance. frePPLe Community is itself
[MIT licensed](https://frepple.com/docs/current/license.html), so licensing alone
is not a reason to build another planner.

## Decision boundaries

Continue only while stable IDs, import review, local recovery, independent
validation and straightforward daily output work end-to-end. Do not broaden into
inventory, live execution, accounts, machine control, ERP writes or multiple
planners to manufacture a larger market claim. A user needing split operations,
alternative machines, sequence-dependent setups, an operator shared by concurrent
machines, material constraints or centrally coordinated planners should evaluate
the existing alternatives.

A release-quality implementation can establish technical workflow feasibility.
It cannot establish customer fit without actual planners trying their exports
and reporting whether data maintenance and conflict review beat their existing
method. That remains the main uncertainty.

## Reproduce the recorded checks

From the repository root with the documented project environment installed:

```sh
PYTHONPATH=src .venv/bin/python scripts/comparison_workflow.py --output docs/comparison_workflow.json
.venv/bin/python scripts/comparison_ortools.py --output docs/comparison_ortools.json
.venv/bin/python scripts/comparison_dependencies.py --output docs/comparison_dependencies.json
```

The first command runs offline and cleans its temporary fixtures. The other two
read public upstream metadata/source over HTTPS. The official-source harness
also accepts `--source` for an already downloaded exact file and still checks
its pinned hash. Timings, solver incumbents and chosen unlocked starts can vary
between machines or reruns. The logged observations above describe the recorded
run; rerunning the JSON output does not automatically rewrite this narrative.
