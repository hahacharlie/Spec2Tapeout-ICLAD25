from __future__ import annotations
from pathlib import Path

from .models import Spec, Candidate
from .llm_client import llm_call, extract_code_block
from .prompts import build_fixer_prompt


async def fix_rtl(
    candidate: Candidate,
    spec: Spec,
    error_log: str,
    testbench_source: str | None = None,
    error_type: str = "compilation",
) -> Candidate:
    print(f"  [{spec.module_name}] Fixing RTL ({error_type}, attempt {candidate.retry_count + 1})")
    system, prompt = build_fixer_prompt(
        rtl_source=candidate.rtl_source,
        error_log=error_log,
        spec=spec,
        testbench_source=testbench_source,
        error_type=error_type,
    )
    response = await llm_call(prompt, system, model="sonnet", purpose="rtl_fix")
    fixed_source = extract_code_block(response)

    return Candidate(
        rtl_source=fixed_source,
        strategy=candidate.strategy,
        retry_count=candidate.retry_count + 1,
        base_strategy=candidate.base_strategy,
        variant=candidate.variant,
        origin=candidate.origin,
        source_strategy=candidate.source_strategy,
        llm_purpose="rtl_fix",
        generator="llm_fix",
        verification_attempts=list(candidate.verification_attempts),
    )
