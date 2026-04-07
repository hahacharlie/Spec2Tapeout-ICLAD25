from __future__ import annotations
from .models import Spec

SYSTEM_BASE = """You are an expert digital hardware designer generating SystemVerilog-2012 RTL.
Target: SkyWater 130nm HD (sky130hd).
Compatibility: must pass BOTH iverilog -Wall -g2012 AND Yosys synthesis.
Rules:
- Use ONLY synthesizable constructs (no $display, $finish, initial blocks, delays)
- Match the module signature EXACTLY as provided — do not change port names, types, or widths
- Output ONLY the complete SystemVerilog module in a ```systemverilog code block
- No testbench code, no explanatory text outside the code block

Yosys compatibility (CRITICAL — violations cause ORFS to fail):
- NEVER use blocking assignments (=) to signals inside always_ff blocks — use only <=
- In always_comb: assign ALL outputs/variables in EVERY branch to prevent latch inference
  (Yosys errors: "Latch inferred for signal ... from always_comb process")
- Do NOT nest always blocks or mix initial/always constructs
- Prefer continuous assign statements over always_comb for simple combinational logic
- For complex combinational logic in always_comb, assign default values at the TOP of
  the block BEFORE any if/case statements
- Do NOT use blocking assignments to intermediate variables inside always_ff — move
  combinational calculations to separate always_comb blocks or assign statements"""

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
- Break computation into pipeline stages with registered boundaries (always_ff)
- All combinational logic between stages must be in separate always_comb or assign
- Track data validity through the pipeline with a valid/enable shift register
- Be careful with bit-width growth: multiplication doubles width, addition adds 1 bit
- Use $clog2 for computing address/index widths from parameters
- CRITICAL iverilog compatibility for packed arrays: indexing a signed packed array
  (e.g. A[i] where A is `logic signed [N-1:0][WIDTH-1:0]`) drops the signedness —
  the element becomes unsigned. Keep ALL intermediate storage UNSIGNED. Only apply
  $signed at the final output assignment if needed.
- For dot product: Do NOT use $signed() casts on packed array indices. Write
  `A[i] * B[i]` directly — iverilog treats indexed elements as unsigned, and the
  testbench relies on this behavior. Using $signed(A[i]) will produce WRONG results.
  Store products and accumulator as-is without sign casting.
- For Taylor series / fixed-point: all intermediate computations should use unsigned
  fixed-point. Compute divisions by constant (e.g. /2, /6) using right-shift or
  multiply-by-reciprocal (e.g. *43>>8 for /6). Keep pipeline stages balanced.
- NEVER put blocking assignments to intermediate signals inside always_ff — move
  combinational calculations (term computation, normalization) to assign statements
  or always_comb blocks, then register results in always_ff with <=.""",

    "combinational": """Design type: Combinational Logic
- No sequential elements needed in the datapath
- Handle ALL special cases explicitly (for IEEE 754: zero, subnormal, infinity, NaN)
- Use explicit rounding logic (round-to-nearest-even for IEEE 754)
- STRONGLY PREFER continuous assign statements over always_comb — this completely
  avoids latch inference errors in Yosys
- If you must use always_comb, set DEFAULT values for ALL outputs at the top of the
  block BEFORE any if/case logic. Example:
    always_comb begin
      result = '0;  // default
      if (...) result = ...;
      else if (...) result = ...;
    end
- For IEEE 754 FP16 multiplication:
  * Extract sign, exponent (5-bit), mantissa (10-bit) with continuous assigns
  * Add implicit leading 1 for normalized, 0 for subnormal
  * Multiply 11-bit mantissas → 22-bit product
  * Exponent sum = exp_a + exp_b - bias(15), handle normalize shift
  * Use continuous assigns for normalization, rounding, and special case muxing
  * Final output: single always_comb with defaults at top, or ternary assign chain""",
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
Fix the errors shown in the error log while ensuring the code remains Yosys-compatible.
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

    wns = metrics.get('timing__setup__ws', 0)
    tns = metrics.get('timing__setup__tns', 0)
    focus_areas = []
    if isinstance(wns, (int, float)) and wns < 0:
        focus_areas.append(f"TIMING CRITICAL: WNS={wns:.3f}ns — reduce combinational depth between registers. "
                          f"Break long paths with pipeline stages or restructure logic.")
    if isinstance(tns, (int, float)) and tns < -10:
        focus_areas.append(f"Many paths violating timing (TNS={tns:.1f}). Consider adding pipeline stages.")
    if not focus_areas:
        focus_areas.append("Timing is met. Focus on reducing area and power.")

    prompt = f"""Optimize this design. Current score: {score}/100

Metrics:
  WNS (setup slack): {wns}
  TNS (total negative slack): {tns}
  Power: {metrics.get('power__total', 'N/A')}
  Area: {metrics.get('design__instance__area', 'N/A')}

Priority: {' '.join(focus_areas)}

Spec: {spec.module_name} ({spec.design_type}), clock={spec.clock_period}ns

Current source:
```systemverilog
{rtl_source}
```

Module signature (MUST NOT change): {spec.module_signature}

Return the optimized module in a ```systemverilog code block."""

    return system, prompt
