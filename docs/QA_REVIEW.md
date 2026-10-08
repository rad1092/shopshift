# Independent acceptance review

This review covers the offline scheduling and file workflow. It is separate
from implementation-owned engine/I/O unit tests and from GUI and packaged-launch
checks. All fixtures are authored synthetic data; no customer export is included.

Latest local result: **87 acceptance tests passed in 0.61 seconds**, and Ruff
passed for the acceptance suite and benchmark generator. This count excludes
the implementation-owned engine/I/O suites and GUI tests.

## Independent oracle

`tests/test_acceptance.py` contains a direct pairwise arithmetic oracle that
imports neither the production validator nor OR-Tools inside its checks.

- Sixteen tiny shops each enumerate all 343 start combinations: **5,488**
  candidate schedules checked for validator agreement. Shops vary machine and
  operator calendars, holes, setup/run durations, release times and dependencies.
- Twenty-four tiny shops independently enumerate feasible starts and minimum
  objective values. CP-SAT's feasibility, objective and locks must agree exactly;
  input objects must remain unchanged. No solver-produced schedule acts as the
  ground truth for these cases.
- A feasible arithmetic witness with a deliberately exhausted real CP-SAT search
  budget checks that `time_limited` means unknown feasibility, never infeasible.
- Direct scenarios cover machine-independent operator conflicts, endpoint
  touching, calendar holes, malformed/missing resources and predecessors,
  dependency cycles, conflicting locks, and rebuilding invalid unlocked starts.

Time tests cover New York's DST gaps and repeated clocks, Lord Howe's half-hour
DST transitions, explicit-offset round trips, elapsed time across the repeated
hour, overnight Friday shifts continuing into Saturday, malformed offsets and
subsecond rejection. Extreme offset-bearing dates must fit the saved model's
representable UTC range.

## Repeated import and persistence

Acceptance exercises CSV BOMs, mapped fields, retained unmapped fields, explicit
blank clearing, exact decimal units, native XLSX dates and numbers, XLSX formula
rejection, duplicate IDs, truncated records, missing/extra columns, and invalid
rows following valid rows. Import failure must leave the input project identical.

The repeated-import scenario changes a duration, introduces a resource/operation,
and omits an existing row. It compares **all scenario placements and lock flags**
before and after import, then requires the validator to expose the resulting
overlap. Omitted rows remain present, and saved mapping units remain explicit.

Three child processes terminate with `os._exit` at distinct save boundaries:
before replacing the backup, before replacing the main project, and immediately
after replacing the main project. This bypasses Python cleanup and tests actual
abrupt process exit, not just an exception. Every observed main/backup file
remains a complete readable expected version. Corruption recovery separately
requires explicit restore and preserves damaged bytes in `.corrupt`.

These tests do **not** simulate filesystem power loss or prove disk durability on
every platform. The implementation documents Windows directory-fsync limits.
CSV/HTML snapshot tests additionally cover overnight day intersections,
unscheduled work, lateness, HTML escaping and spreadsheet formula escaping.

## Defects found during review

1. **Decimal precision silently rounded a fractional duration.** Importing
   `0.01666666666666666666666666667` minutes originally yielded one second.
   Default Decimal multiplication precision rounded before the integrality test.
   Import now uses exact rational multiplication, and a public import regression
   requires rejection. This was an actual observed defect, not a speculative risk.
2. **Extreme offset dates escaped the persistence range.** Parsing year 0001
   with a +23:59 offset or year 9999 with a -23:59 offset originally returned UTC
   instants outside the model's supported year range, creating an unsaveable
   import. Parsing now rejects unrepresentable instants; boundary regressions
   cover both directions.

## Bounded workload measurements

The standalone `scripts/benchmark_shop.py` generates three production cells,
each with two machines and one shared operator. Each job has three dependent
operations, explicit setup and run durations, releases and due dates. Calendars
have lunch holes, an operator's Wednesday afternoon absence, and weekly machine
maintenance. A 45-minute template constructs a known feasible input plan; it is
a fixture, not a replacement scheduling algorithm. Three manual locks remain.

Every workload performs initial CSV import, daily reimport with 5% duration
updates and one omitted operation, validation, optional suggestion, a second
independent pairwise candidate check, save/reopen equality, and daily CSV/HTML
exports. Temporary fixtures are removed automatically; only the generator and
small measurement reports remain.

Observed on macOS 27.0.1 arm64, Python 3.12.13, OR-Tools 9.15.6755, one solver
worker, a three-second **search** cap:

| Workload | Reimport | Suggestion API | Result | Independent candidate check |
| --- | ---: | ---: | --- | --- |
| 240 operations / 80 jobs, staged releases | 0.0053 s | 0.4161 s | Optimal | 240 operations, no violations |
| 480 operations / 160 jobs, staged releases | 0.0101 s | 0.3021 s | Optimal | 480 operations, no violations |
| 480 operations / 160 jobs, all backlog ready day one | 0.0100 s | 3.2021 s | Feasible, optimum unproven | 480 operations, no violations |

See [staged-release log](benchmark_shop.json) and [backlog log](benchmark_backlog.json).
The first run in each process includes lazy OR-Tools import and model building;
the search limit does not bound total API wall time. These are single local
observations, not comparative speed claims or general capacity guarantees.

The backlog incumbent objective was 2,357,700 seconds with a best bound of
304,860 seconds. That wide gap matters: a feasible returned plan can be far from
proven best, even when every resource/calendar/dependency invariant is satisfied.
The displayed status must remain `feasible`. The benchmark does not establish
real-shop productivity, performance for arbitrary 480-operation constraint
graphs, or superiority over an expert spreadsheet, frePPLe or commercial tools.

## Reproduction and remaining release evidence

```sh
PYTHONPATH=src .venv/bin/python -m pytest tests/test_acceptance.py -q
.venv/bin/python -m ruff check tests/test_acceptance.py scripts/benchmark_shop.py
PYTHONPATH=src .venv/bin/python scripts/benchmark_shop.py --operations 240 480 --seconds 3 --output docs/benchmark_shop.json
PYTHONPATH=src .venv/bin/python scripts/benchmark_shop.py --operations 480 --seconds 3 --backlog --output docs/benchmark_backlog.json
```

Native GUI drag/keyboard, dialog cancellation/review, undo, accessibility,
screenshots, fresh packaged launches, Windows/Linux CI and exact release-SHA
status are separate acceptance evidence. This headless review does not stand in
for those checks or claim that an installer is signed/notarized. Release
artifacts and distribution evidence belong in [distribution notes](DISTRIBUTION.md).
