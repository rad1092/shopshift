# Reusable validator API

`shopshift.model` and `shopshift.validator` are plain Python modules. They import neither Qt nor OR-Tools. The library is included in this product and can be used in import checks and other planning tools.

```python
from shopshift.model import Project, Operation, Resource, Window, Placement
from shopshift.validator import validate

project = Project(horizon_start=0, horizon_end=3600)
project.machines["mill"] = Resource("mill", [Window(0, 3600)])
project.operations["op-1"] = Operation("op-1", "job-1", "mill", run=600)
project.scenario.placements["op-1"] = Placement(120, locked=True)
issues = validate(project)
assert not [issue for issue in issues if issue.severity == "error"]
```

All instants and durations are integral seconds. Windows and placements use half-open intervals; a task may end exactly when the next begins. A continuous operation must fit inside one available resource span. Due dates generate warnings when exceeded; release times are hard constraints. An unscheduled operation is a warning and does not mean the overall plan is complete.

`Issue` exposes `code`, `message`, `operation_ids`, `severity`. Check severity and scheduling completeness separately. Preserve codes when presenting errors; the UI uses human-readable messages, while integrations can group by code.

`Project.from_dict(data)` performs strict structural deserialization; `validate` performs semantic checking. Loading a structurally valid but conflicting plan within storage limits is intentional so a planner can repair it.

`shopshift.storage.validate_project_for_storage(project)` returns `None` or raises `StorageProblem`. It checks the same schema, bounds and canonical encoded size as saving, without writing a file or checking scheduling feasibility. Call it before accepting a mutable draft in an integration. `Project.from_dict` and `import_operations` alone do not enforce all persistence limits. The desktop app uses this common gate before applying edits/imports or replacing its project, preserving the current draft and undo history on rejection. `load_project` also checks that a compact input fits the canonical saved format. Conflicts and infeasible schedules remain saveable drafts.

For suggestions, `shopshift.solver.suggest(project, time_limit=5.0)` returns status, placements, issues, wall_time, objective and bound. It does not mutate the project. Review before replacing the current scenario placements. Status `optimal` means the declared objective was proven optimal; `feasible` means a valid candidate without optimality proof; `time_limited` means no candidate was found within the budget; `infeasible` means constraints proved impossible; `invalid` means bad inputs. No plan is silently partially applied.

Persist with `shopshift.storage.save_project` / `load_project`; import with `shopshift.importing.import_operations`. See the test suite for a complete repeated-import example. JSON format version is controlled by storage; unsupported schema versions are rejected rather than guessed.
