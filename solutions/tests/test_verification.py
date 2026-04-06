import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.verification import compile_verilog, run_simulation, check_result


def test_compile_known_good():
    v_path = Path(__file__).resolve().parent.parent.parent / "example_problem" / "output" / "iclad_seq_detector.v"
    tb_path = Path(__file__).resolve().parent.parent.parent / "evaluation" / "visible" / "p1" / "iclad_seq_detector_tb.v"
    success, log = compile_verilog(v_path, tb_path)
    assert success, f"Compilation failed: {log}"


def test_simulate_known_good():
    v_path = Path(__file__).resolve().parent.parent.parent / "example_problem" / "output" / "iclad_seq_detector.v"
    tb_path = Path(__file__).resolve().parent.parent.parent / "evaluation" / "visible" / "p1" / "iclad_seq_detector_tb.v"
    success, compile_log = compile_verilog(v_path, tb_path)
    assert success
    passed, sim_log = run_simulation()
    assert passed, f"Simulation failed: {sim_log}"


def test_check_result_pass():
    assert check_result("Test PASSED!") is True
    assert check_result("PASS: Output = 42") is True


def test_check_result_fail():
    assert check_result("Test FAILED: 3 errors found.") is False
    assert check_result("FAIL: Output = 0, Expected = 1") is False
    assert check_result("No output at all") is False
