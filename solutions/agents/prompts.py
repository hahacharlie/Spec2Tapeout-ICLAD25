from __future__ import annotations
from .models import Spec

SYSTEM_BASE = """You are an expert digital hardware designer generating SystemVerilog-2012 RTL.
Target: SkyWater 130nm HD (sky130hd).
Compatibility: iverilog -Wall -g2012.
Rules:
- Use ONLY synthesizable constructs (no $display, $finish, initial blocks, delays)
- Match the module signature EXACTLY as provided — do not change port names, types, or widths
- Output ONLY the complete SystemVerilog module in a ```systemverilog code block
- No testbench code, no explanatory text outside the code block"""

STRATEGY_TEXTBOOK = """Strategy: Write a clean, correct, straightforward implementation.
Prioritize readability and correctness over optimization.
Use clear state encoding, explicit type declarations, and well-named signals."""

STRATEGY_TIMING_OPT = """Strategy: Optimize for timing — minimize critical path depth.
- Use pipeline registers to break long combinational chains
- Prefer registered outputs over combinational outputs
- For multipliers, consider breaking into stages
- Minimize logic depth between any two flip-flops
- Use balanced binary trees for wide reduction operations"""

STRATEGY_AREA_OPT = """Strategy: Optimize for area — minimize gate count and register usage.
- Prefer resource sharing and sequential reuse over parallel hardware
- Use minimal bit-widths where possible
- Share multipliers across clock cycles if timing permits
- Avoid redundant pipeline registers when timing is relaxed"""

DESIGN_TYPE_HINTS = {
    "fsm": """Design type: Finite State Machine (FSM)
- Use localparam for state encoding (one-hot or binary depending on state count)
- Separate next-state logic and output logic into distinct always blocks
- Use synchronous reset
- For sequence detectors: handle overlapping detection carefully
- Register outputs for clean timing""",

    "pipelined": """Design type: Pipelined Datapath
- Break computation into pipeline stages with registered boundaries
- Track data validity through the pipeline with a valid/enable shift register
- Use signed arithmetic operators ($signed) for signed datapaths
- Be careful with bit-width growth: multiplication doubles width, addition adds 1 bit
- Use $clog2 for computing address/index widths from parameters""",

    "combinational": """Design type: Combinational Logic
- No sequential elements needed in the datapath
- Handle ALL special cases explicitly (for IEEE 754: zero, subnormal, infinity, NaN)
- Use explicit rounding logic (round-to-nearest-even for IEEE 754)
- Assign to output using continuous assignment or always_comb
- Watch for unintended latches — cover all branches in case/if""",
}


def build_rtl_prompt(spec: Spec, strategy: str) -> tuple[str, str]:
    strategy_text = {
        "textbook": STRATEGY_TEXTBOOK,
        "timing_opt": STRATEGY_TIMING_OPT,
        "area_opt": STRATEGY_AREA_OPT,
    }[strategy]

    design_hint = DESIGN_TYPE_HINTS.get(spec.design_type, "")

    system = f"{SYSTEM_BASE}\n\n{strategy_text}\n\n{design_hint}"

    param_str = ""
    if spec.parameters:
        param_str = "\nParameters:\n" + "\n".join(
            f"  {k} = {v}" for k, v in spec.parameters.items()
        )

    port_str = "\nPorts:\n" + "\n".join(
        f"  {p.direction} {p.name}: {p.description}" for p in spec.ports
    )

    sample_io = ""
    for key in ("sample_input", "sample_output", "sample_usage", "stimulus", "expected_y_out"):
        if key in spec.yaml_raw:
            sample_io += f"\n{key}: {spec.yaml_raw[key]}"

    prompt = f"""Generate a complete SystemVerilog module for the following specification.

Module: {spec.module_name}
Description: {spec.description}
Clock period: {spec.clock_period}ns
{param_str}
{port_str}

Module signature (MUST match exactly):
```
{spec.module_signature}
```
{sample_io}

Output the complete module implementation in a ```systemverilog code block."""

    return system, prompt


def build_fixer_prompt(
    rtl_source: str,
    error_log: str,
    spec: Spec,
    testbench_source: str | None = None,
    error_type: str = "compilation",
) -> tuple[str, str]:
    system = f"""{SYSTEM_BASE}

You are fixing a SystemVerilog file that failed {error_type}.
Fix ONLY the errors shown in the error log.
Do NOT change the module signature.
Return the complete corrected file in a ```systemverilog code block."""

    tb_section = ""
    if testbench_source:
        tb_section = f"\nTestbench (read-only, do NOT modify):\n```systemverilog\n{testbench_source}\n```"

    prompt = f"""Fix this SystemVerilog file.

Error log:
```
{error_log}
```

Original spec:
  Module: {spec.module_name}
  Description: {spec.description}
  Module signature: {spec.module_signature}
{tb_section}

Current source:
```systemverilog
{rtl_source}
```

Return the complete corrected file."""

    return system, prompt


def build_optimizer_prompt(
    rtl_source: str,
    metrics: dict,
    score: float,
    spec: Spec,
) -> tuple[str, str]:
    system = f"""{SYSTEM_BASE}

You are optimizing an RTL design to improve its physical implementation score.
The design has already passed functional verification.
Focus on changes that improve timing (WNS/TNS), power, or area WITHOUT breaking functionality."""

    prompt = f"""Optimize this design. Current score: {score}/100

Metrics:
  WNS (setup slack): {metrics.get('timing__setup__ws', 'N/A')}
  TNS (total negative slack): {metrics.get('timing__setup__tns', 'N/A')}
  Power: {metrics.get('power__total', 'N/A')}
  Area: {metrics.get('design__instance__area', 'N/A')}

Spec: {spec.module_name} ({spec.design_type}), clock={spec.clock_period}ns

Current source:
```systemverilog
{rtl_source}
```

Module signature (MUST NOT change): {spec.module_signature}

Return the optimized module in a ```systemverilog code block."""

    return system, prompt
