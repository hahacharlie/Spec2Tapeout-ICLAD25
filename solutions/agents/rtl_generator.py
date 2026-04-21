from __future__ import annotations

from .models import Spec, Candidate
from .llm_client import llm_call, extract_code_block
from .prompts import build_rtl_prompt, get_generation_variants

STRATEGIES = ["textbook", "timing_opt", "area_opt"]



def strategy_label(strategy: str, variant: str | None = None) -> str:
    if variant is None:
        return strategy
    return f"{strategy}__{variant}"



def generation_plan(spec: Spec) -> list[tuple[str, str | None]]:
    plan: list[tuple[str, str | None]] = []
    for strategy in STRATEGIES:
        for variant in get_generation_variants(spec, strategy):
            plan.append((strategy, variant))
    return plan


async def generate_rtl(spec: Spec, strategy: str, variant: str | None = None) -> Candidate:
    label = strategy_label(strategy, variant)
    print(f"  [{spec.module_name}] Generating RTL with strategy: {label}")

    system, prompt = build_rtl_prompt(spec, strategy, variant=variant)
    response = await llm_call(prompt, system, model="opus", purpose="rtl_generation")
    rtl_source = extract_code_block(response)

    # Ensure module signature matches spec exactly
    if spec.module_signature not in rtl_source:
        rtl_source = _fix_module_signature(rtl_source, spec)

    return Candidate(
        rtl_source=rtl_source,
        strategy=label,
        base_strategy=strategy,
        variant=variant,
        origin="initial_generation",
        llm_purpose="rtl_generation",
        generator="llm",
    )


async def generate_rtl_candidates(spec: Spec) -> tuple[list[Candidate], list[dict]]:
    candidates: list[Candidate] = []
    events: list[dict] = []
    seen_sources: set[str] = set()

    for strategy, variant in generation_plan(spec):
        label = strategy_label(strategy, variant)
        try:
            candidate = await generate_rtl(spec, strategy, variant=variant)
        except Exception as e:
            events.append({
                "stage": "initial_generation",
                "purpose": "rtl_generation",
                "base_strategy": strategy,
                "variant": variant,
                "label": label,
                "status": "failed",
                "generator": "llm",
                "error": str(e),
            })
            continue

        status = "generated"
        if candidate.rtl_source in seen_sources:
            status = "duplicate_filtered"
        else:
            seen_sources.add(candidate.rtl_source)
            candidates.append(candidate)

        events.append({
            "stage": "initial_generation",
            "purpose": "rtl_generation",
            "base_strategy": strategy,
            "variant": variant,
            "label": candidate.strategy,
            "status": status,
            "generator": candidate.generator,
            "error": None,
        })

    if not candidates:
        raise RuntimeError(f"No RTL candidates generated for {spec.module_name}")

    return candidates, events


def _fix_module_signature(rtl_source: str, spec: Spec) -> str:
    import re
    pattern = r"module\s+" + re.escape(spec.module_name) + r"\s*(?:#\s*\(.*?\))?\s*\(.*?\)\s*;"
    match = re.search(pattern, rtl_source, re.DOTALL)
    if match:
        rtl_source = rtl_source[:match.start()] + spec.module_signature + rtl_source[match.end():]
    return rtl_source
