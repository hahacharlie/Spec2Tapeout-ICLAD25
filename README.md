# Spec-to-Tapeout: LLM Agent for Automated ASIC Design

An LLM-powered multi-agent pipeline that reads YAML hardware specifications and produces tapeout-ready ASIC designs targeting **SkyWater 130nm HD (sky130hd)**.

Built for the **ASU ICLAD 2025 Hackathon** (EEE 598 — Spec2Tapeout).

## Quick Start

```bash
# 1. Clone
git clone https://github.com/hahacharlie/Spec2Tapeout-ICLAD25.git
cd Spec2Tapeout-ICLAD25

# 2. Install dependencies
pip install openai pyyaml

# 3. Set your API key
export OPENAI_API_KEY="sk-..."

# 4. Ensure Docker is running (required for OpenROAD-flow-scripts)
docker pull openroad/flow-ubuntu22.04-builder:836842

# 5. Run
./run.sh
```

## Dependencies

| Dependency | Purpose |
|---|---|
| Python 3.10+ | Agent runtime |
| `openai` (pip) | LLM API client |
| `pyyaml` (pip) | YAML spec parsing |
| Docker | Runs ORFS (OpenROAD-flow-scripts) for physical synthesis |
| Icarus Verilog (`iverilog`) | Functional verification of generated RTL |

## How to Run

### Visible problems (default)

```bash
./run.sh
```

### Hidden test cases

```bash
./run.sh --problems problems/hidden/*.yaml --output solutions/hidden/
```

### Single problem

```bash
./run.sh --problems problems/visible/p1.yaml --output solutions/visible/
```

The script is a thin wrapper around the agent entry point:
```bash
cd solutions && python spec2tapeout_agent.py --problems <yaml_files> --output <dir>
```

## Input / Output

### Input
YAML specification files in `problems/visible/` (or `problems/hidden/`). Each YAML defines:
- Module name and signature
- Port definitions (direction, type, width)
- Design type (FSM, pipelined, combinational)
- Clock period
- Technology node (sky130hd)

### Output
Per problem, the agent produces in `solutions/visible/pN/`:
- `<module_name>.v` — synthesizable SystemVerilog RTL
- `6_final.odb` — OpenROAD database (tapeout-ready layout)
- `6_final.sdc` — timing constraints from the physical flow

## Pipeline Workflow

```
YAML Spec
   │
   ├─► Spec Interpreter ──► parse ports, clock, design type
   │
   ├─► RTL Generator ──► 3 strategies (textbook, timing_opt, area_opt)
   │       │                 via LLM (GPT-5.3-codex / GPT-5.4)
   │       ▼
   ├─► Verification ──► iverilog compile + testbench simulation
   │       │               up to 3 fix-and-retry cycles per candidate
   │       ▼
   ├─► ORFS (Docker) ──► Yosys → Floorplan → Place → CTS → Route → Final
   │       │
   │       ▼
   ├─► Ranker ──► score against reference (WNS/TNS/Power/Area)
   │       │
   │       ▼
   └─► Optimizer ──► if score < 85, LLM refines best candidate
```

All 5 problems run in parallel. Each problem generates 3 RTL candidates in parallel, verifies them, runs ORFS, ranks, and optionally optimizes.

## Expected Results

| Problem | Module | Type | Score |
|---------|--------|------|-------|
| P1 | `seq_detector_0011` | FSM | ~94/100 |
| P5 | `dot_product` | Pipelined | ~76/100 |
| P7 | `exp_fixed_point` | Pipelined | ~82/100 |
| P8 | `fp16_multiplier` | Combinational | ~63/100 |
| P9 | `fir_filter` | Pipelined | ~65/100 |

Scores are on a 100-point scale: WNS (40pts), TNS (20pts), Power (20pts), Area (20pts).

## Repository Structure

```
.
├── run.sh                          # Single entry point
├── README.md                       # This file
├── solutions/
│   ├── spec2tapeout_agent.py       # Main pipeline orchestrator
│   ├── agents/
│   │   ├── llm_client.py           # LLM API abstraction (OpenAI)
│   │   ├── spec_interpreter.py     # YAML spec parser
│   │   ├── prompts.py              # System/user prompts for RTL generation
│   │   ├── rtl_generator.py        # Multi-strategy RTL generation
│   │   ├── rtl_fixer.py            # LLM-based error correction
│   │   ├── verification.py         # iverilog compile + simulate
│   │   ├── sdc_config_generator.py # SDC + ORFS config.mk generation
│   │   ├── orfs_runner.py          # Docker-based ORFS execution
│   │   ├── ranker.py               # Score candidates from ORFS metrics
│   │   └── models.py               # Data models (Spec, Candidate, etc.)
│   └── visible/p{1,5,7,8,9}/      # Output solutions (RTL + ODB + SDC)
├── problems/
│   └── visible/p{1,5,7,8,9}.yaml  # Problem specifications
├── evaluation/
│   ├── evaluate_verilog.py         # Functional verification script
│   ├── evaluate_openroad.py        # Physical evaluation script
│   └── visible/p{1,5,7,8,9}/      # Testbenches + reference metrics
└── example_outputs/
    └── run_log.txt                 # Example agent execution log
```

## Configuration

The LLM backend is configured in `solutions/agents/llm_client.py`. To switch models or providers, edit the `MODEL_MAP` and `get_client()` function. The agent supports any OpenAI-compatible API.

## Runtime

A full run (5 problems) takes approximately 30-60 minutes depending on LLM latency and ORFS synthesis time. ORFS runs are the bottleneck (~5-15 min per design).
