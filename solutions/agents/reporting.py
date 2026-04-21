from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .models import Candidate, ScoredCandidate, Spec

LOG_PREVIEW_CHARS = 4000



def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()



def truncate_text(text: str, limit: int = LOG_PREVIEW_CHARS) -> str:
    if len(text) <= limit:
        return text
    head = max(0, limit // 2)
    tail = max(0, limit - head - len("\n...[truncated]...\n"))
    return text[:head] + "\n...[truncated]...\n" + text[-tail:]



def rtl_sha256(rtl_source: str) -> str:
    return hashlib.sha256(rtl_source.encode("utf-8")).hexdigest()



def strategy_parts(strategy: str) -> tuple[str, str | None]:
    if "__" not in strategy:
        return strategy, None
    return strategy.split("__", 1)



def make_problem_report(
    problem_num: int,
    yaml_path: Path,
    spec: Spec,
    testbench_path: Path | None,
    suite: str,
) -> dict:
    return {
        "problem": problem_num,
        "yaml": str(yaml_path),
        "suite": suite,
        "module_name": spec.module_name,
        "design_type": spec.design_type,
        "clock_period_ns": spec.clock_period,
        "status": "started",
        "testbench": str(testbench_path) if testbench_path is not None else None,
        "prompt_attempts": [],
        "candidates": [],
        "winner": None,
    }



def prompt_attempt_entry(
    *,
    stage: str,
    purpose: str,
    base_strategy: str,
    variant: str | None,
    label: str,
    status: str,
    generator: str,
    attempt: int | None = None,
    source_strategy: str | None = None,
    error: str | None = None,
    note: str | None = None,
) -> dict:
    return {
        "timestamp": utc_now_iso(),
        "stage": stage,
        "purpose": purpose,
        "base_strategy": base_strategy,
        "variant": variant,
        "label": label,
        "status": status,
        "generator": generator,
        "attempt": attempt,
        "source_strategy": source_strategy,
        "error": truncate_text(error or "") if error else None,
        "note": note,
    }



def apply_candidate_metadata(scored: ScoredCandidate, candidate: Candidate) -> ScoredCandidate:
    scored.strategy = candidate.strategy
    scored.base_strategy = candidate.base_strategy
    scored.variant = candidate.variant
    scored.origin = candidate.origin
    scored.source_strategy = candidate.source_strategy
    scored.llm_purpose = candidate.llm_purpose
    scored.generator = candidate.generator
    return scored



def candidate_report_entry(
    candidate: Candidate,
    scored: ScoredCandidate | None = None,
    *,
    orfs_status: str = "not_run",
) -> dict:
    wns = None
    tns = None
    score = None
    metrics = None
    odb_path = None
    sdc_path = None
    v_path = None
    if scored is not None:
        metrics = scored.metrics
        score = scored.score
        odb_path = str(scored.odb_path) if scored.odb_path is not None else None
        sdc_path = str(scored.sdc_path) if scored.sdc_path is not None else None
        v_path = str(scored.v_path) if scored.v_path is not None else None
        wns = scored.metrics.get("timing__setup__ws") if scored.metrics else None
        tns = scored.metrics.get("timing__setup__tns") if scored.metrics else None
        orfs_status = "success"

    base_strategy, parsed_variant = strategy_parts(candidate.strategy)
    return {
        "strategy": candidate.strategy,
        "base_strategy": candidate.base_strategy or base_strategy,
        "variant": candidate.variant or parsed_variant,
        "origin": candidate.origin,
        "source_strategy": candidate.source_strategy,
        "generator": candidate.generator,
        "llm_purpose": candidate.llm_purpose,
        "selected": False,
        "selected_reason": None,
        "rtl": {
            "sha256": rtl_sha256(candidate.rtl_source),
            "line_count": len(candidate.rtl_source.splitlines()),
            "char_count": len(candidate.rtl_source),
        },
        "verification": {
            "passed": candidate.passed,
            "retry_count": candidate.retry_count,
            "attempts": candidate.verification_attempts,
            "compile_log": truncate_text(candidate.compile_log),
            "sim_log": truncate_text(candidate.sim_log),
        },
        "orfs": {
            "status": orfs_status,
            "score": score,
            "wns": wns,
            "tns": tns,
            "odb_path": odb_path,
            "sdc_path": sdc_path,
            "v_path": v_path,
            "metrics": metrics,
        },
    }



def mark_selected_candidate(problem_report: dict, strategy: str, reason: str) -> None:
    winner_entry = None
    for candidate in problem_report["candidates"]:
        if candidate["strategy"] == strategy:
            candidate["selected"] = True
            candidate["selected_reason"] = reason
            winner_entry = candidate
            break

    if winner_entry is None:
        problem_report["winner"] = {
            "strategy": strategy,
            "reason": reason,
        }
        return

    problem_report["winner"] = {
        "strategy": winner_entry["strategy"],
        "base_strategy": winner_entry["base_strategy"],
        "variant": winner_entry["variant"],
        "origin": winner_entry["origin"],
        "source_strategy": winner_entry["source_strategy"],
        "generator": winner_entry["generator"],
        "score": winner_entry["orfs"]["score"],
        "wns": winner_entry["orfs"]["wns"],
        "tns": winner_entry["orfs"]["tns"],
        "reason": reason,
    }



def run_report_header(report_path: Path) -> dict:
    return {
        "generated_at": utc_now_iso(),
        "report_path": str(report_path),
        "problems": [],
    }



def write_run_report(report_path: Path, report: dict) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=False))
