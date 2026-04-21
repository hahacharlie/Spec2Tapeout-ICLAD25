from __future__ import annotations
import json
from pathlib import Path

from .models import Spec, ScoredCandidate
from .llm_client import llm_call, extract_code_block
from .prompts import build_optimizer_prompt, build_timing_closure_prompt
from .suite_utils import normalize_suite

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


def reference_metrics_path(problem_number: int, suite: str) -> Path:
    normalized_suite = normalize_suite(suite)
    return SCRIPT_DIR / normalized_suite / f"p{problem_number}" / f"p{problem_number}.json"


def score_candidate(
    candidate: ScoredCandidate,
    problem_number: int,
    flow_root: Path,
    suite: str,
) -> float:
    del flow_root  # Metrics are read directly from ORFS reports.

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
    candidate.metrics = submission

    # Check required keys exist
    required = ["timing__setup__ws", "timing__setup__tns", "power__total", "design__instance__area"]
    if not all(k in submission for k in required):
        missing = [k for k in required if k not in submission]
        print(f"  Metrics missing required keys: {missing}")
        return 0.0

    try:
        ref_path = reference_metrics_path(problem_number, suite)
        if not ref_path.exists():
            print(f"  No {normalize_suite(suite)} reference metrics for p{problem_number}")
            return 0.0

        with open(ref_path) as f:
            reference = json.load(f)

        score = _evaluate(submission, reference)
        candidate.score = score
        return score

    except Exception as e:
        print(f"  Scoring failed: {e}")
        return 0.0


def rank_candidates(candidates: list[ScoredCandidate]) -> list[ScoredCandidate]:
    return sorted(candidates, key=lambda c: c.score, reverse=True)



def _metric_as_float(value, default: float = float("-inf")) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default



def timing_values(candidate: ScoredCandidate) -> tuple[float, float]:
    metrics = candidate.metrics or {}
    return (
        _metric_as_float(metrics.get("timing__setup__ws")),
        _metric_as_float(metrics.get("timing__setup__tns")),
    )



def timing_is_closed(
    candidate: ScoredCandidate,
    wns_target: float = 0.0,
    tns_target: float = 0.0,
) -> bool:
    wns, tns = timing_values(candidate)
    if wns == float("-inf") or tns == float("-inf"):
        return False
    return wns >= wns_target and tns >= tns_target



def timing_violation_penalty(candidate: ScoredCandidate) -> float:
    wns, tns = timing_values(candidate)
    if wns == float("-inf") or tns == float("-inf"):
        return float("inf")
    return max(0.0, -wns) * 1000.0 + max(0.0, -tns)



def timing_sort_key(candidate: ScoredCandidate) -> tuple[float, float, float, float, float]:
    wns, tns = timing_values(candidate)
    closed = 1.0 if timing_is_closed(candidate) else 0.0
    penalty = timing_violation_penalty(candidate)
    return (closed, -penalty, wns, tns, candidate.score)



def rank_candidates_by_timing(candidates: list[ScoredCandidate]) -> list[ScoredCandidate]:
    return sorted(candidates, key=timing_sort_key, reverse=True)



def best_timing_candidate(candidates: list[ScoredCandidate]) -> ScoredCandidate:
    if not candidates:
        raise ValueError("No candidates provided")
    return max(candidates, key=timing_sort_key)



def is_timing_better(candidate: ScoredCandidate, baseline: ScoredCandidate) -> bool:
    return timing_sort_key(candidate) > timing_sort_key(baseline)


async def optimize_candidate(
    candidate: ScoredCandidate,
    spec: Spec,
    goal: str = "score",
    attempt: int = 1,
    timing_report: str | None = None,
    timing_only: bool = False,
    testbench_source: str | None = None,
    variant: str | None = None,
    prior_attempt_summary: str | None = None,
) -> str:
    if goal == "timing":
        system, prompt = build_timing_closure_prompt(
            rtl_source=candidate.rtl_source,
            metrics=candidate.metrics,
            spec=spec,
            attempt=attempt,
            timing_report=timing_report,
            timing_only=timing_only,
            testbench_source=testbench_source,
            variant=variant,
            prior_attempt_summary=prior_attempt_summary,
        )
    else:
        system, prompt = build_optimizer_prompt(
            rtl_source=candidate.rtl_source,
            metrics=candidate.metrics,
            score=candidate.score,
            spec=spec,
        )
    response = await llm_call(
        prompt,
        system,
        model="opus",
        purpose="timing_optimization" if goal == "timing" else "score_optimization",
    )
    return extract_code_block(response)
