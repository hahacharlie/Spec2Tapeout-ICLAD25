from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Port:
    name: str
    direction: str  # "input" or "output"
    type: str
    description: str
    width: int | None = None


@dataclass
class Spec:
    module_name: str
    design_type: str  # "fsm", "pipelined", "combinational"
    clock_period: float
    ports: list[Port]
    parameters: dict[str, int]
    module_signature: str
    description: str
    yaml_raw: dict = field(default_factory=dict)

    @property
    def clock_port_name(self) -> str | None:
        for p in self.ports:
            if p.name in ("clk", "clock"):
                return p.name
        return None

    @property
    def has_clock(self) -> bool:
        return self.clock_port_name is not None


@dataclass
class Candidate:
    rtl_source: str
    strategy: str  # "textbook", "timing_opt", "area_opt"
    passed: bool = False
    compile_log: str = ""
    sim_log: str = ""
    retry_count: int = 0


@dataclass
class ScoredCandidate:
    rtl_source: str
    strategy: str
    score: float = 0.0
    metrics: dict = field(default_factory=dict)
    odb_path: Path | None = None
    sdc_path: Path | None = None
    v_path: Path | None = None
