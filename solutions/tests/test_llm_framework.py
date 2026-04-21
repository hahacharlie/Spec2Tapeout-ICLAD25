import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agents.rtl_generator as rtl_generator
from agents.llm_client import (
    CODEX_MODEL,
    cache_key_for_request,
    load_cached_response,
    model_chain_for_purpose,
    save_cached_response,
)
from agents.models import Port, Spec
from agents.prompts import build_rtl_prompt, get_generation_variants, get_timing_repair_variants
from agents.rtl_generator import generate_rtl, generation_plan



def _dummy_spec(design_type: str = "combinational") -> Spec:
    return Spec(
        module_name="demo",
        design_type=design_type,
        clock_period=5.0,
        ports=[
            Port(name="a", direction="input", type="logic", description="a"),
            Port(name="b", direction="input", type="logic", description="b"),
            Port(name="y", direction="output", type="logic", description="y"),
        ],
        parameters={},
        module_signature="module demo(input logic a, input logic b, output logic y);",
        description="demo block",
        yaml_raw={},
    )



def test_model_chain_for_purpose_dedupes_primary_model():
    chain = model_chain_for_purpose("sonnet", "timing_optimization")
    assert chain == [CODEX_MODEL]



def test_cache_round_trip(tmp_path, monkeypatch):
    import agents.llm_client as llm_client

    monkeypatch.setattr(llm_client, "LLM_CACHE_DIR", tmp_path)
    monkeypatch.setattr(llm_client, "LLM_ENABLE_CACHE", True)

    key = cache_key_for_request("prompt", "system", ["m1", "m2"], "rtl_generation")
    save_cached_response(key, "m1", "cached-response", "rtl_generation")
    assert load_cached_response(key) == "cached-response"



def test_generation_variants_expand_timing_strategy(monkeypatch):
    spec = _dummy_spec("combinational")
    monkeypatch.setenv("RTL_TIMING_VARIANT_COUNT", "2")
    variants = get_generation_variants(spec, "timing_opt")
    assert variants[0] is None
    assert variants[1:] == ["parallel_special_cases", "balanced_reduction"]



def test_generation_plan_includes_timing_variants(monkeypatch):
    spec = _dummy_spec("pipelined")
    monkeypatch.setenv("RTL_TIMING_VARIANT_COUNT", "2")
    plan = generation_plan(spec)
    assert ("textbook", None) in plan
    assert ("area_opt", None) in plan
    assert ("timing_opt", None) in plan
    assert ("timing_opt", "balanced_tree") in plan
    assert ("timing_opt", "latency_preserving_retime") in plan



def test_build_rtl_prompt_includes_variant_hint():
    spec = _dummy_spec("combinational")
    system, prompt = build_rtl_prompt(spec, "timing_opt", variant="balanced_reduction")
    assert "Timing search variant: balanced_reduction" in system
    assert "carry-save style accumulation" in system
    assert "Timing search variant to prioritize: balanced_reduction" in prompt



def test_get_timing_repair_variants_reverses_after_first_attempt(monkeypatch):
    spec = _dummy_spec("pipelined")
    monkeypatch.setenv("TIMING_REPAIR_VARIANT_COUNT", "2")
    first = get_timing_repair_variants(spec, 1)
    second = get_timing_repair_variants(spec, 2)
    assert first == [None, "tree_reduction", "retime_last_stage"]
    assert second == [None, "streaming_structure", "retime_last_stage"]


def test_generate_rtl_propagates_llm_errors(monkeypatch):
    spec = _dummy_spec("combinational")

    async def _failing_llm_call(*args, **kwargs):
        raise RuntimeError("LLM backend unavailable")

    monkeypatch.setattr(rtl_generator, "llm_call", _failing_llm_call)

    with pytest.raises(RuntimeError, match="LLM backend unavailable"):
        asyncio.run(generate_rtl(spec, "textbook"))
