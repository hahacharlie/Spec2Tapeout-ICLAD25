# Spec-to-Tapeout: LLM Agent for Automated ASIC Design

An LLM-powered multi-agent pipeline that reads YAML hardware specifications and produces tapeout-ready ASIC designs targeting **SkyWater 130nm HD (sky130hd)**.

Built for the **ASU ICLAD 2025 Hackathon** (EEE 598 — Project 2).

## Prerequisites


| Dependency | Purpose |
|---|---|
| **Python 3.10** | Agent runtime |
| **Docker** | Required by ORFS for physical synthesis |
| **Icarus Verilog** (`iverilog`) | Functional verification of generated RTL |
| **Codex CLI** (`codex`) | LLM backend used by the agent |
| **[OpenROAD-flow-scripts](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts)** | Physical synthesis flow -- included as the `OpenROAD-flow-scripts/` git submodule and built via its Docker setup (see [BuildWithDocker.md](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts/blob/master/docs/user/BuildWithDocker.md)) |


### Install system dependencies

**Ubuntu/Debian:**

```bash
sudo apt update
sudo apt install -y python3.10 python3.10-venv iverilog docker.io
```

**Arch Linux:**

```bash
sudo pacman -S python iverilog docker
```

**macOS (Homebrew):**

```bash
brew install python@3.10 icarus-verilog docker
```

Make sure Docker is running:

```bash
sudo systemctl start docker
```

## Quick Start

```bash
# 1. Clone this repo and initialize the OpenROAD-flow-scripts submodule
git clone --recurse-submodules https://github.com/hahacharlie/Spec2Tapeout-ICLAD25.git
cd Spec2Tapeout-ICLAD25

# If you already cloned without submodules:
git submodule update --init --recursive

# 2. Create and activate a Python 3.10 virtual environment
python3.10 -m venv .venv
source .venv/bin/activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Install and authenticate Codex CLI
#    Example install:
#    npm install -g @openai/codex
codex login

# 5. Optional: choose the Codex model
export CODEX_MODEL="gpt-5.4"

# 6. Set up ORFS Docker (follow OpenROAD-flow-scripts instructions)
#    See: OpenROAD-flow-scripts/docs/user/BuildWithDocker.md
cd OpenROAD-flow-scripts
sudo ./setup.sh
./build_openroad.sh
cd ..

# 7. Run
#    run.sh checks that Codex CLI is installed and already authenticated
./run.sh
```

## How to Run

### All visible problems (default)

```bash
./run.sh
```

### Hidden test cases

```bash
./run.sh --suite hidden --problems problems/hidden/*.yaml --output solutions/hidden/
```

### Single problem

```bash
./run.sh --problems problems/visible/p1.yaml --output solutions/visible/
```

### Single problem with JSON report

```bash
./run.sh --problems problems/visible/p8.yaml --output solutions/out \
  --report-json solutions/out/report.json
```

### Help

```bash
./run.sh --help
```

`run.sh` performs a small preflight before starting the pipeline:

- verifies `codex` is installed
- verifies `codex login` has already been completed
- parses flags like `--problems`, `--suite`, `--output`, `--report-json`, `--workspace`, and `--flow-root`
- interprets relative paths from the repository root
- prints the selected Codex model

A single invocation may target only one suite. Mixing `problems/visible/...` and `problems/hidden/...`
in the same run is rejected, and the pipeline never falls back from hidden collateral to visible collateral.

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

- `<module_name>.v` -- synthesizable SystemVerilog RTL
- `6_final.odb` -- OpenROAD database (tapeout-ready layout)
- `6_final.sdc` -- timing constraints from the physical flow

## Pipeline Workflow

```
YAML Spec
   |
   +-> Spec Interpreter --> parse ports, clock, design type
   |
   +-> RTL Generator --> 3 strategies (textbook, timing_opt, area_opt)
   |       |                via Codex CLI (default model: gpt-5.4)
   |       v
   +-> Verification --> iverilog compile + testbench simulation
   |       |              up to 3 fix-and-retry cycles per candidate
   |       v
   +-> ORFS (Docker) --> Yosys -> Floorplan -> Place -> CTS -> Route -> Final
   |       |
   |       v
   +-> Ranker --> score against reference (WNS/TNS/Power/Area)
   |       |
   |       v
   +-> Optimizer --> if score < 85, LLM refines best candidate
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

## Evaluation

### Functional verification (iVerilog)

```bash
source .venv/bin/activate
cd evaluation
python evaluate_verilog.py \
  --verilog ../solutions/visible/p1/seq_detector_0011.v \
  --problem 1 \
  --tb visible/p1/iclad_seq_detector_tb.v
```

### Physical evaluation (OpenROAD)

```bash
source .venv/bin/activate
cd evaluation
python evaluate_openroad.py \
  --odb ../solutions/visible/p1/6_final.odb \
  --sdc ../solutions/visible/p1/6_final.sdc \
  --flow_root ../OpenROAD-flow-scripts \
  --problem 1
```

## Repository Structure

```
.
├── run.sh                          # Single entry point
├── requirements.txt                # Python dependencies
├── README.md                       # This file
├── solutions/
│   ├── spec2tapeout_agent.py       # Main pipeline orchestrator
│   ├── agents/
│   │   ├── llm_client.py           # Codex CLI abstraction
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

The LLM backend is configured in `solutions/agents/llm_client.py` and now uses Codex CLI directly instead of the Python OpenAI client. By default the agent calls `codex exec` with model `gpt-5.4`. You can override this with:

```bash
export CODEX_MODEL="gpt-5.4"
export CODEX_CLI_PATH="codex"
export CODEX_SANDBOX="read-only"
```

If Codex is not authenticated yet, run:

```bash
codex login
```

## Runtime

A full run (5 problems) takes approximately 30-60 minutes depending on LLM latency and ORFS synthesis time. ORFS runs are the bottleneck (~5-15 min per design).
