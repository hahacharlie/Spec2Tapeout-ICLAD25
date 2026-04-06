"""End-to-end integration test using problem P1.

Requires:
- ANTHROPIC_API_KEY environment variable set
- Docker with openroad/flow-ubuntu22.04-builder:836842 image
- iverilog installed

Run: python -m pytest tests/test_pipeline.py -v -s --timeout=7200
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PROBLEMS_DIR = BASE_DIR / "problems" / "visible"
EVAL_DIR = BASE_DIR / "evaluation" / "visible"

from agents.spec_interpreter import parse_spec
from agents.sdc_config_generator import generate_sdc, generate_config_mk
from agents.rtl_generator import generate_rtl
from agents.verification import verify_candidate


@pytest.mark.skipif(
    not (PROBLEMS_DIR / "p1.yaml").exists(),
    reason="Problem files not found",
)
class TestP1Pipeline:
    def test_parse_spec(self):
        spec = parse_spec(PROBLEMS_DIR / "p1.yaml")
        assert spec.module_name == "seq_detector_0011"
        assert spec.design_type == "fsm"

    def test_generate_sdc(self):
        spec = parse_spec(PROBLEMS_DIR / "p1.yaml")
        sdc = generate_sdc(spec)
        assert "seq_detector_0011" in sdc
        assert "create_clock" in sdc

    def test_generate_config(self):
        spec = parse_spec(PROBLEMS_DIR / "p1.yaml")
        config = generate_config_mk(spec)
        assert "sky130hd" in config
        assert "seq_detector_0011" in config

    @pytest.mark.skipif(
        "ANTHROPIC_API_KEY" not in __import__("os").environ,
        reason="ANTHROPIC_API_KEY not set",
    )
    def test_generate_and_verify_rtl(self, tmp_path):
        """Generate RTL with textbook strategy and verify with iVerilog."""
        spec = parse_spec(PROBLEMS_DIR / "p1.yaml")
        tb_path = EVAL_DIR / "p1" / "iclad_seq_detector_tb.v"

        async def run():
            candidate = await generate_rtl(spec, "textbook")
            assert "module seq_detector_0011" in candidate.rtl_source
            assert "endmodule" in candidate.rtl_source

            passed, compile_log, sim_log = await verify_candidate(
                candidate.rtl_source, tb_path, tmp_path,
            )
            return passed, compile_log, sim_log

        passed, compile_log, sim_log = asyncio.run(run())
        print(f"Compile log: {compile_log}")
        print(f"Sim log: {sim_log}")
        assert passed, f"Verification failed.\nCompile: {compile_log}\nSim: {sim_log}"
