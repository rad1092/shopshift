"""Engine regression tests with an oracle that does not use engine helpers."""

from __future__ import annotations

import random
import subprocess
import sys
from copy import deepcopy

import pytest

from shopshift.model import Operation, Placement, Project, Resource, Scenario, Window
from shopshift.solver import suggest
from shopshift.validator import validate


def project(operations=None, end=100):
    return Project(horizon_start=0, horizon_end=end,
                   machines={"M": Resource("M", [Window(0, end)])},
                   operations=operations or {"A": Operation("A", "J", "M", run=10)})


def codes(p, scenario=None):
    return {issue.code for issue in validate(p, scenario)}


def assert_independent_oracle(p, placements):
    """Deliberately pairwise and direct, sharing no validator/solver routines."""
    assert set(placements) == set(p.operations)
    jobs = list(p.operations.values())
    for operation in jobs:
        start = placements[operation.id].start
        end = start + operation.setup + operation.run
        assert p.horizon_start <= start < end <= p.horizon_end
        assert operation.release is None or start >= operation.release
        for predecessor in operation.predecessors:
            pred = p.operations[predecessor]
            assert placements[predecessor].start + pred.setup + pred.run <= start
        for resources, key in ((p.machines, operation.machine), (p.operators, operation.operator)):
            if not key:
                continue
            # Verify each integer second directly on tiny test horizons.
            for second in range(start, end):
                assert any(w.start <= second < w.end for w in resources[key].windows)
    for i, left in enumerate(jobs):
        for right in jobs[i + 1:]:
            if left.machine == right.machine or (left.operator and left.operator == right.operator):
                left_start, right_start = placements[left.id].start, placements[right.id].start
                assert (left_start + left.setup + left.run <= right_start
                        or right_start + right.setup + right.run <= left_start)
    for key, existing in p.scenario.placements.items():
        if existing.locked:
            assert placements[key] == existing


def test_roundtrip_independent_mutable_defaults_and_saved_locks():
    p = project()
    p.scenario.placements["A"] = Placement(4, True)
    p.mappings["erp"] = {"id": "Operation No", "__duration_unit": "minutes"}
    loaded = Project.from_dict(p.to_dict())
    assert loaded == p
    loaded.operations["A"].predecessors.append("new")
    loaded.scenario.placements["A"].start = 8
    assert p.operations["A"].predecessors == []
    assert p.scenario.placements["A"].start == 4
    assert Project().scenario.placements == {}


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(extra="future field"),
    lambda d: d.update(horizon_start=True),
    lambda d: d.update(horizon_end=3.5),
    lambda d: d.update(horizon_end="100"),
    lambda d: d.update(horizon_end=10 ** 100),
    lambda d: d.update(machines=None),
    lambda d: d.update(active_scenario="Missing"),
    lambda d: d["operations"]["A"].update(id="other"),
    lambda d: d["operations"]["A"].update(predecessors="B"),
    lambda d: d["operations"]["A"].update(setup=False),
    lambda d: d["operations"]["A"].pop("predecessors"),
    lambda d: d["machines"]["M"]["windows"][0].update(start=False),
    lambda d: d["scenarios"]["Baseline"].update(name="other"),
    lambda d: d["scenarios"]["Baseline"]["placements"]["A"].update(locked="false"),
    lambda d: d["scenarios"]["Baseline"]["placements"]["A"].pop("locked"),
    lambda d: d["scenarios"]["Baseline"]["placements"]["A"].update(end=25),
    lambda d: d.update(mappings={"x": {"id": None}}),
])
def test_strict_deserialization_rejects_corrupt_schema(mutation):
    p = project()
    p.scenario.placements["A"] = Placement(0, True)
    payload = p.to_dict()
    mutation(payload)
    with pytest.raises(ValueError):
        Project.from_dict(payload)


def test_semantic_conflict_is_loadable_but_visible():
    p = project()
    p.scenario.placements["A"] = Placement(99, True)
    loaded = Project.from_dict(p.to_dict())
    assert loaded == p
    assert {"outside_horizon", "machine_calendar"} <= codes(loaded)


@pytest.mark.parametrize("setup,run", [(0, 0), (-1, 10), (1, -1), (True, 2), (0, 1.5)])
def test_invalid_duration(setup, run):
    p = project()
    p.operations["A"].setup, p.operations["A"].run = setup, run
    assert "invalid_duration" in codes(p)
    assert suggest(p).status == "invalid"


def test_lunch_hole_operator_intersection_and_adjacent_calendar_boundaries():
    p = project(end=30)
    p.machines["M"].windows = [Window(0, 8), Window(8, 10), Window(20, 30)]
    p.operators["P"] = Resource("P", [Window(5, 25)])
    p.operations["A"].operator = "P"
    p.operations["A"].run = 10
    p.scenario.placements["A"] = Placement(5)
    assert "machine_calendar" in codes(p)
    assert suggest(p).status == "infeasible"  # Intersection has no 10-second block.
    p.operations["A"].operator = ""
    p.scenario.placements["A"] = Placement(0)
    assert not [issue for issue in validate(p) if issue.severity == "error"]
    assert suggest(p).placements["A"].start == 0


def test_touching_intervals_valid_but_machine_and_operator_conflicts_separate():
    p = project({"A": Operation("A", "J1", "M", "P", run=10),
                 "B": Operation("B", "J2", "N", "P", run=10)})
    p.machines["N"] = Resource("N", [Window(0, 100)])
    p.operators["P"] = Resource("P", [Window(0, 100)])
    p.scenario.placements = {"A": Placement(0), "B": Placement(9)}
    assert "operator_overlap" in codes(p)
    assert "machine_overlap" not in codes(p)
    p.operations["B"].machine = "M"
    assert {"operator_overlap", "machine_overlap"} <= codes(p)
    p.scenario.placements["B"].start = 10
    assert validate(p) == []
    result = suggest(p)
    assert_independent_oracle(p, result.placements)


def test_partial_missing_resource_dependency_and_cycle_messages():
    p = project({"A": Operation("A", "J", "M", predecessors=["B"]),
                 "B": Operation("B", "J", "M", predecessors=["A"])})
    assert "dependency_cycle" in codes(p)
    p.operations["A"].predecessors = ["missing"]
    p.operations["B"].machine = "missing machine"
    assert {"missing_machine", "missing_predecessor"} <= codes(p)
    assert suggest(p).status == "invalid"
    p = project({"A": Operation("A", "J", "M", run=10),
                 "B": Operation("B", "J", "M", run=10, predecessors=["A"])})
    p.scenario.placements["B"] = Placement(20, True)
    assert {"unscheduled", "unscheduled_predecessor"} <= codes(p)
    result = suggest(p)
    assert result.status == "optimal"
    assert_independent_oracle(p, result.placements)


def test_precedence_release_and_lateness_are_distinct():
    p = project({"A": Operation("A", "J", "M", setup=5, run=5),
                 "B": Operation("B", "J", "M", run=10, predecessors=["A"], release=15, due=18)})
    p.scenario.placements = {"A": Placement(0), "B": Placement(8)}
    assert {"precedence", "before_release"} <= codes(p)
    p.scenario.placements["B"].start = 15
    assert codes(p) == {"late"}
    assert validate(p)[0].severity == "warning"
    result = suggest(p)
    assert result.status == "optimal"
    assert result.objective == 32  # end 25 + tardiness 7
    assert_independent_oracle(p, result.placements)


def test_due_date_objective_changes_order_without_hard_deadline():
    p = project({"A": Operation("A", "J1", "M", run=8),
                 "B": Operation("B", "J2", "M", run=2, due=2)})
    result = suggest(p)
    assert result.status == "optimal"
    assert result.placements["B"].start == 0
    assert result.objective == result.bound == 10


def test_locks_not_moved_changed_duration_detected_and_input_unmodified():
    p = project({"A": Operation("A", "J1", "M", run=10),
                 "B": Operation("B", "J2", "M", run=10)})
    p.scenario.placements = {"A": Placement(20, True), "B": Placement(-999)}
    original = deepcopy(p)
    result = suggest(p)
    assert result.status == "optimal"
    assert p == original
    assert result.placements["A"] == Placement(20, True)
    p.scenario.placements["B"] = Placement(29, True)
    result = suggest(p)
    assert result.status == "infeasible" and result.placements == {}
    assert any(i.code == "machine_overlap" for i in result.issues)
    p.scenario.placements["B"].start = 30
    p.operations["A"].run = 11
    assert suggest(p).status == "infeasible"


def test_orphaned_locks_and_selected_scenario():
    p = project()
    p.scenario.placements["ghost"] = Placement(0, True)
    assert "orphan_lock" in codes(p)
    assert suggest(p).status == "invalid"
    alternative = Scenario("Preview", {"A": Placement(50, True)})
    result = suggest(p, alternative)
    assert result.status == "optimal"
    assert result.placements["A"].start == 50
    assert p.scenario.placements["ghost"].locked
    p.scenario.placements["ghost"].locked = False
    assert suggest(p).status == "optimal"  # Stale unlocked placements are rebuilt.


@pytest.mark.parametrize("limit", [0, -1, float("nan"), float("inf"), True, "5", 10 ** 999])
def test_time_limit_validation(limit):
    assert suggest(project(), time_limit=limit).status == "invalid"


def test_infeasible_capacity_and_empty_availability():
    p = project({"A": Operation("A", "J1", "M", run=6),
                 "B": Operation("B", "J2", "M", run=6)}, end=10)
    result = suggest(p)
    assert result.status == "infeasible"
    assert result.placements == {} and result.objective is None and result.bound is None
    p.machines["M"].windows = []
    assert suggest(p).status == "infeasible"


def test_validator_handles_long_chains_without_recursive_dfs():
    p = project({str(i): Operation(str(i), "J", "M", run=1, predecessors=[str(i - 1)] if i else [])
                 for i in range(1500)}, end=2000)
    assert not [issue for issue in validate(p) if issue.severity == "error"]
    p.operations["0"].predecessors = ["1499"]
    cycle = [issue for issue in validate(p) if issue.code == "dependency_cycle"]
    assert len(cycle) == 1 and len(cycle[0].operation_ids) == 1500


def test_api_import_does_not_load_qt_or_solver_libraries():
    # A new process proves transitive imports stay independent, even when other
    # pytest modules have already imported OR-Tools or Qt in this process.
    subprocess.run([sys.executable, "-c", "import sys; import shopshift.model; import shopshift.validator; "
                    "import shopshift.solver; assert not any(k.startswith(('PySide6', 'ortools')) "
                    "for k in sys.modules)"], check=True, timeout=5)


@pytest.mark.parametrize("seed", range(12))
def test_randomized_complete_plans_independent_oracle(seed):
    rng = random.Random(seed)
    p = Project(horizon_start=0, horizon_end=150,
                machines={key: Resource(key, [Window(0, 50), Window(60, 150)]) for key in ("M1", "M2", "M3")},
                operators={key: Resource(key, [Window(0, 45), Window(65, 150)]) for key in ("P1", "P2")})
    for i in range(12):
        key = str(i)
        p.operations[key] = Operation(key, str(i // 3), rng.choice(list(p.machines)),
                                      rng.choice(["", "P1", "P2"]), setup=rng.randrange(3), run=rng.randrange(1, 7),
                                      predecessors=[str(i - 1)] if i % 3 else [], release=rng.randrange(5),
                                      due=20 + rng.randrange(60))
    original = deepcopy(p)
    result = suggest(p, time_limit=0.25)
    assert result.status in {"optimal", "feasible"}
    assert_independent_oracle(p, result.placements)
    assert p == original
    assert result.bound <= result.objective


def test_cp_sat_status_mapping_and_candidate_gate(monkeypatch):
    from ortools.sat.python import cp_model

    class FakeSolver:
        def __init__(self):
            class Parameters:
                pass
            self.parameters = Parameters()
            self.objective_value = 10.0
            self.best_objective_bound = 0.0

        def solve(self, model):
            return self.status

        def value(self, variable):
            return self.start

    monkeypatch.setattr(cp_model, "CpSolver", FakeSolver)
    for cp_status, expected in ((cp_model.UNKNOWN, "time_limited"), (cp_model.MODEL_INVALID, "invalid"),
                                (cp_model.INFEASIBLE, "infeasible")):
        FakeSolver.status = cp_status
        assert suggest(project()).status == expected
        assert suggest(project()).placements == {}
    FakeSolver.status, FakeSolver.start = cp_model.FEASIBLE, 0
    result = suggest(project())
    assert result.status == "feasible"
    assert any(issue.code == "optimality_unproven" for issue in result.issues)
    FakeSolver.status, FakeSolver.start = cp_model.OPTIMAL, 1000
    result = suggest(project())
    assert result.status == "invalid" and not result.placements
    assert any(issue.code == "candidate_rejected" for issue in result.issues)


def test_moderate_realistic_workload_with_one_worker():
    p = Project(horizon_start=0, horizon_end=20000,
                machines={f"M{i}": Resource(f"M{i}", [Window(0, 9000), Window(10000, 20000)]) for i in range(6)})
    for i in range(120):
        p.operations[str(i)] = Operation(str(i), f"J{i // 3}", f"M{i % 6}", setup=10, run=90,
                                         predecessors=[str(i - 1)] if i % 3 else [])
    result = suggest(p, time_limit=1)
    assert result.status in {"optimal", "feasible"}
    assert_independent_oracle(p, result.placements)
    assert result.wall_time < 5
