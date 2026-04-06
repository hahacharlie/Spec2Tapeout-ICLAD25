from __future__ import annotations
import asyncio
import json
import subprocess
from pathlib import Path

from .models import Spec, ScoredCandidate

DOCKER_IMAGE = "openroad/flow-ubuntu22.04-builder:836842"
ORFS_TIMEOUT = 3600  # 1 hour


async def run_orfs(
    rtl_source: str,
    sdc_content: str,
    config_content: str,
    spec: Spec,
    work_dir: Path,
    semaphore: asyncio.Semaphore | None = None,
) -> ScoredCandidate | None:
    if semaphore:
        async with semaphore:
            return await _run_orfs_inner(rtl_source, sdc_content, config_content, spec, work_dir)
    return await _run_orfs_inner(rtl_source, sdc_content, config_content, spec, work_dir)


async def _run_orfs_inner(
    rtl_source: str,
    sdc_content: str,
    config_content: str,
    spec: Spec,
    work_dir: Path,
) -> ScoredCandidate | None:
    print(f"  [{spec.module_name}] Running ORFS in Docker...")
    work_dir.mkdir(parents=True, exist_ok=True)

    v_path = work_dir / f"{spec.module_name}.v"
    v_path.write_text(rtl_source)

    sdc_path = work_dir / "constraint.sdc"
    sdc_path.write_text(sdc_content)

    config_path = work_dir / "config.mk"
    config_path.write_text(config_content)

    results_dir = work_dir / "results"
    logs_dir = work_dir / "logs"
    results_dir.mkdir(exist_ok=True)
    logs_dir.mkdir(exist_ok=True)

    design_nickname = f"iclad_{spec.module_name}"

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{work_dir.resolve()}:/design",
        "-v", f"{results_dir.resolve()}:/OpenROAD-flow-scripts/flow/results",
        "-v", f"{logs_dir.resolve()}:/OpenROAD-flow-scripts/flow/logs",
        DOCKER_IMAGE,
        "bash", "-c",
        "cd /OpenROAD-flow-scripts/flow && make DESIGN_CONFIG=/design/config.mk finish",
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=ORFS_TIMEOUT,
        )

        if process.returncode != 0:
            print(f"  [{spec.module_name}] ORFS failed (exit {process.returncode})")
            log_output = stdout.decode() + stderr.decode()
            print(f"  Last 500 chars: {log_output[-500:]}")
            return None

    except asyncio.TimeoutError:
        print(f"  [{spec.module_name}] ORFS timed out after {ORFS_TIMEOUT}s")
        process.kill()
        return None

    odb_path = _find_output(results_dir, design_nickname, "6_final.odb")
    final_sdc_path = _find_output(results_dir, design_nickname, "6_final.sdc")

    if odb_path is None:
        print(f"  [{spec.module_name}] No 6_final.odb found in results")
        return None

    print(f"  [{spec.module_name}] ORFS completed successfully")
    return ScoredCandidate(
        rtl_source=rtl_source,
        strategy="",
        odb_path=odb_path,
        sdc_path=final_sdc_path,
        v_path=v_path,
    )


def _find_output(results_dir: Path, design_nickname: str, filename: str) -> Path | None:
    expected = results_dir / "sky130hd" / design_nickname / "base" / filename
    if expected.exists():
        return expected
    for p in results_dir.rglob(filename):
        return p
    return None


async def run_orfs_with_retry(
    rtl_source: str,
    sdc_content: str,
    config_content: str,
    spec: Spec,
    work_dir: Path,
    semaphore: asyncio.Semaphore | None = None,
) -> ScoredCandidate | None:
    result = await run_orfs(rtl_source, sdc_content, config_content, spec, work_dir, semaphore)
    if result is not None:
        return result

    print(f"  [{spec.module_name}] Retrying ORFS with relaxed utilization...")
    relaxed_config = _relax_utilization(config_content)
    retry_dir = work_dir.parent / f"{work_dir.name}_retry"
    return await run_orfs(rtl_source, sdc_content, relaxed_config, spec, retry_dir, semaphore)


def _relax_utilization(config_content: str) -> str:
    import re
    match = re.search(r"CORE_UTILIZATION\s*=\s*(\d+)", config_content)
    if match:
        old_val = int(match.group(1))
        new_val = max(10, old_val - 10)
        config_content = config_content.replace(
            f"CORE_UTILIZATION = {old_val}",
            f"CORE_UTILIZATION = {new_val}",
        )
    return config_content
