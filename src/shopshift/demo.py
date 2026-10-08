"""Small, deterministic, entirely synthetic metal-shop example."""

from __future__ import annotations

import copy

from .model import Operation, Placement, Project, Resource, Scenario, Window
from .timeutil import parse_timestamp, working_windows

ERP_MAPPING = {"id": "Operation", "job": "Work Order", "machine": "Work Center", "operator": "Assigned To",
               "setup": "Setup Min", "run": "Run Min", "predecessors": "After", "release": "Ready At",
               "due": "Due At", "label": "Description"}


def demo_project() -> Project:
    """21 operations, real contention, one late job, a lunch break and service gap.

The placements are authored sample planner decisions, not a scheduling engine.
The dates and employee names are synthetic; no external files are required.
"""
    zone = "America/Chicago"
    def stamp(text):
        return parse_timestamp(text, zone)
    project = Project("Prairie Metal — synthetic shop", zone,
                      stamp("2026-10-05T00:00"), stamp("2026-10-10T00:00"))
    windows = working_windows(project.horizon_start, project.horizon_end, zone)
    project.machines = {name: Resource(name, copy.deepcopy(windows))
                        for name in ("SAW", "MILL-1", "LATHE-1", "QC")}
    project.operators = {name: Resource(name, copy.deepcopy(windows)) for name in ("Morgan", "Alex", "Priya")}
    # Maintenance on the mill: Tuesday 13:00–14:00 is unavailable.
    service_start, service_end = stamp("2026-10-06T13:00"), stamp("2026-10-06T14:00")
    mill = project.machines["MILL-1"]
    mill.windows = [part for window in mill.windows for part in (
        [Window(window.start, service_start), Window(service_end, window.end)]
        if window.start <= service_start < service_end <= window.end else [window]) if part.start < part.end]
    jobs = [
        ("401", "Pump mounting plate", "MILL-1", "Alex", 30, 120, "2026-10-05T10:30", "2026-10-05T08:00", "2026-10-05T09:00", "2026-10-05T11:00"),
        ("402", "Valve spindle", "LATHE-1", "Priya", 45, 120, "2026-10-05T16:00", "2026-10-05T08:45", "2026-10-05T10:00", "2026-10-05T13:00"),
        ("403", "Conveyor bracket", "MILL-1", "Alex", 30, 120, "2026-10-06T10:00", "2026-10-05T09:30", "2026-10-05T13:00", "2026-10-05T15:00"),
        ("404", "Motor base adapter", "MILL-1", "Alex", 30, 120, "2026-10-06T15:00", "2026-10-05T13:30", "2026-10-06T08:00", "2026-10-06T10:00"),
        ("405", "Bearing collar", "LATHE-1", "Priya", 45, 120, "2026-10-06T12:00", "2026-10-05T14:00", "2026-10-05T15:00", "2026-10-06T08:00"),
        ("406", "Repair clevis", "MILL-1", "Alex", 30, 90, "2026-10-07T12:00", "2026-10-06T08:30", "2026-10-06T10:00", "2026-10-06T11:30"),
        ("407", "Sensor standoff", "LATHE-1", "Priya", 30, 90, "2026-10-07T17:00", "2026-10-06T09:00", "2026-10-06T10:00", "2026-10-06T13:00"),
    ]
    for job, label, machine, operator, cut_minutes, machine_minutes, due, cut_at, machine_at, qc_at in jobs:
        identity = f"WO-{job}"
        release = stamp("2026-10-05T08:00")
        due_epoch = stamp(due)
        specs = [
            ("10", "SAW", "Morgan", 10, cut_minutes - 10, [], cut_at, "Cut stock"),
            ("20", machine, operator, 30, machine_minutes - 30, [f"{identity}-10"], machine_at, "Machine"),
            ("30", "QC", "Morgan", 5, 25, [f"{identity}-20"], qc_at, "Inspect and deburr"),
        ]
        for step, resource, person, setup, run, predecessors, planned, stage in specs:
            op_id = f"{identity}-{step}"
            project.operations[op_id] = Operation(op_id, identity, resource, person, setup * 60, run * 60,
                                                 predecessors, release, due_epoch, f"{label} / {stage}")
            project.scenario.placements[op_id] = Placement(stamp(planned), locked=op_id == "WO-401-20")
    scenario = copy.deepcopy(project.scenario)
    scenario.name = "Overtime review"
    project.scenarios[scenario.name] = Scenario(scenario.name, scenario.placements)
    project.mappings = {"__last__": dict(ERP_MAPPING, __duration_unit="minutes")}
    return project
