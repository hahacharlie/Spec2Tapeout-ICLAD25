import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.verification import compile_verilog, run_simulation, check_result


KNOWN_GOOD_SEQ_DETECTOR_RTL = """\
module seq_detector_0011(
    input clk,
    input reset,
    input data_in,
    output reg detected = 1'b0
);
reg [2:0] hist = 3'b000;

always @(posedge clk) begin
    if (reset) begin
        hist <= 3'b000;
        detected <= 1'b0;
    end else begin
        detected <= ({hist, data_in} == 4'b0011);
        hist <= {hist[1:0], data_in};
    end
end
endmodule
"""


def _write_known_good_design(tmp_path: Path) -> tuple[Path, Path]:
    v_path = tmp_path / "seq_detector_0011.v"
    v_path.write_text(KNOWN_GOOD_SEQ_DETECTOR_RTL)
    tb_path = (
        Path(__file__).resolve().parent.parent.parent
        / "evaluation"
        / "visible"
        / "p1"
        / "iclad_seq_detector_tb.v"
    )
    return v_path, tb_path


def test_compile_known_good(tmp_path):
    v_path, tb_path = _write_known_good_design(tmp_path)
    success, log = compile_verilog(v_path, tb_path, tmp_path)
    assert success, f"Compilation failed: {log}"


def test_simulate_known_good(tmp_path):
    v_path, tb_path = _write_known_good_design(tmp_path)
    success, compile_log = compile_verilog(v_path, tb_path, tmp_path)
    assert success
    passed, sim_log = run_simulation(tmp_path / "sim.out")
    assert passed, f"Simulation failed: {sim_log}"


def test_check_result_pass():
    assert check_result("Test PASSED!") is True
    assert check_result("PASS: Output = 42") is True


def test_check_result_fail():
    assert check_result("Test FAILED: 3 errors found.") is False
    assert check_result("FAIL: Output = 0, Expected = 1") is False
    assert check_result("No output at all") is False
