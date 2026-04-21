#!/usr/bin/env bash
# Single entry point for the Spec-to-Tapeout agentic workflow.
# Usage examples:
#   ./run.sh
#   ./run.sh --problems problems/visible/p8.yaml --output solutions/out --report-json solutions/out/report.json
#   ./run.sh --suite hidden --problems problems/hidden/*.yaml --output solutions/hidden/

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
CODEX_BIN="${CODEX_CLI_PATH:-codex}"
CODEX_MODEL_SELECTED="${CODEX_MODEL:-gpt-5.4}"
DEFAULT_PROBLEM_PATTERN="problems/visible/*.yaml"
DEFAULT_OUTPUT_TEMPLATE="solutions/<suite>"
DEFAULT_WORKSPACE_TEMPLATE="solutions/workspace/<suite>"

show_help() {
    cat <<EOF
Usage: ./run.sh [OPTIONS]

Run the Spec-to-Tapeout pipeline using Codex CLI as the LLM backend.

Options:
  -p, --problems <file|glob> [more files/globs...]
      Problem YAML file(s) or glob pattern(s).
      Paths are interpreted relative to the repository root unless absolute.
      Default: ${DEFAULT_PROBLEM_PATTERN}

  -o, --output <dir>
      Output directory for generated solutions.
      Default: ${DEFAULT_OUTPUT_TEMPLATE}

  -r, --report-json <file>
      Optional JSON run report path.

  -w, --workspace <dir>
      Workspace directory for intermediate files.
      Default: ${DEFAULT_WORKSPACE_TEMPLATE}

      --flow-root <dir>
      Optional path to OpenROAD-flow-scripts.
      If omitted, the Python agent uses its built-in default.

      --suite <visible|hidden>
      Problem suite for this run.
      If omitted, inferred from the problem paths.

  -h, --help
      Show this help message and exit.

Examples:
  ./run.sh
  ./run.sh --problems problems/visible/p8.yaml --output solutions/out
  ./run.sh --suite hidden --problems problems/hidden/*.yaml --output solutions/hidden/
  ./run.sh --problems problems/visible/p8.yaml --output solutions/out \
    --report-json solutions/out/report.json

Environment:
  CODEX_CLI_PATH   Path to Codex CLI executable (default: codex)
  CODEX_MODEL      Codex model to use (default: gpt-5.4)
EOF
}

die() {
    echo "Error: $*" >&2
    exit 1
}

resolve_path() {
    local path="$1"
    if [[ "$path" = /* ]]; then
        printf '%s\n' "$path"
    else
        printf '%s\n' "$ROOT/$path"
    fi
}

is_glob_pattern() {
    case "$1" in
        *'*'*|*'?'*|*'['*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

expand_problem_inputs() {
    local -n out_ref=$1
    shift

    local item resolved
    local -a matches=()

    for item in "$@"; do
        resolved="$(resolve_path "$item")"
        if is_glob_pattern "$item"; then
            mapfile -t matches < <(compgen -G "$resolved" || true)
            if [[ ${#matches[@]} -eq 0 ]]; then
                die "No problem files matched pattern: $item"
            fi
            out_ref+=("${matches[@]}")
        else
            [[ -e "$resolved" ]] || die "Problem file not found: $item"
            out_ref+=("$resolved")
        fi
    done
}

PROBLEM_INPUTS=()
OUTPUT_DIR=""
WORKSPACE_DIR=""
REPORT_JSON=""
FLOW_ROOT=""
SUITE=""
PASSTHROUGH_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            show_help
            exit 0
            ;;
        -p|--problems)
            shift
            [[ $# -gt 0 ]] || die "--problems requires at least one file or glob"
            while [[ $# -gt 0 ]]; do
                case "$1" in
                    -*)
                        break
                        ;;
                    *)
                        PROBLEM_INPUTS+=("$1")
                        shift
                        ;;
                esac
            done
            ;;
        --problems=*)
            PROBLEM_INPUTS+=("${1#*=}")
            shift
            ;;
        -o|--output)
            [[ $# -ge 2 ]] || die "--output requires a directory"
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --output=*)
            OUTPUT_DIR="${1#*=}"
            shift
            ;;
        -r|--report-json)
            [[ $# -ge 2 ]] || die "--report-json requires a file path"
            REPORT_JSON="$2"
            shift 2
            ;;
        --report-json=*)
            REPORT_JSON="${1#*=}"
            shift
            ;;
        -w|--workspace)
            [[ $# -ge 2 ]] || die "--workspace requires a directory"
            WORKSPACE_DIR="$2"
            shift 2
            ;;
        --workspace=*)
            WORKSPACE_DIR="${1#*=}"
            shift
            ;;
        --flow-root)
            [[ $# -ge 2 ]] || die "--flow-root requires a directory"
            FLOW_ROOT="$2"
            shift 2
            ;;
        --flow-root=*)
            FLOW_ROOT="${1#*=}"
            shift
            ;;
        --suite)
            [[ $# -ge 2 ]] || die "--suite requires visible or hidden"
            SUITE="$2"
            shift 2
            ;;
        --suite=*)
            SUITE="${1#*=}"
            shift
            ;;
        --)
            shift
            PASSTHROUGH_ARGS=("$@")
            break
            ;;
        -*)
            die "Unknown option: $1"
            ;;
        *)
            die "Unexpected positional argument: $1"
            ;;
    esac
done

if [[ ${#PROBLEM_INPUTS[@]} -eq 0 ]]; then
    PROBLEM_INPUTS=("$DEFAULT_PROBLEM_PATTERN")
fi

PROBLEM_FILES=()
expand_problem_inputs PROBLEM_FILES "${PROBLEM_INPUTS[@]}"

if [[ -n "$OUTPUT_DIR" ]]; then
    OUTPUT_DIR="$(resolve_path "$OUTPUT_DIR")"
fi
if [[ -n "$WORKSPACE_DIR" ]]; then
    WORKSPACE_DIR="$(resolve_path "$WORKSPACE_DIR")"
fi
if [[ -n "$REPORT_JSON" ]]; then
    REPORT_JSON="$(resolve_path "$REPORT_JSON")"
fi
if [[ -n "$FLOW_ROOT" ]]; then
    FLOW_ROOT="$(resolve_path "$FLOW_ROOT")"
fi

# Activate virtual environment if not already active.
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    if [[ -f "$ROOT/.venv/bin/activate" ]]; then
        # shellcheck disable=SC1091
        source "$ROOT/.venv/bin/activate"
    else
        die "Virtual environment not found. Set it up first: python3.10 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    fi
fi

# Preflight: Codex CLI must exist and be authenticated.
if ! command -v "$CODEX_BIN" >/dev/null 2>&1 && [[ ! -x "$CODEX_BIN" ]]; then
    die "Codex CLI not found. Install it with 'npm install -g @openai/codex' or set CODEX_CLI_PATH."
fi

set +e
CODEX_STATUS="$($CODEX_BIN login status 2>&1)"
CODEX_STATUS_RC=$?
set -e
if [[ "$CODEX_STATUS_RC" -ne 0 ]]; then
    echo "Error: Codex CLI is not authenticated." >&2
    echo "Run:" >&2
    echo "  $CODEX_BIN login" >&2
    echo "Details:" >&2
    echo "$CODEX_STATUS" >&2
    exit 1
fi

echo "=== Spec-to-Tapeout Agent Pipeline ==="
echo "Python:   $(python --version 2>&1)"
echo "Codex:    $(printf '%s' "$CODEX_STATUS" | head -n 1)"
echo "Model:    $CODEX_MODEL_SELECTED"
if [[ -n "$SUITE" ]]; then
    echo "Suite:    $SUITE"
else
    echo "Suite:    auto (inferred from problem paths)"
fi
echo "Problems: ${#PROBLEM_FILES[@]} file(s)"
for problem in "${PROBLEM_FILES[@]}"; do
    if [[ "$problem" == "$ROOT/"* ]]; then
        echo "  - ${problem#$ROOT/}"
    else
        echo "  - $problem"
    fi
done
if [[ -n "$OUTPUT_DIR" ]]; then
    echo "Output:   ${OUTPUT_DIR#$ROOT/}"
else
    echo "Output:   auto (solutions/<suite>)"
fi
if [[ -n "$WORKSPACE_DIR" ]]; then
    echo "Workspace: ${WORKSPACE_DIR#$ROOT/}"
else
    echo "Workspace: auto (solutions/workspace/<suite>)"
fi
if [[ -n "$REPORT_JSON" ]]; then
    echo "Report:   ${REPORT_JSON#$ROOT/}"
fi
echo ""

AGENT_ARGS=(
    "$ROOT/solutions/spec2tapeout_agent.py"
    --problems
    "${PROBLEM_FILES[@]}"
)

if [[ -n "$SUITE" ]]; then
    AGENT_ARGS+=(--suite "$SUITE")
fi
if [[ -n "$OUTPUT_DIR" ]]; then
    AGENT_ARGS+=(--output "$OUTPUT_DIR")
fi
if [[ -n "$WORKSPACE_DIR" ]]; then
    AGENT_ARGS+=(--workspace "$WORKSPACE_DIR")
fi

if [[ -n "$FLOW_ROOT" ]]; then
    AGENT_ARGS+=(--flow-root "$FLOW_ROOT")
fi
if [[ -n "$REPORT_JSON" ]]; then
    AGENT_ARGS+=(--report-json "$REPORT_JSON")
fi
if [[ ${#PASSTHROUGH_ARGS[@]} -gt 0 ]]; then
    AGENT_ARGS+=("${PASSTHROUGH_ARGS[@]}")
fi

exec python "${AGENT_ARGS[@]}"
