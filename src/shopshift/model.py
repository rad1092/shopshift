"""Plain, dependency-free scheduling data and strict JSON deserialization.

All time values are integral UTC epoch seconds. Deserialization rejects malformed
data, but intentionally preserves logically conflicting plans for human review.
Use :func:`shopshift.validator.validate` to inspect those conflicts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MIN_TIMESTAMP = -62135596800  # 0001-01-01 UTC
MAX_TIMESTAMP = 253402300799  # 9999-12-31T23:59:59 UTC


def _object(value: Any, fields: set[str], path: str, required: set[str] | None = None) -> dict:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise ValueError(f"{path}: expected an object with string keys")
    unknown = value.keys() - fields
    if unknown:
        raise ValueError(f"{path}: unknown fields: {', '.join(sorted(unknown))}")
    missing = (required or set()) - value.keys()
    if missing:
        raise ValueError(f"{path}: missing fields: {', '.join(sorted(missing))}")
    return value


def _string(value: Any, path: str, nonempty: bool = False) -> str:
    if not isinstance(value, str) or (nonempty and not value.strip()):
        raise ValueError(f"{path}: expected {'nonempty ' if nonempty else ''}text")
    return value


def _integer(value: Any, path: str, timestamp: bool = False) -> int:
    if type(value) is not int:
        raise ValueError(f"{path}: expected an integer, not a boolean, float, or numeric string")
    low, high = (MIN_TIMESTAMP, MAX_TIMESTAMP) if timestamp else (-MAX_TIMESTAMP, MAX_TIMESTAMP)
    if not low <= value <= high:
        raise ValueError(f"{path}: integer outside supported range [{low}, {high}]")
    return value


def _mapping(value: Any, path: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected an object")  # noqa: TRY004 — uniform invalid-JSON API
    for key in value:
        _string(key, f"{path} key", nonempty=True)
    return value


def _list(value: Any, path: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{path}: expected an array")  # noqa: TRY004 — uniform invalid-JSON API
    return value


@dataclass
class Window:
    start: int
    end: int

    def to_dict(self) -> dict:
        return {"start": self.start, "end": self.end}

    @classmethod
    def from_dict(cls, data: Any) -> Window:
        d = _object(data, {"start", "end"}, "window", {"start", "end"})
        return cls(_integer(d["start"], "window.start", True), _integer(d["end"], "window.end", True))


@dataclass
class Resource:
    id: str
    windows: list[Window] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"id": self.id, "windows": [w.to_dict() for w in self.windows]}

    @classmethod
    def from_dict(cls, data: Any) -> Resource:
        d = _object(data, {"id", "windows"}, "resource", {"id", "windows"})
        return cls(_string(d["id"], "resource.id", True),
                   [Window.from_dict(w) for w in _list(d["windows"], "resource.windows")])


@dataclass
class Operation:
    id: str
    job: str
    machine: str
    operator: str = ""
    setup: int = 0
    run: int = 60
    predecessors: list[str] = field(default_factory=list)
    release: int | None = None
    due: int | None = None
    label: str = ""

    @property
    def duration(self) -> int:
        return self.setup + self.run

    def to_dict(self) -> dict:
        return {"id": self.id, "job": self.job, "machine": self.machine, "operator": self.operator,
                "setup": self.setup, "run": self.run, "predecessors": list(self.predecessors),
                "release": self.release, "due": self.due, "label": self.label}

    @classmethod
    def from_dict(cls, data: Any) -> Operation:
        d = _object(data, set(cls.__dataclass_fields__), "operation", set(cls.__dataclass_fields__))

        def optional_time(key: str) -> int | None:
            return None if d[key] is None else _integer(d[key], f"operation.{key}", True)
        return cls(
            id=_string(d["id"], "operation.id", True),
            job=_string(d["job"], "operation.job", True),
            machine=_string(d["machine"], "operation.machine", True),
            operator=_string(d.get("operator", ""), "operation.operator"),
            setup=_integer(d.get("setup", 0), "operation.setup"),
            run=_integer(d.get("run", 60), "operation.run"),
            predecessors=[_string(p, "operation.predecessors entry", True)
                          for p in _list(d.get("predecessors", []), "operation.predecessors")],
            release=optional_time("release"), due=optional_time("due"),
            label=_string(d.get("label", ""), "operation.label"),
        )


@dataclass
class Placement:
    start: int
    locked: bool = False

    def to_dict(self) -> dict:
        return {"start": self.start, "locked": self.locked}

    @classmethod
    def from_dict(cls, data: Any) -> Placement:
        d = _object(data, {"start", "locked"}, "placement", {"start", "locked"})
        if type(d.get("locked", False)) is not bool:
            raise ValueError("placement.locked: expected a boolean")
        return cls(_integer(d["start"], "placement.start", True), d.get("locked", False))


@dataclass
class Scenario:
    name: str
    placements: dict[str, Placement] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"name": self.name, "placements": {k: v.to_dict() for k, v in self.placements.items()}}

    @classmethod
    def from_dict(cls, data: Any) -> Scenario:
        d = _object(data, {"name", "placements"}, "scenario", {"name", "placements"})
        return cls(_string(d["name"], "scenario.name", True),
                   {k: Placement.from_dict(v) for k, v in _mapping(d["placements"], "scenario.placements").items()})


@dataclass
class Project:
    name: str = "Untitled"
    timezone: str = "UTC"
    horizon_start: int = 0
    horizon_end: int = 0
    operations: dict[str, Operation] = field(default_factory=dict)
    machines: dict[str, Resource] = field(default_factory=dict)
    operators: dict[str, Resource] = field(default_factory=dict)
    scenarios: dict[str, Scenario] = field(default_factory=lambda: {"Baseline": Scenario("Baseline")})
    active_scenario: str = "Baseline"
    mappings: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def scenario(self) -> Scenario:
        return self.scenarios[self.active_scenario]

    def to_dict(self) -> dict:
        return {"name": self.name, "timezone": self.timezone, "horizon_start": self.horizon_start,
                "horizon_end": self.horizon_end,
                "operations": {k: v.to_dict() for k, v in self.operations.items()},
                "machines": {k: v.to_dict() for k, v in self.machines.items()},
                "operators": {k: v.to_dict() for k, v in self.operators.items()},
                "scenarios": {k: v.to_dict() for k, v in self.scenarios.items()},
                "active_scenario": self.active_scenario,
                "mappings": {k: dict(v) for k, v in self.mappings.items()}}

    @classmethod
    def from_dict(cls, data: Any) -> Project:
        d = _object(data, set(cls.__dataclass_fields__), "project", set(cls.__dataclass_fields__))
        objects = {}
        for name, kind, identity in (("operations", Operation, "id"), ("machines", Resource, "id"),
                                     ("operators", Resource, "id"), ("scenarios", Scenario, "name")):
            objects[name] = {k: kind.from_dict(v) for k, v in _mapping(d[name], f"project.{name}").items()}
            for key, obj in objects[name].items():
                if key != getattr(obj, identity):
                    raise ValueError(f"project.{name}: key {key!r} does not match {identity} {getattr(obj, identity)!r}")
        active = _string(d["active_scenario"], "project.active_scenario", True)
        if active not in objects["scenarios"]:
            raise ValueError("project.active_scenario: scenario does not exist")
        mappings = {k: {f: _string(v, f"project.mappings.{k}.{f}")
                        for f, v in _mapping(mapping, f"project.mappings.{k}").items()}
                    for k, mapping in _mapping(d["mappings"], "project.mappings").items()}
        return cls(name=_string(d["name"], "project.name"), timezone=_string(d["timezone"], "project.timezone", True),
                   horizon_start=_integer(d["horizon_start"], "project.horizon_start", True),
                   horizon_end=_integer(d["horizon_end"], "project.horizon_end", True),
                   active_scenario=active, mappings=mappings, **objects)
