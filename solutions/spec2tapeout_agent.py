#!/usr/bin/env python3
"""Multi-agent Spec-to-Tapeout pipeline.

Usage:
    python spec2tapeout_agent.py --problems problems/visible/*.yaml --output solutions/visible/
"""

from __future__ import annotations

import argparse
import asyncio
import re
import shutil
from pathlib import Path

from agents.models import Candidate, ScoredCandidate, Spec
from agents.orfs_runner import run_orfs_with_retry
from agents.prompts import get_timing_repair_variants
from agents.ranker import (
    best_timing_candidate,
    is_timing_better,
    optimize_candidate,
    rank_candidates,
    rank_candidates_by_timing,
    score_candidate,
    timing_is_closed,
)
from agents.reporting import (
    apply_candidate_metadata,
    candidate_report_entry,
    make_problem_report,
    mark_selected_candidate,
    prompt_attempt_entry,
    run_report_header,
    truncate_text,
    write_run_report,
)
from agents.rtl_fixer import fix_rtl
from agents.rtl_generator import STRATEGIES, generate_rtl_candidates
from agents.sdc_config_generator import (
    generate_config_mk,
    generate_sdc,
    tighten_physical_config,
)
from agents.suite_utils import (
    VALID_SUITES,
    default_output_dir_for_suite,
    default_workspace_dir_for_suite,
    normalize_suite,
    resolve_run_suite,
)
from agents.spec_interpreter import parse_spec
from agents.timing_feedback import get_timing_diagnostics
from agents.verification import verify_candidate

MAX_FIX_RETRIES = 5
ORFS_CONCURRENCY = 3
OPTIMIZATION_THRESHOLD = 85
MAX_TIMING_FIX_ROUNDS = 5
TIMING_ONLY_MAX_ROUNDS = 6
TIMING_ONLY_PROBLEM_NUMBERS = {8, 9}


def get_problem_number(yaml_path: Path) -> int:
    match = re.search(r"p(\d+)", yaml_path.stem)
    if match:
        return int(match.group(1))
    raise ValueError(f"Cannot extract problem number from {yaml_path}")


def find_testbench(problem_number: int, base_dir: Path, suite: str) -> Path | None:
    eval_dir = (
        base_dir
        / "evaluation"
        / normalize_suite(suite)
        / f"p{problem_number}"
    )
    if not eval_dir.exists():
        return None
    tbs = list(eval_dir.glob("*.v"))
    return tbs[0] if tbs else None


def _format_metric(value) -> str:
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "N/A"


def timing_summary(candidate: ScoredCandidate) -> str:
    metrics = candidate.metrics or {}
    return (
        f"WNS={_format_metric(metrics.get('timing__setup__ws'))}ns, "
        f"TNS={_format_metric(metrics.get('timing__setup__tns'))}ns"
    )


def verification_attempt_record(
    attempt: int,
    compile_ok: bool,
    passed: bool,
    compile_log: str,
    sim_log: str,
) -> dict:
    return {
        "attempt": attempt,
        "compile_ok": compile_ok,
        "passed": passed,
        "compile_log": truncate_text(compile_log),
        "sim_log": truncate_text(sim_log),
    }


def timing_only_mode_enabled(problem_num: int) -> bool:
    return problem_num in TIMING_ONLY_PROBLEM_NUMBERS


async def verify_and_fix(
    candidate: Candidate,
    spec: Spec,
    testbench_path: Path,
    work_dir: Path,
) -> Candidate:
    tb_source = testbench_path.read_text()
    current = candidate

    for attempt in range(MAX_FIX_RETRIES + 1):
        passed, compile_log, sim_log = await verify_candidate(
            current.rtl_source,
            testbench_path,
            work_dir / f"verify_{attempt}",
        )
        compile_ok = not (compile_log and "error" in compile_log.lower())
        current.verification_attempts.append(
            verification_attempt_record(
                attempt=attempt,
                compile_ok=compile_ok,
                passed=passed,
                compile_log=compile_log,
                sim_log=sim_log,
            )
        )

        if passed:
            current.passed = True
            current.compile_log = compile_log
            current.sim_log = sim_log
            print(
                f"  [{spec.module_name}] Strategy '{current.strategy}' PASSED (attempt {attempt})"
            )
            return current

        error_log = compile_log + sim_log
        if attempt < MAX_FIX_RETRIES:
            error_type = (
                "compilation" if "error" in compile_log.lower() else "simulation"
            )
            current = await fix_rtl(current, spec, error_log, tb_source, error_type)
        else:
            current.passed = False
            current.compile_log = compile_log
            current.sim_log = sim_log

    print(
        f"  [{spec.module_name}] Strategy '{current.strategy}' FAILED after {MAX_FIX_RETRIES} retries"
    )
    return current


async def emergency_regenerate(
    spec: Spec,
    failed_candidates: list[Candidate],
    testbench_path: Path,
    work_dir: Path,
    problem_report: dict | None = None,
) -> list[Candidate]:
    print(f"  [{spec.module_name}] Emergency regeneration...")
    error_context = "\n".join(
        f"Strategy {c.strategy} errors:\n{c.compile_log}\n{c.sim_log}"
        for c in failed_candidates
    )

    from agents.llm_client import extract_code_block, llm_call
    from agents.prompts import build_rtl_prompt

    system, prompt = build_rtl_prompt(spec, "textbook")
    prompt += f"\n\nPrevious attempts failed with these errors (avoid them):\n{error_context[:2000]}"

    try:
        response = await llm_call(
            prompt, system, model="opus", purpose="rtl_generation"
        )
        rtl_source = extract_code_block(response)
        if problem_report is not None:
            problem_report["prompt_attempts"].append(
                prompt_attempt_entry(
                    stage="emergency_regeneration",
                    purpose="rtl_generation",
                    base_strategy="textbook",
                    variant=None,
                    label="emergency",
                    status="generated",
                    generator="llm",
                )
            )
    except Exception as e:
        if problem_report is not None:
            problem_report["prompt_attempts"].append(
                prompt_attempt_entry(
                    stage="emergency_regeneration",
                    purpose="rtl_generation",
                    base_strategy="textbook",
                    variant=None,
                    label="emergency",
                    status="failed",
                    generator="llm",
                    error=str(e),
                )
            )
        raise

    candidate = Candidate(
        rtl_source=rtl_source,
        strategy="emergency",
        base_strategy="textbook",
        origin="emergency_regeneration",
        llm_purpose="rtl_generation",
        generator="llm",
    )
    result = await verify_and_fix(
        candidate, spec, testbench_path, work_dir / "emergency"
    )

    return [result] if result.passed else []


def summarize_timing_attempt_history(history: list[dict]) -> str:
    if not history:
        return ""
    lines = []
    for item in history[-8:]:
        variant = item.get("variant") or "baseline"
        outcome = item.get("outcome", "unknown")
        timing = item.get("timing", "")
        note = item.get("note", "")
        lines.append(
            f"attempt {item.get('attempt')} variant {variant}: {outcome}; {timing} {note}".strip()
        )
    return "\n".join(lines)


async def attempt_timing_closure(
    best: ScoredCandidate,
    scored_candidates: list[ScoredCandidate],
    spec: Spec,
    problem_num: int,
    suite: str,
    testbench_path: Path,
    prob_workspace: Path,
    sdc_content: str,
    config_content: str,
    flow_root: Path,
    orfs_semaphore: asyncio.Semaphore,
    problem_report: dict,
) -> ScoredCandidate:
    if timing_is_closed(best):
        return best

    tb_source = testbench_path.read_text()
    timing_only = timing_only_mode_enabled(problem_num)
    max_rounds = TIMING_ONLY_MAX_ROUNDS if timing_only else MAX_TIMING_FIX_ROUNDS
    seed_pool = rank_candidates_by_timing(scored_candidates)
    current_seed_index = 0
    current = best_timing_candidate(scored_candidates)
    best_seen = current
    stale_attempts = 0
    attempt_history: list[dict] = []

    print(
        f"[P{problem_num}] Timing not closed for best-score candidate ({timing_summary(best)})."
    )
    if timing_only:
        print(f"[P{problem_num}] Entering multi-round timing-only mode")
    if current.strategy != best.strategy:
        print(
            f"[P{problem_num}] Using best-timing seed '{current.strategy}' "
            f"instead of best-score '{best.strategy}' ({timing_summary(current)})."
        )

    for attempt in range(1, max_rounds + 1):
        if timing_is_closed(current):
            return current

        print(
            f"[P{problem_num}] Timing repair attempt {attempt}/{max_rounds} "
            f"from strategy '{current.strategy}' ({timing_summary(current)})"
        )

        timing_report = get_timing_diagnostics(current, flow_root)
        if timing_report:
            print(
                f"[P{problem_num}] Collected OpenROAD timing diagnostics for prompt guidance"
            )

        prior_attempt_summary = summarize_timing_attempt_history(attempt_history)
        variant_names = get_timing_repair_variants(spec, attempt)
        proposed_candidates: list[Candidate] = []
        seen_rtl_sources: set[str] = set()

        for variant in variant_names:
            label = (
                f"timing_fix_{attempt}"
                if variant is None
                else f"timing_fix_{attempt}__{variant}"
            )
            try:
                repaired_rtl = await optimize_candidate(
                    current,
                    spec,
                    goal="timing",
                    attempt=attempt,
                    timing_report=timing_report,
                    timing_only=timing_only,
                    testbench_source=tb_source,
                    variant=variant,
                    prior_attempt_summary=prior_attempt_summary,
                )
            except Exception as e:
                attempt_history.append(
                    {
                        "attempt": attempt,
                        "variant": variant,
                        "outcome": "api_failed",
                        "timing": timing_summary(current),
                        "note": str(e)[:160],
                    }
                )
                problem_report["prompt_attempts"].append(
                    prompt_attempt_entry(
                        stage="timing_repair",
                        purpose="timing_optimization",
                        base_strategy="timing_fix",
                        variant=variant,
                        label=label,
                        status="failed",
                        generator="llm",
                        attempt=attempt,
                        source_strategy=current.strategy,
                        error=str(e),
                    )
                )
                print(
                    f"[P{problem_num}] Timing optimization call failed for variant {variant or 'baseline'}: {e}"
                )
                continue

            if repaired_rtl in seen_rtl_sources:
                problem_report["prompt_attempts"].append(
                    prompt_attempt_entry(
                        stage="timing_repair",
                        purpose="timing_optimization",
                        base_strategy="timing_fix",
                        variant=variant,
                        label=label,
                        status="duplicate_filtered",
                        generator="llm",
                        attempt=attempt,
                        source_strategy=current.strategy,
                    )
                )
                continue
            seen_rtl_sources.add(repaired_rtl)
            problem_report["prompt_attempts"].append(
                prompt_attempt_entry(
                    stage="timing_repair",
                    purpose="timing_optimization",
                    base_strategy="timing_fix",
                    variant=variant,
                    label=label,
                    status="generated",
                    generator="llm",
                    attempt=attempt,
                    source_strategy=current.strategy,
                )
            )
            proposed_candidates.append(
                Candidate(
                    rtl_source=repaired_rtl,
                    strategy=label,
                    base_strategy="timing_fix",
                    variant=variant,
                    origin="timing_repair",
                    source_strategy=current.strategy,
                    llm_purpose="timing_optimization",
                    generator="llm",
                )
            )

        if not proposed_candidates:
            stale_attempts += 1
            if timing_only and current_seed_index + 1 < len(seed_pool):
                current_seed_index += 1
                current = seed_pool[current_seed_index]
                stale_attempts = 0
                print(
                    f"[P{problem_num}] Switching timing-only seed to '{current.strategy}' "
                    f"({timing_summary(current)})"
                )
                continue
            break

        verified_variants = await asyncio.gather(
            *[
                verify_and_fix(
                    candidate,
                    spec,
                    testbench_path,
                    prob_workspace / f"candidate_{candidate.strategy}",
                )
                for candidate in proposed_candidates
            ]
        )
        verified_passing = [
            candidate for candidate in verified_variants if candidate.passed
        ]
        for candidate in verified_variants:
            if not candidate.passed:
                attempt_history.append(
                    {
                        "attempt": attempt,
                        "variant": candidate.strategy.split("__", 1)[1]
                        if "__" in candidate.strategy
                        else None,
                        "outcome": "verify_failed",
                        "timing": timing_summary(current),
                        "note": "functional verification failed",
                    }
                )
                problem_report["candidates"].append(
                    candidate_report_entry(candidate, orfs_status="not_run")
                )

        if not verified_passing:
            stale_attempts += 1
            print(
                f"[P{problem_num}] All timing repair variants failed verification on attempt {attempt}"
            )
            if (
                timing_only
                and stale_attempts >= 1
                and current_seed_index + 1 < len(seed_pool)
            ):
                current_seed_index += 1
                current = seed_pool[current_seed_index]
                stale_attempts = 0
                print(
                    f"[P{problem_num}] Switching timing-only seed to '{current.strategy}' "
                    f"({timing_summary(current)})"
                )
            continue

        if timing_only:
            timing_config = tighten_physical_config(
                config_content,
                attempt=attempt + 1,
                util_step=7,
                density_step=0.07,
                min_density=0.35,
            )
        else:
            timing_config = tighten_physical_config(config_content, attempt=attempt)

        scored_variants = await asyncio.gather(
            *[
                run_orfs_with_retry(
                    candidate.rtl_source,
                    sdc_content,
                    timing_config,
                    spec,
                    prob_workspace / f"orfs_{candidate.strategy}",
                    orfs_semaphore,
                )
                for candidate in verified_passing
            ]
        )

        successful_variants: list[ScoredCandidate] = []
        for verified_candidate, scored_variant in zip(
            verified_passing, scored_variants
        ):
            if scored_variant is None:
                attempt_history.append(
                    {
                        "attempt": attempt,
                        "variant": verified_candidate.strategy.split("__", 1)[1]
                        if "__" in verified_candidate.strategy
                        else None,
                        "outcome": "orfs_failed",
                        "timing": timing_summary(current),
                    }
                )
                problem_report["candidates"].append(
                    candidate_report_entry(verified_candidate, orfs_status="failed")
                )
                continue
            apply_candidate_metadata(scored_variant, verified_candidate)
            score_candidate(scored_variant, problem_num, flow_root, suite)
            successful_variants.append(scored_variant)
            problem_report["candidates"].append(
                candidate_report_entry(verified_candidate, scored_variant)
            )
            attempt_history.append(
                {
                    "attempt": attempt,
                    "variant": verified_candidate.strategy.split("__", 1)[1]
                    if "__" in verified_candidate.strategy
                    else None,
                    "outcome": "scored",
                    "timing": timing_summary(scored_variant),
                    "note": f"score={scored_variant.score:.2f}",
                }
            )

        if not successful_variants:
            stale_attempts += 1
            print(
                f"[P{problem_num}] Timing repair attempt {attempt} failed in ORFS for all variants"
            )
            if (
                timing_only
                and stale_attempts >= 1
                and current_seed_index + 1 < len(seed_pool)
            ):
                current_seed_index += 1
                current = seed_pool[current_seed_index]
                stale_attempts = 0
                print(
                    f"[P{problem_num}] Switching timing-only seed to '{current.strategy}' "
                    f"({timing_summary(current)})"
                )
            continue

        repaired_scored = best_timing_candidate(successful_variants)
        print(
            f"[P{problem_num}] Best timing repair variant result: score={repaired_scored.score}/100, "
            f"{timing_summary(repaired_scored)} (strategy {repaired_scored.strategy})"
        )

        if is_timing_better(repaired_scored, best_seen):
            best_seen = repaired_scored

        if timing_is_closed(repaired_scored):
            print(f"[P{problem_num}] Timing closed on attempt {attempt}")
            return repaired_scored

        if is_timing_better(repaired_scored, current):
            current = repaired_scored
            stale_attempts = 0
        else:
            stale_attempts += 1
            if timing_only and current_seed_index + 1 < len(seed_pool):
                current_seed_index += 1
                current = seed_pool[current_seed_index]
                stale_attempts = 0
                print(
                    f"[P{problem_num}] Timing did not improve; switching timing-only seed to "
                    f"'{current.strategy}' ({timing_summary(current)})"
                )
            else:
                print(
                    f"[P{problem_num}] Timing did not improve on attempt {attempt}; keeping prior seed"
                )

    print(
        f"[P{problem_num}] Timing still open after {max_rounds} attempts; "
        f"best seen remains {timing_summary(best_seen)}"
    )
    return best_seen


async def solve_problem(
    yaml_path: Path,
    output_dir: Path,
    workspace_dir: Path,
    base_dir: Path,
    flow_root: Path,
    suite: str,
    orfs_semaphore: asyncio.Semaphore,
) -> dict:
    problem_num = get_problem_number(yaml_path)
    print(f"\n{'=' * 60}")
    print(f"[P{problem_num}] Starting pipeline for {yaml_path.name}")
    print(f"{'=' * 60}")

    # Phase 1: Parse
    spec = parse_spec(yaml_path)
    sdc_content = generate_sdc(spec)
    config_content = generate_config_mk(spec)
    print(
        f"[P{problem_num}] Parsed: {spec.module_name} ({spec.design_type}), clock={spec.clock_period}ns"
    )

    testbench_path = find_testbench(problem_num, base_dir, suite)
    problem_report = make_problem_report(
        problem_num,
        yaml_path,
        spec,
        testbench_path,
        suite,
    )
    if testbench_path is None:
        print(f"[P{problem_num}] WARNING: No testbench found, skipping verification")
        problem_report["status"] = "no_testbench"
        return {
            "problem": problem_num,
            "score": 0,
            "status": "no_testbench",
            "report": problem_report,
        }

    prob_workspace = workspace_dir / f"p{problem_num}"
    prob_workspace.mkdir(parents=True, exist_ok=True)

    # Phase 2: Generate initial candidates
    print(
        f"[P{problem_num}] Generating RTL candidates from {len(STRATEGIES)} base strategies..."
    )
    candidates, generation_events = await generate_rtl_candidates(spec)
    for event in generation_events:
        problem_report["prompt_attempts"].append(prompt_attempt_entry(**event))
    print(f"[P{problem_num}] Generated {len(candidates)} unique RTL candidates")

    # Phase 3: Verify + fix loop in parallel
    print(f"[P{problem_num}] Verifying candidates...")
    verified = await asyncio.gather(
        *[
            verify_and_fix(
                candidate,
                spec,
                testbench_path,
                prob_workspace / f"candidate_{candidate.strategy}",
            )
            for candidate in candidates
        ]
    )

    passing = [v for v in verified if v.passed]
    print(
        f"[P{problem_num}] {len(passing)}/{len(verified)} candidates passed verification"
    )

    for candidate in verified:
        if not candidate.passed:
            problem_report["candidates"].append(
                candidate_report_entry(candidate, orfs_status="not_run")
            )

    if not passing:
        passing = await emergency_regenerate(
            spec, verified, testbench_path, prob_workspace, problem_report
        )
        if not passing:
            print(
                f"[P{problem_num}] ABORT: No candidates passed after emergency regeneration"
            )
            problem_report["status"] = "all_failed"
            return {
                "problem": problem_num,
                "score": 0,
                "status": "all_failed",
                "report": problem_report,
            }

    # Phase 4: ORFS synthesis in parallel
    print(f"[P{problem_num}] Running ORFS on {len(passing)} candidates...")
    scored_candidates = await asyncio.gather(
        *[
            run_orfs_with_retry(
                c.rtl_source,
                sdc_content,
                config_content,
                spec,
                prob_workspace / f"orfs_{c.strategy}",
                orfs_semaphore,
            )
            for c in passing
        ]
    )

    scored = [s for s in scored_candidates if s is not None]
    if not scored:
        print(f"[P{problem_num}] ABORT: All ORFS runs failed")
        for candidate in passing:
            problem_report["candidates"].append(
                candidate_report_entry(candidate, orfs_status="failed")
            )
        problem_report["status"] = "orfs_failed"
        return {
            "problem": problem_num,
            "score": 0,
            "status": "orfs_failed",
            "report": problem_report,
        }

    # Phase 5: Rank
    passing_by_rtl = {candidate.rtl_source: candidate for candidate in passing}
    scored_by_rtl = {}
    for sc in scored:
        source_candidate = passing_by_rtl.get(sc.rtl_source)
        if source_candidate is not None:
            apply_candidate_metadata(sc, source_candidate)
        score_candidate(sc, problem_num, flow_root, suite)
        scored_by_rtl[sc.rtl_source] = sc

    for candidate in passing:
        problem_report["candidates"].append(
            candidate_report_entry(
                candidate,
                scored_by_rtl.get(candidate.rtl_source),
                orfs_status="success"
                if candidate.rtl_source in scored_by_rtl
                else "failed",
            )
        )

    ranked = rank_candidates(scored)
    best = ranked[0]
    print(
        f"[P{problem_num}] Best score: {best.score}/100 "
        f"(strategy: {best.strategy}, {timing_summary(best)})"
    )

    if not timing_is_closed(best):
        repaired = await attempt_timing_closure(
            best=best,
            scored_candidates=ranked,
            spec=spec,
            problem_num=problem_num,
            suite=suite,
            testbench_path=testbench_path,
            prob_workspace=prob_workspace,
            sdc_content=sdc_content,
            config_content=config_content,
            flow_root=flow_root,
            orfs_semaphore=orfs_semaphore,
            problem_report=problem_report,
        )
        if timing_is_closed(repaired):
            print(
                f"[P{problem_num}] Adopting timing-closed candidate '{repaired.strategy}' "
                f"({timing_summary(repaired)})"
            )
            best = repaired
        elif is_timing_better(repaired, best):
            print(
                f"[P{problem_num}] Adopting best timing-improved candidate '{repaired.strategy}' "
                f"({timing_summary(repaired)})"
            )
            best = repaired

    if best.score < OPTIMIZATION_THRESHOLD and best.score > 0:
        if timing_is_closed(best):
            print(
                f"[P{problem_num}] Score below {OPTIMIZATION_THRESHOLD}, attempting score optimization..."
            )
            try:
                optimized_rtl = await optimize_candidate(best, spec, goal="score")
                problem_report["prompt_attempts"].append(
                    prompt_attempt_entry(
                        stage="score_optimization",
                        purpose="score_optimization",
                        base_strategy="optimized",
                        variant=None,
                        label="optimized",
                        status="generated",
                        generator="llm",
                        source_strategy=best.strategy,
                    )
                )
            except Exception as e:
                print(
                    f"[P{problem_num}] Score optimization skipped due to API failure: {e}"
                )
                problem_report["prompt_attempts"].append(
                    prompt_attempt_entry(
                        stage="score_optimization",
                        purpose="score_optimization",
                        base_strategy="optimized",
                        variant=None,
                        label="optimized",
                        status="failed",
                        generator="llm",
                        source_strategy=best.strategy,
                        error=str(e),
                    )
                )
                optimized_rtl = None
            if optimized_rtl is None:
                opt_candidate = None
            else:
                opt_candidate = Candidate(
                    rtl_source=optimized_rtl,
                    strategy="optimized",
                    base_strategy="optimized",
                    origin="score_optimization",
                    source_strategy=best.strategy,
                    llm_purpose="score_optimization",
                    generator="llm",
                )
            if opt_candidate is not None:
                opt_verified = await verify_and_fix(
                    opt_candidate,
                    spec,
                    testbench_path,
                    prob_workspace / "candidate_optimized",
                )
                if opt_verified.passed:
                    opt_scored = await run_orfs_with_retry(
                        opt_verified.rtl_source,
                        sdc_content,
                        config_content,
                        spec,
                        prob_workspace / "orfs_optimized",
                        orfs_semaphore,
                    )
                    if opt_scored:
                        apply_candidate_metadata(opt_scored, opt_verified)
                        score_candidate(opt_scored, problem_num, flow_root, suite)
                        problem_report["candidates"].append(
                            candidate_report_entry(opt_verified, opt_scored)
                        )
                        if (
                            timing_is_closed(opt_scored)
                            and opt_scored.score > best.score
                        ):
                            print(
                                f"[P{problem_num}] Optimization improved score: "
                                f"{best.score} -> {opt_scored.score}"
                            )
                            best = opt_scored
                        elif not timing_is_closed(opt_scored):
                            print(
                                f"[P{problem_num}] Rejecting optimized candidate because it reopened timing"
                            )
                    else:
                        problem_report["candidates"].append(
                            candidate_report_entry(opt_verified, orfs_status="failed")
                        )
                else:
                    problem_report["candidates"].append(
                        candidate_report_entry(opt_verified, orfs_status="not_run")
                    )
        else:
            print(
                f"[P{problem_num}] Skipping generic score optimization because timing is still open "
                f"({timing_summary(best)})"
            )

    # Emit solution
    prob_output = output_dir / f"p{problem_num}"
    prob_output.mkdir(parents=True, exist_ok=True)

    v_dest = prob_output / f"{spec.module_name}.v"
    v_dest.write_text(best.rtl_source)

    if best.odb_path and best.odb_path.exists():
        shutil.copy2(best.odb_path, prob_output / "6_final.odb")
    if best.sdc_path and best.sdc_path.exists():
        shutil.copy2(best.sdc_path, prob_output / "6_final.sdc")

    mark_selected_candidate(problem_report, best.strategy, "final_output")
    problem_report["status"] = "success"
    problem_report["output_dir"] = str(prob_output)

    print(f"[P{problem_num}] Solution emitted to {prob_output}")
    return {
        "problem": problem_num,
        "score": best.score,
        "status": "success",
        "report": problem_report,
    }


async def main():
    parser = argparse.ArgumentParser(description="Spec-to-Tapeout Multi-Agent Pipeline")
    parser.add_argument(
        "--problems",
        type=Path,
        nargs="+",
        required=True,
        help="Path(s) to problem YAML files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output directory for solutions (default: solutions/<suite>)",
    )
    parser.add_argument(
        "--flow-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "OpenROAD-flow-scripts",
        help="Path to OpenROAD-flow-scripts",
    )
    parser.add_argument(
        "--suite",
        choices=VALID_SUITES,
        help="Problem suite for this run. If omitted, inferred from --problems.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        help="Working directory for intermediate files (default: solutions/workspace/<suite>)",
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        help="Write a JSON run report to this path (default: <output>/run_report.json)",
    )
    args = parser.parse_args()

    try:
        suite = resolve_run_suite(args.problems, args.suite)
    except ValueError as e:
        parser.error(str(e))

    base_dir = Path(__file__).resolve().parent.parent
    output_arg = args.output if args.output is not None else default_output_dir_for_suite(suite)
    workspace_arg = (
        args.workspace
        if args.workspace is not None
        else default_workspace_dir_for_suite(suite)
    )
    output_dir = output_arg.resolve()
    workspace_dir = workspace_arg.resolve()
    flow_root = args.flow_root.resolve()
    report_path = (
        args.report_json.resolve()
        if args.report_json
        else output_dir / "run_report.json"
    )
    orfs_semaphore = asyncio.Semaphore(ORFS_CONCURRENCY)

    print("Spec-to-Tapeout Agent")
    print(f"Suite: {suite}")
    print(f"Problems: {[p.name for p in args.problems]}")
    print(f"Output: {output_dir}")
    print(f"Workspace: {workspace_dir}")
    print(f"Run report: {report_path}")

    results = await asyncio.gather(
        *[
            solve_problem(
                yaml_path=p.resolve(),
                output_dir=output_dir,
                workspace_dir=workspace_dir,
                base_dir=base_dir,
                flow_root=flow_root,
                suite=suite,
                orfs_semaphore=orfs_semaphore,
            )
            for p in args.problems
        ],
        return_exceptions=True,
    )

    run_report = run_report_header(report_path)
    run_report["settings"] = {
        "orfs_concurrency": ORFS_CONCURRENCY,
        "max_fix_retries": MAX_FIX_RETRIES,
        "max_timing_fix_rounds": MAX_TIMING_FIX_ROUNDS,
        "timing_only_max_rounds": TIMING_ONLY_MAX_ROUNDS,
        "timing_only_problem_numbers": sorted(TIMING_ONLY_PROBLEM_NUMBERS),
        "base_strategies": STRATEGIES,
        "suite": suite,
        "problems": [str(p.resolve()) for p in args.problems],
        "output_dir": str(output_dir),
        "workspace_dir": str(workspace_dir),
        "flow_root": str(flow_root),
    }

    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    for problem_path, result in zip(args.problems, results):
        if isinstance(result, BaseException):
            print(f"  ERROR: {result}")
            run_report["problems"].append(
                {
                    "problem": problem_path.stem,
                    "yaml": str(problem_path.resolve()),
                    "status": "exception",
                    "error": str(result),
                }
            )
        else:
            print(f"  P{result['problem']}: {result['score']}/100 ({result['status']})")
            run_report["problems"].append(
                result.get(
                    "report",
                    {
                        "problem": result["problem"],
                        "status": result["status"],
                        "score": result["score"],
                    },
                )
            )

    write_run_report(report_path, run_report)
    print(f"Run report written to {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
