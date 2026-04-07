from __future__ import annotations
import re
from pathlib import Path
import yaml

from .models import Port, Spec


def _sanitize_yaml(content: str) -> str:
    """Strip stimulus/expected sections that use Python-like syntax invalid in YAML."""
    # Remove lines in stimulus/expected blocks that contain bare * or + operators
    # These sections aren't needed for RTL generation
    lines = content.split("\n")
    result = []
    skip_indent = None
    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if skip_indent is not None:
            if stripped == "" or indent > skip_indent:
                continue
            else:
                skip_indent = None
        if re.match(r"^(stimulus|expected_\w+)\s*:", stripped):
            skip_indent = indent
            continue
        result.append(line)
    return "\n".join(result)


def classify_design_type(description: str, ports: dict, parameters: dict) -> str:
    desc_lower = description.lower()

    has_clock = any(name in ("clk", "clock") for name in ports)

    if not has_clock:
        return "combinational"

    fsm_keywords = ["detect", "fsm", "state machine", "sequence", "controller", "arbiter"]
    if any(kw in desc_lower for kw in fsm_keywords):
        return "fsm"

    pipeline_keywords = ["pipeline", "pipelined", "stage", "filter", "fir", "iir",
                         "dot product", "accumul", "taylor", "exponential"]
    if any(kw in desc_lower for kw in pipeline_keywords):
        return "pipelined"

    if parameters:
        return "pipelined"

    return "pipelined"


def parse_spec(yaml_path: Path) -> Spec:
    with open(yaml_path) as f:
        content = f.read()

    try:
        raw = yaml.safe_load(content)
    except yaml.YAMLError:
        raw = yaml.safe_load(_sanitize_yaml(content))

    module_name = list(raw.keys())[0]
    data = raw[module_name]

    ports = []
    port_names = {}
    for p in data.get("ports", []):
        port = Port(
            name=p["name"],
            direction=p["direction"],
            type=p.get("type", "logic"),
            description=p.get("description", ""),
            width=p.get("width"),
        )
        ports.append(port)
        port_names[p["name"]] = port

    parameters = {}
    params_raw = data.get("parameters", {})
    if isinstance(params_raw, dict):
        for k, v in params_raw.items():
            if isinstance(v, int):
                parameters[k] = v
            elif isinstance(v, str):
                match = re.match(r"(\d+)", v.strip())
                if match:
                    parameters[k] = int(match.group(1))

    clock_str = data.get("clock_period", "0ns")
    if isinstance(clock_str, str):
        clock_period = float(re.sub(r"[a-zA-Z]", "", clock_str))
    else:
        clock_period = float(clock_str)

    design_type = classify_design_type(
        data.get("description", ""),
        port_names,
        parameters,
    )

    return Spec(
        module_name=module_name,
        design_type=design_type,
        clock_period=clock_period,
        ports=ports,
        parameters=parameters,
        module_signature=data.get("module_signature", "").strip(),
        description=data.get("description", ""),
        yaml_raw=data,
    )
