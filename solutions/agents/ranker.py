from __future__ import annotations
import json
from pathlib import Path

from .models import Spec, ScoredCandidate
from .llm_client import llm_call, extract_code_block
from .prompts import build_optimizer_prompt

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


def _find_orfs_report(odb_path: Path) -> Path | None:
    """Find 6_report.json from the ORFS workspace given the odb path.

    ORFS layout:
      workspace/pN/orfs_strategy/results/sky130hd/<design>/base/6_final.odb
      workspace/pN/orfs_strategy/logs/sky130hd/<design>/base/6_report.json
    """
    odb_str = str(odb_path)

    # Primary: swap results/ -> logs/ and 6_final.odb -> 6_report.json
    if "/results/" in odb_str:
        report = Path(
            odb_str.replace("/results/", "/logs/")
                   .replace("6_final.odb", "6_report.json")
        )
        if report.exists():
            return report

    # Fallback: search sibling logs directory
    for parent in odb_path.parents:
        if parent.name in ("results", "base"):
            logs_root = parent.parent / "logs" if parent.name == "results" else None
            if logs_root is None:
                for p2 in parent.parents:
                    if p2.name == "results":
                        logs_root = Path(str(p2).replace("/results", "/logs"))
                        break
            if logs_root and logs_root.exists():
                for p in logs_root.rglob("6_report.json"):
                    return p
            break
    return None


def _load_orfs_metrics(report_path: Path) -> dict | None:
    """Load metrics from ORFS 6_report.json, stripping the finish__ prefix."""
    try:
        with open(report_path) as f:
            raw = json.load(f)
        # Strip the 'finish__' prefix ORFS adds to metric keys
        return {
            k.replace("finish__", "", 1): v
            for k, v in raw.items()
        }
    except Exception as e:
        print(f"  Failed to load metrics from {report_path}: {e}")
        return None


def score_candidate(
    candidate: ScoredCandidate,
    problem_number: int,
    flow_root: Path,
) -> float:
    if candidate.odb_path is None:
        return 0.0

    # Read metrics directly from ORFS output (no extra Docker needed)
    report_path = _find_orfs_report(candidate.odb_path)
    if report_path is None:
        print(f"  No 6_report.json found for {candidate.odb_path}")
        return 0.0

    submission = _load_orfs_metrics(report_path)
    if submission is None:
        return 0.0

    # Check required keys exist
    required = ["timing__setup__ws", "timing__setup__tns", "power__total", "design__instance__area"]
    if not all(k in submission for k in required):
        missing = [k for k in required if k not in submission]
        print(f"  Metrics missing required keys: {missing}")
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
