import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.spec_interpreter import parse_spec, classify_design_type


def test_parse_p1():
    spec = parse_spec(Path(__file__).resolve().parent.parent.parent / "problems" / "visible" / "p1.yaml")
    assert spec.module_name == "seq_detector_0011"
    assert spec.clock_period == 1.1
    assert spec.design_type == "fsm"
    assert "module seq_detector_0011(" in spec.module_signature
    assert len(spec.ports) == 4
    assert spec.clock_port_name == "clk"


def test_parse_p5():
    spec = parse_spec(Path(__file__).resolve().parent.parent.parent / "problems" / "visible" / "p5.yaml")
    assert spec.module_name == "dot_product"
    assert spec.clock_period == 4.5
    assert spec.design_type == "pipelined"
    assert spec.parameters == {"N": 8, "WIDTH": 8}


def test_parse_p8():
    spec = parse_spec(Path(__file__).resolve().parent.parent.parent / "problems" / "visible" / "p8.yaml")
    assert spec.module_name == "fp16_multiplier"
    assert spec.clock_period == 9.0
    assert spec.design_type == "combinational"
    assert spec.parameters == {}


def test_classify_fsm():
    assert classify_design_type("Detects a binary sequence", {"clk": None}, {}) == "fsm"


def test_classify_pipelined():
    assert classify_design_type("Pipelined dot product", {"clk": None}, {"N": 8}) == "pipelined"


def test_classify_combinational():
    assert classify_design_type("16-bit floating-point multiplier", {}, {}) == "combinational"
