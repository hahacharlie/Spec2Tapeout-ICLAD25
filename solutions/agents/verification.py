from __future__ import annotations
import subprocess
import tempfile
from pathlib import Path

_last_exe: Path | None = None


def compile_verilog(
    verilog_path: Path,
    testbench_path: Path,
    output_dir: Path | None = None,
) -> tuple[bool, str]:
    global _last_exe
    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp())
    exe_path = output_dir / "sim.out"
    _last_exe = exe_path

    cmd = [
        "iverilog",
        "-Wall",
        "-g2012",
        "-o", str(exe_path),
        str(verilog_path),
        str(testbench_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    log = result.stdout + result.stderr
    success = result.returncode == 0
    return success, log


def run_simulation(exe_path: Path | None = None, timeout: int = 60) -> tuple[bool, str]:
    global _last_exe
    if exe_path is None:
        exe_path = _last_exe
    if exe_path is None or not exe_path.exists():
        return False, "No compiled executable found"

    result = subprocess.run(
        ["vvp", str(exe_path)],
        capture_output=True, text=True, timeout=timeout,
    )
    log = result.stdout + result.stderr
    passed = check_result(log)

    try:
        exe_path.unlink(missing_ok=True)
    except OSError:
        pass

    return passed, log


def check_result(output: str) -> bool:
    output_upper = output.upper()
    has_pass = "PASS" in output_upper
    has_fail = "FAIL" in output_upper
    if has_pass and not has_fail:
        return True
    if has_fail:
        return False
    return False


async def verify_candidate(
    rtl_source: str,
    testbench_path: Path,
    work_dir: Path,
) -> tuple[bool, str, str]:
    v_path = work_dir / "design.v"
    v_path.parent.mkdir(parents=True, exist_ok=True)
    v_path.write_text(rtl_source)

    compile_ok, compile_log = compile_verilog(v_path, testbench_path, work_dir)
    if not compile_ok:
        return False, compile_log, ""

    exe_path = work_dir / "sim.out"
    passed, sim_log = run_simulation(exe_path)
    return passed, compile_log, sim_log
