from __future__ import annotations
from pathlib import Path

from .models import Spec, Candidate
from .llm_client import llm_call, extract_code_block
from .prompts import build_rtl_prompt

STRATEGIES = ["textbook", "timing_opt", "area_opt"]


async def generate_rtl(spec: Spec, strategy: str) -> Candidate:
    print(f"  [{spec.module_name}] Generating RTL with strategy: {strategy}")
    system, prompt = build_rtl_prompt(spec, strategy)
    response = await llm_call(prompt, system, model="opus")
    rtl_source = extract_code_block(response)

    # Ensure module signature matches spec exactly
    if spec.module_signature not in rtl_source:
        rtl_source = _fix_module_signature(rtl_source, spec)

    return Candidate(rtl_source=rtl_source, strategy=strategy)


def _fix_module_signature(rtl_source: str, spec: Spec) -> str:
    import re
    pattern = r"module\s+" + re.escape(spec.module_name) + r"\s*(?:#\s*\(.*?\))?\s*\(.*?\)\s*;"
    match = re.search(pattern, rtl_source, re.DOTALL)
    if match:
        rtl_source = rtl_source[:match.start()] + spec.module_signature + rtl_source[match.end():]
    return rtl_source
