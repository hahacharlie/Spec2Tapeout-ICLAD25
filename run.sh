#!/usr/bin/env bash
# Single entry point for the Spec-to-Tapeout agentic workflow.
# Usage: ./run.sh [--problems <yaml_glob>] [--output <dir>]
#
# Examples:
#   ./run.sh                                         # run visible problems
#   ./run.sh --problems problems/hidden/*.yaml       # run hidden problems
#   ./run.sh --problems problems/visible/p1.yaml     # run a single problem

set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

# Activate virtual environment if not already active
if [ -z "${VIRTUAL_ENV:-}" ]; then
    if [ -f "$ROOT/.venv/bin/activate" ]; then
        source "$ROOT/.venv/bin/activate"
    else
        echo "Error: Virtual environment not found. Set it up first:"
        echo "  python3.10 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
        exit 1
    fi
fi

cd "$ROOT/solutions"

PROBLEMS="${1:---problems}"
if [ "$PROBLEMS" = "--problems" ]; then
    shift 2>/dev/null || true
    PROBLEM_GLOB="${1:-../problems/visible/*.yaml}"
    shift 2>/dev/null || true
else
    PROBLEM_GLOB="../problems/visible/*.yaml"
fi

OUTPUT="${1:-visible/}"

echo "=== Spec-to-Tapeout Agent Pipeline ==="
echo "Python:   $(python --version 2>&1)"
echo "Problems: $PROBLEM_GLOB"
echo "Output:   $OUTPUT"
echo ""

exec python spec2tapeout_agent.py --problems $PROBLEM_GLOB --output "$OUTPUT"
