"""End-to-end integration test using problem P1.

Requires:
- Codex CLI installed and authenticated (`codex login`)
- iverilog installed

Run: pytest -q solutions/tests/test_pipeline.py -v -s --timeout=7200
"""
import asyncio
import os
import shutil
import subprocess
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
from spec2tapeout_agent import verify_and_fix


def _running_in_codex_sandbox() -> bool:
    return (
        os.getenv("CODEX_CI") == "1"
        or os.getenv("CODEX_SANDBOX_NETWORK_DISABLED") == "1"
        or os.getenv("CODEX_THREAD_ID") is not None
    )


def _codex_live_test_ready() -> bool:
    if _running_in_codex_sandbox():
        return False
    return _codex_authenticated()


def _codex_authenticated() -> bool:
    if shutil.which("codex") is None:
        return False
    try:
        result = subprocess.run(
            ["codex", "login", "status"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


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
        not _codex_live_test_ready(),
        reason="Codex CLI integration test disabled in Codex sandbox or Codex CLI not authenticated",
    )
    @pytest.mark.skipif(shutil.which("iverilog") is None, reason="iverilog not installed")
    def test_generate_and_verify_rtl(self, tmp_path):
        """Exercise the live generate-and-fix loop used by the real pipeline."""
        spec = parse_spec(PROBLEMS_DIR / "p1.yaml")
        tb_path = EVAL_DIR / "p1" / "iclad_seq_detector_tb.v"

        async def run():
            candidate = await generate_rtl(spec, "textbook")
            assert "module seq_detector_0011" in candidate.rtl_source
            assert "endmodule" in candidate.rtl_source

            verified = await verify_and_fix(
                candidate,
                spec,
                tb_path,
                tmp_path / "textbook",
            )
            return verified.passed, verified.compile_log, verified.sim_log

        passed, compile_log, sim_log = asyncio.run(run())
        print(f"Compile log: {compile_log}")
        print(f"Sim log: {sim_log}")
        assert passed, f"Verification failed.\nCompile: {compile_log}\nSim: {sim_log}"
