import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.spec_interpreter import parse_spec
from agents.sdc_config_generator import (
    generate_sdc,
    generate_config_mk,
    get_orfs_defaults,
    tighten_physical_config,
)


def test_sdc_p1():
    spec = parse_spec(Path(__file__).resolve().parent.parent.parent / "problems" / "visible" / "p1.yaml")
    sdc = generate_sdc(spec)
    assert "current_design seq_detector_0011" in sdc
    assert "create_clock" in sdc
    assert "set_input_delay" in sdc
    assert "set_output_delay" in sdc


def test_config_mk_p1():
    spec = parse_spec(Path(__file__).resolve().parent.parent.parent / "problems" / "visible" / "p1.yaml")
    config = generate_config_mk(spec, design_nickname="iclad_seq_detector")
    assert "DESIGN_NAME = seq_detector_0011" in config
    assert "PLATFORM    = sky130hd" in config
    assert "VERILOG_FILES" in config
    assert "SDC_FILE" in config


def test_orfs_defaults_fsm():
    defaults = get_orfs_defaults("fsm")
    assert defaults["utilization"] == 15
    assert defaults["density"] == 0.6


def test_orfs_defaults_pipelined():
    defaults = get_orfs_defaults("pipelined")
    assert defaults["utilization"] == 30
    assert defaults["density"] == 0.65


def test_orfs_defaults_combinational():
    defaults = get_orfs_defaults("combinational")
    assert defaults["utilization"] == 40
    assert defaults["density"] == 0.7


def test_config_mk_p8_no_clock_constraint():
    spec = parse_spec(Path(__file__).resolve().parent.parent.parent / "problems" / "visible" / "p8.yaml")
    sdc = generate_sdc(spec)
    assert "create_clock" in sdc


def test_config_mk_p8_uses_combinational_defaults():
    spec = parse_spec(
        Path(__file__).resolve().parent.parent.parent / "problems" / "visible" / "p8.yaml"
    )
    config = generate_config_mk(spec)
    assert "export CORE_UTILIZATION = 40" in config
    assert "export PLACE_DENSITY = 0.7" in config


def test_tighten_physical_config_reduces_utilization_and_density():
    spec = parse_spec(Path(__file__).resolve().parent.parent.parent / "problems" / "visible" / "p7.yaml")
    config = generate_config_mk(spec)
    tightened = tighten_physical_config(config, attempt=2)
    assert "export CORE_UTILIZATION = 20" in tightened
    assert "export PLACE_DENSITY = 0.55" in tightened
