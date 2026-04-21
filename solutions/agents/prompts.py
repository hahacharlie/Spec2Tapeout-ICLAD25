from __future__ import annotations
import os

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
- For multipliers, consider breaking into stages or using a balanced reduction tree
- Minimize logic depth between any two flip-flops
- Use balanced binary trees / carry-save style reductions for wide arithmetic operations"""

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
- For FIR filters that must keep one output per cycle, a transposed-form FIR often gives
  much better timing than a direct-form linear accumulator because each stage becomes
  roughly one multiply + one add.
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
  * If timing is tight, prefer explicit partial-product generation plus balanced / carry-save
    reduction over a monolithic arithmetic expression that may synthesize into a deep chain
  * Final output: single always_comb with defaults at top, or ternary assign chain""",
}

RTL_TIMING_VARIANT_HINTS = {
    "fsm": {
        "compact_decode": "Prefer compact case/unique-case decode logic and avoid long priority chains in next-state/output logic.",
        "registered_outputs": "Prefer registered outputs and shallow output decode, while preserving the observable behavior.",
    },
    "pipelined": {
        "balanced_tree": "Use balanced reduction trees instead of linear accumulation. If there is a sum-of-products structure, explicitly organize it as a tree.",
        "latency_preserving_retime": "Preserve cycle-level interface behavior but move/register intermediate computations so the last stage feeding each register is shallow.",
        "streaming_mac": "For FIR / dot-product / MAC-heavy datapaths, prefer streaming structures such as transposed FIR or local registered partial sums that keep one output per cycle.",
    },
    "combinational": {
        "parallel_special_cases": "Compute special-case detection, sign, exponent, normalization, and rounding candidates in parallel, then select the result with a shallow final mux.",
        "balanced_reduction": "For arithmetic-heavy datapaths, explicitly request balanced partial-product reduction / carry-save style accumulation rather than a serial adder chain.",
        "shallow_output_mux": "Keep the final output-select logic shallow by precomputing candidate outputs and avoiding cascaded priority muxes.",
    },
}

TIMING_REPAIR_VARIANT_HINTS = {
    "fsm": {
        "output_shallow": "Reduce output decode depth first; keep the logic cone into the output register shallow.",
        "state_decode_compact": "Use compact state decode and avoid repeated wide condition checks.",
    },
    "pipelined": {
        "tree_reduction": "Replace serial arithmetic chains with balanced trees or local registered partial sums.",
        "retime_last_stage": "Retarget the worst endpoint by shortening only the final stage feeding it; keep the cycle-level protocol the same.",
        "streaming_structure": "Prefer transposed/streaming MAC structures when the path looks like a direct-form accumulation chain.",
    },
    "combinational": {
        "critical_cone_only": "Only optimize the identified critical logic cone; keep unrelated logic unchanged.",
        "parallelize_normalize_round": "Parallelize normalization, exponent adjust, and rounding as much as possible before the final mux.",
        "balanced_multiplier": "Use explicit balanced partial-product reduction / carry-save style structures for the multiplier portion of the critical path.",
    },
}

TIMING_REPAIR_HINTS = {
    "fsm": """Timing-closure guidance for FSMs:
- Reduce decode depth in next-state and output logic
- Prefer compact case statements over long priority if/else chains
- Register outputs when possible without changing externally observed behavior
- Keep state encoding simple and synthesis-friendly""",

    "pipelined": """Timing-closure guidance for pipelined datapaths:
- PRIMARY GOAL: reduce the longest combinational path while preserving verified behavior
- Prefer retiming or rebalancing existing logic before adding new latency
- Only add a new pipeline stage if the interface/protocol already supports latency changes
  (for example, a valid/enable pipeline) AND the externally observed behavior can still
  pass the same testbench
- Use balanced adder trees instead of linear accumulation chains
- Register multiplier outputs or partial sums to break deep MAC paths
- For FIR filters, strongly prefer a transposed-form FIR or registered partial sums to keep one result
  per cycle while reducing accumulation depth; avoid a direct-form linear sum of all taps in one cycle
- For fixed-point polynomial approximations, split term generation / normalization /
  accumulation into separate shallow stages""",

    "combinational": """Timing-closure guidance for combinational logic:
- The module has no clocked datapath interface, so DO NOT add pipeline registers or
  sequential latency
- Keep the implementation purely combinational and functionally equivalent
- Reduce logic depth by parallelizing special-case detection, normalization, and rounding
- Avoid long cascaded priority mux chains; precompute candidate results and select among them
- For arithmetic-heavy multipliers, use balanced partial-product reduction / carry-save structure
  rather than a long serial carry-propagation chain when possible
- Prefer continuous assigns for sub-expressions so synthesis can optimize structure better""",
}


def get_generation_variants(spec: Spec, strategy: str) -> list[str | None]:
    if strategy != "timing_opt":
        return [None]

    variant_limit = max(1, int(os.getenv("RTL_TIMING_VARIANT_COUNT", "3")))
    hints = RTL_TIMING_VARIANT_HINTS.get(spec.design_type, {})
    variants = list(hints.keys())[:variant_limit]
    return [None] + variants



def get_timing_repair_variants(spec: Spec, attempt: int) -> list[str | None]:
    variant_limit = max(1, int(os.getenv("TIMING_REPAIR_VARIANT_COUNT", "2")))
    hints = TIMING_REPAIR_VARIANT_HINTS.get(spec.design_type, {})
    variants = list(hints.keys())
    if attempt > 1:
        variants = variants[::-1]
    return [None] + variants[:variant_limit]



def build_rtl_prompt(spec: Spec, strategy: str, variant: str | None = None) -> tuple[str, str]:
    strategy_text = {
        "textbook": STRATEGY_TEXTBOOK,
        "timing_opt": STRATEGY_TIMING_OPT,
        "area_opt": STRATEGY_AREA_OPT,
    }[strategy]

    design_hint = DESIGN_TYPE_HINTS.get(spec.design_type, "")
    variant_hint = ""
    if variant is not None:
        variant_hint = RTL_TIMING_VARIANT_HINTS.get(spec.design_type, {}).get(variant, "")

    system = f"{SYSTEM_BASE}\n\n{strategy_text}\n\n{design_hint}"
    if variant_hint:
        system += f"\n\nTiming search variant: {variant}\n- {variant_hint}"

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

    variant_section = ""
    if variant is not None:
        variant_section = f"\nTiming search variant to prioritize: {variant}"

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
{sample_io}{variant_section}

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



def build_timing_closure_prompt(
    rtl_source: str,
    metrics: dict,
    spec: Spec,
    attempt: int,
    timing_report: str | None = None,
    timing_only: bool = False,
    testbench_source: str | None = None,
    variant: str | None = None,
    prior_attempt_summary: str | None = None,
) -> tuple[str, str]:
    timing_hint = TIMING_REPAIR_HINTS.get(spec.design_type, "")
    wns = metrics.get("timing__setup__ws", "N/A")
    tns = metrics.get("timing__setup__tns", "N/A")

    issues = []
    if isinstance(wns, (int, float)) and wns < 0:
        issues.append(
            f"Worst setup slack is negative (WNS={wns:.3f}ns). Shorten the longest path first."
        )
    if isinstance(tns, (int, float)) and tns < 0:
        issues.append(
            f"Total negative slack is negative (TNS={tns:.3f}ns). Many paths may need shallower logic."
        )
    if attempt >= 2:
        issues.append("Earlier timing-repair attempts were insufficient. Make a more aggressive structural change than before.")
    if not issues:
        issues.append("Timing is close to closure; make only conservative structural changes.")

    mode_text = ""
    if timing_only:
        mode_text = """
TIMING-ONLY MODE:
- Ignore score, area, and power until setup timing is closed
- Favor aggressive structural timing improvements over small cosmetic edits
- It is acceptable for area or power to increase if that is required to close timing
- For combinational modules, stay purely combinational; use structural decomposition instead of pipelining"""

    variant_hint = ""
    if variant is not None:
        variant_hint = TIMING_REPAIR_VARIANT_HINTS.get(spec.design_type, {}).get(variant, "")

    system = f"""{SYSTEM_BASE}

You are performing a targeted timing-closure repair pass on an RTL design.
The design has already passed functional verification.
PRIMARY GOAL: achieve non-negative setup timing (WNS >= 0 and TNS >= 0) WITHOUT breaking functionality.
Preserve the exact module signature.
Make focused structural changes instead of cosmetic rewrites.
{mode_text}

{timing_hint}"""
    if variant_hint:
        system += f"\n\nTiming repair variant: {variant}\n- {variant_hint}"

    timing_report_section = ""
    if timing_report:
        timing_report_section = f"""
OpenROAD timing diagnostics (critical path excerpt and repair notes):
```text
{timing_report}
```
"""

    priority_lines = [
        "- Close timing first.",
        "- Preserve functionality and compatibility with the existing testbench.",
        "- Preserve the module signature exactly.",
        "- For combinational modules, remain purely combinational.",
        "- For sequential/pipelined modules, preserve externally visible behavior unless the protocol already supports latency and the new implementation still passes verification.",
        "- If the testbench checks cycle-by-cycle outputs, preserve that latency/throughput behavior.",
    ]
    if timing_only:
        priority_lines.append("- Timing-only mode is active: do not spend effort improving score, area, or power until timing closes.")

    testbench_section = ""
    if testbench_source:
        testbench_section = f"""
Testbench (read-only, use it to preserve observable latency/behavior):
```systemverilog
{testbench_source}
```
"""

    variant_section = ""
    if variant is not None:
        variant_section = f"Timing repair variant to prioritize: {variant}\n"

    prior_attempt_section = ""
    if prior_attempt_summary:
        prior_attempt_section = f"""
Prior timing-repair attempt summary (avoid repeating weak ideas):
```text
{prior_attempt_summary}
```
"""

    prompt = f"""Timing-closure attempt #{attempt}

Current metrics:
  WNS (setup slack): {wns}
  TNS (total negative slack): {tns}
  Power: {metrics.get('power__total', 'N/A')}
  Area: {metrics.get('design__instance__area', 'N/A')}

Priority:
{chr(10).join(priority_lines)}

Timing issues to address:
- {' '.join(issues)}

Spec: {spec.module_name} ({spec.design_type}), clock={spec.clock_period}ns
{variant_section}{timing_report_section}{prior_attempt_section}{testbench_section}
Current source:
```systemverilog
{rtl_source}
```

Module signature (MUST NOT change):
```
{spec.module_signature}
```

Return the repaired module in a ```systemverilog code block."""

    return system, prompt
