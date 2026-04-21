import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agents.ranker as ranker
from agents.suite_utils import (
    default_output_dir_for_suite,
    default_workspace_dir_for_suite,
    infer_suite_from_problem_path,
    resolve_run_suite,
)
from spec2tapeout_agent import find_testbench


def test_infer_suite_from_problem_path():
    assert infer_suite_from_problem_path(Path("problems/visible/p1.yaml")) == "visible"
    assert infer_suite_from_problem_path(Path("problems/hidden/p1.yaml")) == "hidden"
    assert infer_suite_from_problem_path(Path("p1.yaml")) is None


def test_resolve_run_suite_rejects_mixed_problem_suites():
    with pytest.raises(ValueError, match="Mixed suites"):
        resolve_run_suite(
            [
                Path("problems/visible/p1.yaml"),
                Path("problems/hidden/p5.yaml"),
            ]
        )


def test_resolve_run_suite_requires_explicit_suite_for_unscoped_paths():
    with pytest.raises(ValueError, match="Pass --suite"):
        resolve_run_suite([Path("/tmp/p1.yaml")])

    assert resolve_run_suite([Path("/tmp/p1.yaml")], "hidden") == "hidden"


def test_default_dirs_are_suite_scoped():
    assert default_output_dir_for_suite("visible") == Path("solutions/visible")
    assert default_output_dir_for_suite("hidden") == Path("solutions/hidden")
    assert default_workspace_dir_for_suite("visible") == Path(
        "solutions/workspace/visible"
    )
    assert default_workspace_dir_for_suite("hidden") == Path(
        "solutions/workspace/hidden"
    )


def test_find_testbench_honors_requested_suite(tmp_path):
    visible_tb = tmp_path / "evaluation" / "visible" / "p1" / "tb_visible.v"
    hidden_tb = tmp_path / "evaluation" / "hidden" / "p1" / "tb_hidden.v"
    visible_tb.parent.mkdir(parents=True)
    hidden_tb.parent.mkdir(parents=True)
    visible_tb.write_text("// visible")
    hidden_tb.write_text("// hidden")

    assert find_testbench(1, tmp_path, "visible") == visible_tb
    assert find_testbench(1, tmp_path, "hidden") == hidden_tb


def test_reference_metrics_path_uses_requested_suite(monkeypatch, tmp_path):
    monkeypatch.setattr(ranker, "SCRIPT_DIR", tmp_path)

    visible_ref = tmp_path / "visible" / "p1" / "p1.json"
    hidden_ref = tmp_path / "hidden" / "p1" / "p1.json"
    visible_ref.parent.mkdir(parents=True)
    hidden_ref.parent.mkdir(parents=True)
    visible_ref.write_text("{}")
    hidden_ref.write_text("{}")

    assert ranker.reference_metrics_path(1, "visible") == visible_ref
    assert ranker.reference_metrics_path(1, "hidden") == hidden_ref
