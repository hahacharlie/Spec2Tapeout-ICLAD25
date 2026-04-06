from __future__ import annotations

from .models import Spec


ORFS_DEFAULTS = {
    "fsm": {"utilization": 15, "density": 0.6},
    "pipelined": {"utilization": 30, "density": 0.65},
    "combinational": {"utilization": 40, "density": 0.7},
}


def get_orfs_defaults(design_type: str) -> dict:
    return ORFS_DEFAULTS.get(design_type, ORFS_DEFAULTS["pipelined"]).copy()


def generate_sdc(spec: Spec) -> str:
    clk_name = spec.clock_port_name or "virtual_clk"
    clk_port_name = spec.clock_port_name or "virtual_clk"
    is_virtual = spec.clock_port_name is None

    lines = [
        f"current_design {spec.module_name}",
        "",
        f"set clk_name  {clk_name}",
        f"set clk_port_name {clk_port_name}",
        f"set clk_period {spec.clock_period}",
        "set clk_io_pct 0.2",
        "",
    ]

    if is_virtual:
        lines.append(f"create_clock -name $clk_name -period $clk_period")
    else:
        lines.append("set clk_port [get_ports $clk_port_name]")
        lines.append("")
        lines.append("create_clock -name $clk_name -period $clk_period $clk_port")

    lines.append("")
    lines.append("set non_clock_inputs [lsearch -inline -all -not -exact [all_inputs] [get_ports $clk_port_name]]")
    lines.append("")
    lines.append("set_input_delay  [expr $clk_period * $clk_io_pct] -clock $clk_name $non_clock_inputs")
    lines.append("set_output_delay [expr $clk_period * $clk_io_pct] -clock $clk_name [all_outputs]")

    return "\n".join(lines) + "\n"


def generate_config_mk(
    spec: Spec,
    design_nickname: str | None = None,
    utilization: int | None = None,
    density: float | None = None,
) -> str:
    defaults = get_orfs_defaults(spec.design_type)
    if design_nickname is None:
        design_nickname = f"iclad_{spec.module_name}"
    util = utilization or defaults["utilization"]
    dens = density or defaults["density"]

    return f"""export DESIGN_NICKNAME = {design_nickname}
export DESIGN_NAME = {spec.module_name}
export PLATFORM    = sky130hd

export VERILOG_FILES = /design/{spec.module_name}.v
export SDC_FILE      = /design/constraint.sdc

export PLACE_PINS_ARGS = -min_distance 4 -min_distance_in_tracks

export CORE_UTILIZATION = {util}
export CORE_ASPECT_RATIO = 1
export CORE_MARGIN = 4

export PLACE_DENSITY = {dens}
"""
