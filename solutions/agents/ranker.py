from __future__ import annotations
import json
import subprocess
import tempfile
from pathlib import Path

from .models import Spec, ScoredCandidate
from .llm_client import llm_call, extract_code_block
from .prompts import build_optimizer_prompt
from .orfs_runner import DOCKER_IMAGE

SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent / "evaluation"


def _evaluate(submission: dict, reference: dict) -> float:
    """Score submission metrics against reference (from evaluate_openroad.py)."""
    baseline_wns = 30
    baseline_tns = 15
    baseline_power = 15
    baseline_area = 15
    score = 0.0

    # WNS (40 pts total, 30 baseline)
    wns = submission["timing__setup__ws"]
    ref_wns = reference["timing__setup__ws"]
    if wns >= ref_wns:
        wns_bonus = min(10, 40 * (wns - ref_wns))
    else:
        wns_bonus = -min(10, 40 * (ref_wns - wns))
    score += baseline_wns + wns_bonus

    # TNS (20 pts total, 15 baseline)
    tns = submission["timing__setup__tns"]
    ref_tns = reference["timing__setup__tns"]
    if tns <= ref_tns:
        tns_bonus = 5 * ((ref_tns - tns) / abs(ref_tns)) if ref_tns != 0 else 5
    else:
        tns_bonus = -5 * ((tns - ref_tns) / abs(ref_tns)) if ref_tns != 0 else -5
    score += max(0, min(baseline_tns + tns_bonus, baseline_tns + 5))

    # Power (20 pts)
    ref_power = reference["power__total"]
    sub_power = submission["power__total"]
    power_ratio = ref_power / sub_power
    if power_ratio >= 1:
        score += baseline_power + min(5, 20 * (power_ratio - 1))
    else:
        score += baseline_power - min(5, 20 * (1 - power_ratio))

    # Area (20 pts)
    ref_area = reference["design__instance__area"]
    sub_area = submission["design__instance__area"]
    area_ratio = ref_area / sub_area
    if area_ratio >= 1:
        score += baseline_area + min(5, 20 * (area_ratio - 1))
    else:
        score += baseline_area - min(5, 20 * (1 - area_ratio))

    return min(score, 100)


def _extract_metrics_via_docker(odb_path: Path, sdc_path: Path) -> dict | None:
    """Run OpenROAD inside Docker to extract metrics from ODB."""
    eval_tcl = SCRIPT_DIR / "report_metrics.tcl"
    if not eval_tcl.exists():
        print(f"  report_metrics.tcl not found at {eval_tcl}")
        return None

    # Create a temp dir for scoring artifacts
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        metrics_file = tmp_path / "metrics.json"

        # Write the wrapper TCL that sets variables and sources the eval script
        wrapper_tcl = tmp_path / "run_metrics.tcl"
        wrapper_tcl.write_text(f"""
set odb_path "/scoring/design.odb"
set sdc_path "/scoring/design.sdc"
set flow_root "/OpenROAD-flow-scripts"
source "/scoring/report_metrics.tcl"
""")

        cmd = [
            "docker", "run", "--rm",
            "-v", f"{odb_path.resolve()}:/scoring/design.odb:ro",
            "-v", f"{sdc_path.resolve()}:/scoring/design.sdc:ro",
            "-v", f"{eval_tcl.resolve()}:/scoring/report_metrics.tcl:ro",
            "-v", f"{wrapper_tcl.resolve()}:/scoring/run_metrics.tcl:ro",
            "-v", f"{tmp_path.resolve()}:/scoring/output",
            DOCKER_IMAGE,
            "bash", "-c",
            "/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/openroad"
            " -metrics /scoring/output/metrics.json -exit /scoring/run_metrics.tcl",
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if not metrics_file.exists():
                print(f"  Docker scoring produced no metrics.json (exit {result.returncode})")
                if result.stderr:
                    print(f"  stderr: {result.stderr[-300:]}")
                return None

            with open(metrics_file) as f:
                return json.load(f)

        except subprocess.TimeoutExpired:
            print("  Docker scoring timed out")
            return None
        except Exception as e:
            print(f"  Docker scoring failed: {e}")
            return None


def score_candidate(
    candidate: ScoredCandidate,
    problem_number: int,
    flow_root: Path,
) -> float:
    if candidate.odb_path is None or candidate.sdc_path is None:
        return 0.0

    # Extract metrics by running OpenROAD inside Docker
    submission = _extract_metrics_via_docker(candidate.odb_path, candidate.sdc_path)
    if submission is None:
        return 0.0

    try:
        ref_path = SCRIPT_DIR / "visible" / f"p{problem_number}" / f"p{problem_number}.json"
        if not ref_path.exists():
            ref_path = SCRIPT_DIR / "hidden" / f"p{problem_number}" / f"p{problem_number}.json"
        if not ref_path.exists():
            print(f"  No reference metrics for p{problem_number}")
            return 0.0

        with open(ref_path) as f:
            reference = json.load(f)

        score = _evaluate(submission, reference)
        candidate.score = score
        candidate.metrics = submission
        return score

    except Exception as e:
        print(f"  Scoring failed: {e}")
        return 0.0


def rank_candidates(candidates: list[ScoredCandidate]) -> list[ScoredCandidate]:
    return sorted(candidates, key=lambda c: c.score, reverse=True)


async def optimize_candidate(
    candidate: ScoredCandidate,
    spec: Spec,
) -> str:
    system, prompt = build_optimizer_prompt(
        rtl_source=candidate.rtl_source,
        metrics=candidate.metrics,
        score=candidate.score,
        spec=spec,
    )
    response = await llm_call(prompt, system, model="opus")
    return extract_code_block(response)
