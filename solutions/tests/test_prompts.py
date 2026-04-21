import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.models import Port, Spec
from agents.prompts import build_timing_closure_prompt



def _dummy_spec() -> Spec:
    return Spec(
        module_name="fp16_multiplier",
        design_type="combinational",
        clock_period=9.0,
        ports=[
            Port(name="a", direction="input", type="logic [15:0]", description="operand a"),
            Port(name="b", direction="input", type="logic [15:0]", description="operand b"),
            Port(name="result", direction="output", type="logic [15:0]", description="product"),
        ],
        parameters={},
        module_signature="module fp16_multiplier(input logic [15:0] a, input logic [15:0] b, output logic [15:0] result);",
        description="FP16 multiplier",
        yaml_raw={},
    )



def test_build_timing_closure_prompt_includes_timing_report_and_mode():
    spec = _dummy_spec()
    system, prompt = build_timing_closure_prompt(
        rtl_source="module fp16_multiplier; endmodule",
        metrics={"timing__setup__ws": -2.01, "timing__setup__tns": -27.73},
        spec=spec,
        attempt=2,
        timing_report="Startpoint: b[12]\nEndpoint: result[5]\nslack (VIOLATED)",
        timing_only=True,
        testbench_source="module tb; initial begin #1; end endmodule",
    )

    assert "TIMING-ONLY MODE" in system
    assert "OpenROAD timing diagnostics" in prompt
    assert "Startpoint: b[12]" in prompt
    assert "timing-only mode is active" in prompt.lower()
    assert "Earlier timing-repair attempts were insufficient" in prompt
    assert "Testbench (read-only" in prompt
    assert "module tb;" in prompt
