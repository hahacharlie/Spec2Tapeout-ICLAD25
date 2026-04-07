#!/usr/bin/env bash
# Single entry point for the Spec-to-Tapeout agent pipeline.
# Usage: ./run.sh [--problems <yaml_glob>] [--output <dir>]
#
# Examples:
#   ./run.sh                                         # run visible problems
#   ./run.sh --problems problems/hidden/*.yaml       # run hidden problems
#   ./run.sh --problems problems/visible/p1.yaml     # run a single problem

set -euo pipefail
cd "$(dirname "$0")/solutions"

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
echo "Problems: $PROBLEM_GLOB"
echo "Output:   $OUTPUT"
echo ""

exec python spec2tapeout_agent.py --problems $PROBLEM_GLOB --output "$OUTPUT"
