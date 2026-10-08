"""Keep native-shell exit codes authoritative in the release workflow."""

import re
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"


@pytest.mark.parametrize("condition", ["runner.os == 'Linux'", "runner.os != 'Linux'"])
def test_tests_smoke_and_packaging_have_independent_success_gates(condition):
    source = WORKFLOW.read_text(encoding="utf-8")
    # Inspect this repository's fixed indentation, without adding a YAML dependency.
    steps = re.findall(r"^      - .*?(?=^      - |\Z)", source, re.MULTILINE | re.DOTALL)
    gated_steps = []
    for command in ("pytest -q", "--smoke-test build/source-smoke", "scripts/build_release.py"):
        matches = [step for step in steps if command in step and f"        if: {condition}\n" in step]
        assert len(matches) == 1, f"Expected one {condition} step for {command}"
        step = matches[0]
        # A single command lets Actions observe pytest's exit code under pwsh too.
        runs = re.findall(r"^        run: (.+)$", step, re.MULTILINE)
        assert len(runs) == 1 and command in runs[0]
        assert not any(token in runs[0] for token in (";", "&&", "||"))
        assert not re.search(r"^          \S", step, re.MULTILINE)
        assert "continue-on-error:" not in step
        gated_steps.append(steps.index(step))
    assert gated_steps == sorted(set(gated_steps)), "Tests must gate smoke, then packaging"
    # A job-level override would also permit failed tests to be reported as passing.
    assert "continue-on-error:" not in source
