import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.models import Candidate, Port, ScoredCandidate, Spec
from agents.reporting import (
    apply_candidate_metadata,
    candidate_report_entry,
    make_problem_report,
    mark_selected_candidate,
    prompt_attempt_entry,
    write_run_report,
)



def _dummy_spec() -> Spec:
    return Spec(
        module_name="demo",
        design_type="combinational",
        clock_period=3.5,
        ports=[
            Port(name="a", direction="input", type="logic", description="a"),
            Port(name="b", direction="input", type="logic", description="b"),
            Port(name="y", direction="output", type="logic", description="y"),
        ],
        parameters={},
        module_signature="module demo(input logic a, input logic b, output logic y);",
        description="demo",
        yaml_raw={},
    )



def test_prompt_attempt_entry_contains_variant_and_status():
    entry = prompt_attempt_entry(
        stage="timing_repair",
        purpose="timing_optimization",
        base_strategy="timing_fix",
        variant="balanced_multiplier",
        label="timing_fix_1__balanced_multiplier",
        status="generated",
        generator="llm",
        attempt=1,
        source_strategy="timing_opt__balanced_reduction",
    )
    assert entry["variant"] == "balanced_multiplier"
    assert entry["status"] == "generated"
    assert entry["source_strategy"] == "timing_opt__balanced_reduction"



def test_candidate_report_entry_includes_verification_and_orfs():
    candidate = Candidate(
        rtl_source="module demo; endmodule",
        strategy="timing_opt__balanced_tree",
        passed=True,
        compile_log="compile ok",
        sim_log="PASS",
        base_strategy="timing_opt",
        variant="balanced_tree",
        origin="initial_generation",
        llm_purpose="rtl_generation",
        generator="llm",
        verification_attempts=[{"attempt": 0, "compile_ok": True, "passed": True}],
    )
    scored = ScoredCandidate(
        rtl_source=candidate.rtl_source,
        strategy=candidate.strategy,
        score=88.5,
        metrics={
            "timing__setup__ws": 0.12,
            "timing__setup__tns": 0.0,
            "power__total": 0.01,
            "design__instance__area": 1234,
        },
    )
    apply_candidate_metadata(scored, candidate)
    entry = candidate_report_entry(candidate, scored)
    assert entry["strategy"] == "timing_opt__balanced_tree"
    assert entry["base_strategy"] == "timing_opt"
    assert entry["variant"] == "balanced_tree"
    assert entry["verification"]["passed"] is True
    assert entry["orfs"]["status"] == "success"
    assert entry["orfs"]["score"] == 88.5



def test_make_problem_report_and_mark_selected(tmp_path):
    report = make_problem_report(
        8,
        tmp_path / "p8.yaml",
        _dummy_spec(),
        tmp_path / "tb.v",
        "visible",
    )
    candidate = Candidate(rtl_source="module demo; endmodule", strategy="textbook")
    report["candidates"].append(candidate_report_entry(candidate, orfs_status="failed"))
    mark_selected_candidate(report, "textbook", "final_output")
    assert report["winner"]["strategy"] == "textbook"
    assert report["suite"] == "visible"
    assert report["candidates"][0]["selected"] is True



def test_write_run_report(tmp_path):
    report_path = tmp_path / "run_report.json"
    report = {"problems": [{"problem": 1, "status": "success"}]}
    write_run_report(report_path, report)
    loaded = json.loads(report_path.read_text())
    assert loaded["problems"][0]["problem"] == 1
