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

from agents.models import Spec, Candidate, ScoredCandidate
from agents.spec_interpreter import parse_spec
from agents.sdc_config_generator import generate_sdc, generate_config_mk
from agents.rtl_generator import generate_rtl, STRATEGIES
from agents.rtl_fixer import fix_rtl
from agents.verification import verify_candidate
from agents.orfs_runner import run_orfs_with_retry
from agents.ranker import score_candidate, rank_candidates, optimize_candidate

MAX_FIX_RETRIES = 3
ORFS_CONCURRENCY = 3
OPTIMIZATION_THRESHOLD = 85


def get_problem_number(yaml_path: Path) -> int:
    match = re.search(r"p(\d+)", yaml_path.stem)
    if match:
        return int(match.group(1))
    raise ValueError(f"Cannot extract problem number from {yaml_path}")


def find_testbench(problem_number: int, base_dir: Path) -> Path | None:
    eval_dir = base_dir / "evaluation" / "visible" / f"p{problem_number}"
    if not eval_dir.exists():
        eval_dir = base_dir / "evaluation" / "hidden" / f"p{problem_number}"
    if not eval_dir.exists():
        return None
    tbs = list(eval_dir.glob("*.v"))
    return tbs[0] if tbs else None


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
            current.rtl_source, testbench_path, work_dir / f"verify_{attempt}",
        )

        if passed:
            current.passed = True
            current.compile_log = compile_log
            current.sim_log = sim_log
            print(f"  [{spec.module_name}] Strategy '{current.strategy}' PASSED (attempt {attempt})")
            return current

        error_log = compile_log + sim_log
        if attempt < MAX_FIX_RETRIES:
            error_type = "compilation" if "error" in compile_log.lower() else "simulation"
            current = await fix_rtl(current, spec, error_log, tb_source, error_type)
        else:
            current.passed = False
            current.compile_log = compile_log
            current.sim_log = sim_log

    print(f"  [{spec.module_name}] Strategy '{current.strategy}' FAILED after {MAX_FIX_RETRIES} retries")
    return current


async def emergency_regenerate(
    spec: Spec,
    failed_candidates: list[Candidate],
    testbench_path: Path,
    work_dir: Path,
) -> list[Candidate]:
    print(f"  [{spec.module_name}] Emergency regeneration...")
    error_context = "\n".join(
        f"Strategy {c.strategy} errors:\n{c.compile_log}\n{c.sim_log}"
        for c in failed_candidates
    )

    from agents.prompts import build_rtl_prompt
    from agents.llm_client import llm_call, extract_code_block

    system, prompt = build_rtl_prompt(spec, "textbook")
    prompt += f"\n\nPrevious attempts failed with these errors (avoid them):\n{error_context[:2000]}"

    response = await llm_call(prompt, system, model="opus")
    rtl_source = extract_code_block(response)

    candidate = Candidate(rtl_source=rtl_source, strategy="emergency")
    result = await verify_and_fix(candidate, spec, testbench_path, work_dir / "emergency")

    return [result] if result.passed else []


async def solve_problem(
    yaml_path: Path,
    output_dir: Path,
    workspace_dir: Path,
    base_dir: Path,
    flow_root: Path,
    orfs_semaphore: asyncio.Semaphore,
) -> dict:
    problem_num = get_problem_number(yaml_path)
    print(f"\n{'='*60}")
    print(f"[P{problem_num}] Starting pipeline for {yaml_path.name}")
    print(f"{'='*60}")

    # Phase 1: Parse
    spec = parse_spec(yaml_path)
    sdc_content = generate_sdc(spec)
    config_content = generate_config_mk(spec)
    print(f"[P{problem_num}] Parsed: {spec.module_name} ({spec.design_type}), clock={spec.clock_period}ns")

    testbench_path = find_testbench(problem_num, base_dir)
    if testbench_path is None:
        print(f"[P{problem_num}] WARNING: No testbench found, skipping verification")
        return {"problem": problem_num, "score": 0, "status": "no_testbench"}

    prob_workspace = workspace_dir / f"p{problem_num}"
    prob_workspace.mkdir(parents=True, exist_ok=True)

    # Phase 2: Generate N=3 candidates in parallel
    print(f"[P{problem_num}] Generating {len(STRATEGIES)} RTL candidates...")
    candidates = await asyncio.gather(*[
        generate_rtl(spec, strategy) for strategy in STRATEGIES
    ])

    # Phase 3: Verify + fix loop in parallel
    print(f"[P{problem_num}] Verifying candidates...")
    verified = await asyncio.gather(*[
        verify_and_fix(
            candidate, spec, testbench_path,
            prob_workspace / f"candidate_{candidate.strategy}",
        )
        for candidate in candidates
    ])

    passing = [v for v in verified if v.passed]
    print(f"[P{problem_num}] {len(passing)}/{len(verified)} candidates passed verification")

    if not passing:
        passing = await emergency_regenerate(spec, verified, testbench_path, prob_workspace)
        if not passing:
            print(f"[P{problem_num}] ABORT: No candidates passed after emergency regeneration")
            return {"problem": problem_num, "score": 0, "status": "all_failed"}

    # Phase 4: ORFS synthesis in parallel
    print(f"[P{problem_num}] Running ORFS on {len(passing)} candidates...")
    scored_candidates = await asyncio.gather(*[
        run_orfs_with_retry(
            c.rtl_source, sdc_content, config_content, spec,
            prob_workspace / f"orfs_{c.strategy}",
            orfs_semaphore,
        )
        for c in passing
    ])

    scored = [s for s in scored_candidates if s is not None]
    if not scored:
        print(f"[P{problem_num}] ABORT: All ORFS runs failed")
        return {"problem": problem_num, "score": 0, "status": "orfs_failed"}

    # Phase 5: Rank
    for sc in scored:
        sc.strategy = next(
            (c.strategy for c in passing if c.rtl_source == sc.rtl_source), "unknown"
        )
        score_candidate(sc, problem_num, flow_root)

    ranked = rank_candidates(scored)
    best = ranked[0]
    print(f"[P{problem_num}] Best score: {best.score}/100 (strategy: {best.strategy})")

    if best.score < OPTIMIZATION_THRESHOLD and best.score > 0:
        print(f"[P{problem_num}] Score below {OPTIMIZATION_THRESHOLD}, attempting optimization...")
        optimized_rtl = await optimize_candidate(best, spec)
        opt_candidate = Candidate(rtl_source=optimized_rtl, strategy="optimized")
        opt_verified = await verify_and_fix(
            opt_candidate, spec, testbench_path,
            prob_workspace / "candidate_optimized",
        )
        if opt_verified.passed:
            opt_scored = await run_orfs_with_retry(
                opt_verified.rtl_source, sdc_content, config_content, spec,
                prob_workspace / "orfs_optimized",
                orfs_semaphore,
            )
            if opt_scored:
                score_candidate(opt_scored, problem_num, flow_root)
                if opt_scored.score > best.score:
                    print(f"[P{problem_num}] Optimization improved score: {best.score} -> {opt_scored.score}")
                    best = opt_scored

    # Emit solution
    prob_output = output_dir / f"p{problem_num}"
    prob_output.mkdir(parents=True, exist_ok=True)

    v_dest = prob_output / f"{spec.module_name}.v"
    v_dest.write_text(best.rtl_source)

    if best.odb_path and best.odb_path.exists():
        shutil.copy2(best.odb_path, prob_output / "6_final.odb")
    if best.sdc_path and best.sdc_path.exists():
        shutil.copy2(best.sdc_path, prob_output / "6_final.sdc")

    print(f"[P{problem_num}] Solution emitted to {prob_output}")
    return {"problem": problem_num, "score": best.score, "status": "success"}


async def main():
    parser = argparse.ArgumentParser(description="Spec-to-Tapeout Multi-Agent Pipeline")
    parser.add_argument("--problems", type=Path, nargs="+", required=True,
                        help="Path(s) to problem YAML files")
    parser.add_argument("--output", type=Path, default=Path("solutions/visible"),
                        help="Output directory for solutions")
    parser.add_argument("--flow-root", type=Path,
                        default=Path(__file__).resolve().parent.parent.parent / "OpenROAD-flow-scripts",
                        help="Path to OpenROAD-flow-scripts")
    parser.add_argument("--workspace", type=Path, default=Path("solutions/workspace"),
                        help="Working directory for intermediate files")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent.parent
    orfs_semaphore = asyncio.Semaphore(ORFS_CONCURRENCY)

    print(f"Spec-to-Tapeout Agent")
    print(f"Problems: {[p.name for p in args.problems]}")
    print(f"Output: {args.output}")

    results = await asyncio.gather(*[
        solve_problem(
            yaml_path=p.resolve(),
            output_dir=args.output.resolve(),
            workspace_dir=args.workspace.resolve(),
            base_dir=base_dir,
            flow_root=args.flow_root.resolve(),
            orfs_semaphore=orfs_semaphore,
        )
        for p in args.problems
    ], return_exceptions=True)

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for r in results:
        if isinstance(r, Exception):
            print(f"  ERROR: {r}")
        else:
            print(f"  P{r['problem']}: {r['score']}/100 ({r['status']})")


if __name__ == "__main__":
    asyncio.run(main())
