from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from .models import ScoredCandidate
from .orfs_runner import DOCKER_IMAGE

_TIMING_DIAGNOSTICS_CACHE: dict[tuple[str, str, str], str] = {}
_LOG_FILES_IN_PRIORITY = [
    "4_1_cts.log",
    "3_4_place_resized.log",
    "6_report.log",
]


def find_logs_dir(odb_path: Path) -> Path | None:
    """Find the ORFS logs directory corresponding to a final ODB path."""
    odb_str = str(odb_path)
    if "/results/" in odb_str:
        logs_dir = Path(odb_str.replace("/results/", "/logs/")).parent
        if logs_dir.exists():
            return logs_dir

    for parent in odb_path.parents:
        if parent.name == "results":
            candidate = parent.parent / "logs"
            if candidate.exists():
                rel_parent = odb_path.parent.relative_to(parent)
                mapped = candidate / rel_parent
                if mapped.exists():
                    return mapped
                return candidate
    return None


def find_work_dir(odb_path: Path) -> Path | None:
    """Return the ORFS strategy workspace that contains results/ and logs/."""
    for parent in odb_path.parents:
        if parent.name == "results":
            return parent.parent
    return None


def extract_critical_path_from_text(text: str, max_lines: int = 120) -> str | None:
    """Extract a concise critical-path report from OpenROAD report_checks output."""
    lines = text.splitlines()
    summary_lines = [
        line.strip()
        for line in lines
        if line.startswith("worst slack max") or line.startswith("tns max")
    ]

    path_start = None
    path_end = None
    for idx, line in enumerate(lines):
        if line.startswith("Startpoint:"):
            path_start = idx
            continue
        if path_start is not None and "slack" in line and ("VIOLATED" in line or re.search(r"\bslack\b", line)):
            path_end = idx
            break

    if path_start is None:
        return "\n".join(summary_lines).strip() or None

    block = lines[path_start:path_end + 1 if path_end is not None else min(len(lines), path_start + max_lines)]
    if len(block) > max_lines:
        block = block[:max_lines]

    extracted = []
    if summary_lines:
        extracted.extend(summary_lines)
        extracted.append("")
    extracted.extend(block)
    return "\n".join(extracted).strip() or None



def extract_architecture_hints_from_timing_report(report_text: str) -> list[str]:
    """Infer architectural hints from a critical-path excerpt.

    These are intentionally high-level and prompt-friendly. They are not specific
    to a single benchmark, but they capture common arithmetic timing path shapes.
    """
    hints: list[str] = []

    lower = report_text.lower()
    full_adders = len(re.findall(r"sky130_fd_sc_hd__fa_", lower))
    half_adders = len(re.findall(r"sky130_fd_sc_hd__ha_", lower))
    startpoint_match = re.search(r"Startpoint:\s*(.+)", report_text)
    endpoint_match = re.search(r"Endpoint:\s*(.+)", report_text)
    startpoint = startpoint_match.group(1).strip() if startpoint_match else ""
    endpoint = endpoint_match.group(1).strip() if endpoint_match else ""

    if full_adders + half_adders >= 4:
        hints.append(
            "Critical path is dominated by an arithmetic reduction / carry-propagation chain (many FA/HA cells). "
            "Use a carry-save / Wallace-style reduction tree or a more balanced partial-product / adder structure instead of a long serial sum chain."
        )

    if "(input port clocked by virtual_clk)" in lower and "(output port clocked by virtual_clk)" in lower:
        hints.append(
            "Critical path is pure input-to-output combinational logic. Keep special-case handling, exponent path, normalization, and rounding in parallel as much as possible, then select the final result with a shallow mux structure."
        )

    if endpoint and "$_sdff" in endpoint.lower():
        hints.append(
            f"Worst endpoint is a register D pin ({endpoint}). The final stage feeding that register is too deep; restructure the datapath so the last stage before the endpoint is much shallower."
        )
        if "y_out" in endpoint or "dot_out" in endpoint or "exp_out" in endpoint:
            hints.append(
                "Because the worst endpoint is an output register, prioritize breaking the final accumulation / normalization stage before the output register. For FIR-like datapaths, a transposed form or registered partial sums usually shortens the last stage while keeping one output per cycle."
            )

    if startpoint and ("(input port" in startpoint.lower() or "(rising edge-triggered flip-flop" in startpoint.lower()):
        hints.append(
            f"Current critical path starts at {startpoint} and ends at {endpoint or 'the observed endpoint'}. Optimize the logic cone between these two points first; avoid rewriting unrelated logic."
        )

    unique_hints: list[str] = []
    seen = set()
    for hint in hints:
        if hint not in seen:
            seen.add(hint)
            unique_hints.append(hint)
    return unique_hints


def _parse_repair_timing_rows(text: str) -> list[dict[str, str | float]]:
    rows: list[dict[str, str | float]] = []
    for line in text.splitlines():
        if "|" not in line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 12:
            continue
        iter_token = parts[0]
        if not re.match(r"^(?:\d+\*?|final)$", iter_token):
            continue
        try:
            wns = float(parts[7])
        except ValueError:
            continue
        endpoint = parts[11]
        rows.append({"iter": iter_token, "wns": wns, "endpoint": endpoint})
    return rows


def extract_log_hints_from_text(log_name: str, text: str) -> list[str]:
    """Extract short, prompt-friendly timing hints from OpenROAD log text."""
    hints: list[str] = []

    if "No registers in design" in text:
        hints.append(f"{log_name}: no registers in design; timing must be fixed structurally without adding sequential timing repair inside ORFS")

    match = re.search(r"Found\s+(\d+)\s+endpoints with setup violations\.", text)
    if match:
        hints.append(f"{log_name}: found {match.group(1)} setup-violating endpoints during OpenROAD timing repair")

    rows = _parse_repair_timing_rows(text)
    if rows:
        start = rows[0]
        best = max(rows, key=lambda row: float(row["wns"]))
        end = rows[-1]
        hints.append(
            f"{log_name}: initial repair WNS {float(start['wns']):.3f} at {start['iter']} (worst endpoint {start['endpoint']})"
        )
        if best is not start:
            hints.append(
                f"{log_name}: best repair WNS {float(best['wns']):.3f} at {best['iter']} (worst endpoint {best['endpoint']})"
            )
        if end is not best and end is not start:
            hints.append(
                f"{log_name}: final repair WNS {float(end['wns']):.3f} at {end['iter']} (worst endpoint {end['endpoint']})"
            )

    unique_hints: list[str] = []
    seen = set()
    for hint in hints:
        if hint not in seen:
            seen.add(hint)
            unique_hints.append(hint)
    return unique_hints


def extract_openroad_log_hints(logs_dir: Path, max_hints: int = 6) -> str:
    hints: list[str] = []
    for name in _LOG_FILES_IN_PRIORITY:
        log_path = logs_dir / name
        if not log_path.exists():
            continue
        text = log_path.read_text(errors="ignore")
        hints.extend(extract_log_hints_from_text(name, text))

    unique_hints: list[str] = []
    seen = set()
    for hint in hints:
        if hint not in seen:
            seen.add(hint)
            unique_hints.append(hint)

    if not unique_hints:
        return ""
    return "\n".join(f"- {hint}" for hint in unique_hints[:max_hints])


def _build_timing_report_tcl(odb_path: str, sdc_path: str, spef_path: str | None = None) -> str:
    spef_clause = ""
    if spef_path:
        spef_clause = f"""
if {{ [file exists \"{spef_path}\"] }} {{
  read_spef \"{spef_path}\"
}} else {{
  source \"$platform_dir/setRC.tcl\"
}}
"""
    else:
        spef_clause = "source \"$platform_dir/setRC.tcl\"\n"

    return f"""
set platform_dir \"/OpenROAD-flow-scripts/flow/platforms/sky130hd\"
set lib \"$platform_dir/lib/sky130_fd_sc_hd__tt_025C_1v80.lib\"
read_liberty $lib
read_db \"{odb_path}\"
read_sdc \"{sdc_path}\"
{spef_clause}
puts \"===REPORT_WNS===\"
report_worst_slack
puts \"===REPORT_TNS===\"
report_tns
if {{ [llength [all_registers]] != 0 }} {{
  puts \"===REPORT_CHECKS_MAX_REG2REG===\"
  report_checks -path_delay max -from [all_registers] -to [all_registers] \
    -format full_clock_expanded -fields {{slew cap input net fanout}} \
    -group_path_count 1 -endpoint_path_count 1
}}
puts \"===REPORT_CHECKS_MAX===\"
report_checks -path_delay max -format full_clock_expanded -fields {{slew cap input net fanout}} \
  -group_path_count 1 -endpoint_path_count 1
puts \"===DONE===\"
"""


def _run_openroad_report_locally(
    openroad_bin: Path,
    flow_root: Path,
    odb_path: Path,
    sdc_path: Path,
    spef_path: Path | None,
    timeout: int,
) -> str | None:
    platform_dir = flow_root / "flow" / "platforms" / "sky130hd"
    lib = platform_dir / "lib" / "sky130_fd_sc_hd__tt_025C_1v80.lib"
    if not lib.exists():
        return None

    script = f"""
set platform_dir \"{platform_dir}\"
set lib \"{lib}\"
read_liberty $lib
read_db \"{odb_path}\"
read_sdc \"{sdc_path}\"
"""
    if spef_path is not None and spef_path.exists():
        script += f"""
if {{ [file exists \"{spef_path}\"] }} {{
  read_spef \"{spef_path}\"
}} else {{
  source \"$platform_dir/setRC.tcl\"
}}
"""
    else:
        script += "source \"$platform_dir/setRC.tcl\"\n"
    script += """
puts \"===REPORT_WNS===\"
report_worst_slack
puts \"===REPORT_TNS===\"
report_tns
if { [llength [all_registers]] != 0 } {
  puts \"===REPORT_CHECKS_MAX_REG2REG===\"
  report_checks -path_delay max -from [all_registers] -to [all_registers] \
    -format full_clock_expanded -fields {slew cap input net fanout} \
    -group_path_count 1 -endpoint_path_count 1
}
puts \"===REPORT_CHECKS_MAX===\"
report_checks -path_delay max -format full_clock_expanded -fields {slew cap input net fanout} \
  -group_path_count 1 -endpoint_path_count 1
puts \"===DONE===\"
"""

    with tempfile.NamedTemporaryFile("w", suffix=".tcl", delete=False) as tcl_file:
        tcl_file.write(script)
        tcl_path = Path(tcl_file.name)

    try:
        result = subprocess.run(
            [str(openroad_bin), "-no_init", "-exit", str(tcl_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            return None
        return result.stdout + result.stderr
    finally:
        tcl_path.unlink(missing_ok=True)


def _run_openroad_report_in_docker(
    work_dir: Path,
    odb_path: Path,
    sdc_path: Path,
    spef_path: Path | None,
    timeout: int,
) -> str | None:
    container_odb = f"/work/{odb_path.relative_to(work_dir).as_posix()}"
    container_sdc = f"/work/{sdc_path.relative_to(work_dir).as_posix()}"
    container_spef = None
    if spef_path is not None and spef_path.exists():
        container_spef = f"/work/{spef_path.relative_to(work_dir).as_posix()}"

    script = _build_timing_report_tcl(container_odb, container_sdc, container_spef)
    with tempfile.NamedTemporaryFile("w", suffix=".tcl", delete=False) as tcl_file:
        tcl_file.write(script)
        tcl_path = Path(tcl_file.name)

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{work_dir.resolve()}:/work",
        "-v", f"{tcl_path.resolve()}:/tmp/timing_report.tcl",
        DOCKER_IMAGE,
        "bash", "-lc",
        "/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/openroad -no_init -exit /tmp/timing_report.tcl",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            return None
        return result.stdout + result.stderr
    finally:
        tcl_path.unlink(missing_ok=True)


def generate_critical_path_report(
    candidate: ScoredCandidate,
    flow_root: Path,
    timeout: int = 180,
) -> str | None:
    if candidate.odb_path is None:
        return None

    odb_path = candidate.odb_path.resolve()
    sdc_path = (candidate.sdc_path or odb_path.with_name("6_final.sdc")).resolve()
    if not sdc_path.exists():
        return None

    spef_path = odb_path.with_name("6_final.spef")
    if not spef_path.exists():
        spef_path = None

    openroad_bin = flow_root / "tools" / "install" / "OpenROAD" / "bin" / "openroad"
    raw_report = None
    if openroad_bin.exists():
        raw_report = _run_openroad_report_locally(
            openroad_bin=openroad_bin,
            flow_root=flow_root,
            odb_path=odb_path,
            sdc_path=sdc_path,
            spef_path=spef_path,
            timeout=timeout,
        )

    if raw_report is None:
        work_dir = find_work_dir(odb_path)
        if work_dir is None:
            return None
        raw_report = _run_openroad_report_in_docker(
            work_dir=work_dir,
            odb_path=odb_path,
            sdc_path=sdc_path,
            spef_path=spef_path,
            timeout=timeout,
        )

    if raw_report is None:
        return None
    return extract_critical_path_from_text(raw_report)


def get_timing_diagnostics(
    candidate: ScoredCandidate,
    flow_root: Path,
    max_chars: int = 8000,
) -> str:
    """Return concise timing diagnostics for use in a timing-repair prompt."""
    if candidate.odb_path is None:
        return ""

    cache_key = (
        str(candidate.odb_path),
        str(candidate.sdc_path or ""),
        str(flow_root),
    )
    cached = _TIMING_DIAGNOSTICS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    sections: list[str] = []

    logs_dir = find_logs_dir(candidate.odb_path)
    if logs_dir is not None:
        log_hints = extract_openroad_log_hints(logs_dir)
        if log_hints:
            sections.append("OpenROAD log hints:\n" + log_hints)

    critical_path = generate_critical_path_report(candidate, flow_root)
    if critical_path:
        arch_hints = extract_architecture_hints_from_timing_report(critical_path)
        if arch_hints:
            sections.append("Architecture hints inferred from timing path:\n" + "\n".join(f"- {hint}" for hint in arch_hints))
        sections.append("OpenROAD critical path:\n" + critical_path)

    diagnostics = "\n\n".join(section.strip() for section in sections if section.strip())
    if len(diagnostics) > max_chars:
        diagnostics = diagnostics[:max_chars].rstrip() + "\n...[truncated]"

    _TIMING_DIAGNOSTICS_CACHE[cache_key] = diagnostics
    return diagnostics
