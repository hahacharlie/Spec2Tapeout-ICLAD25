from __future__ import annotations
import json
import subprocess
from pathlib import Path

from .models import Spec, ScoredCandidate
from .llm_client import llm_call, extract_code_block
from .prompts import build_optimizer_prompt

SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent / "evaluation"


def score_candidate(
    candidate: ScoredCandidate,
    problem_number: int,
    flow_root: Path,
) -> float:
    if candidate.odb_path is None or candidate.sdc_path is None:
        return 0.0

    cmd = [
        "python3",
        str(SCRIPT_DIR / "evaluate_openroad.py"),
        "--odb", str(candidate.odb_path),
        "--sdc", str(candidate.sdc_path),
        "--flow_root", str(flow_root),
        "--problem", str(problem_number),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        output = result.stdout

        for line in output.split("\n"):
            if "Final Score:" in line:
                score = float(line.split(":")[1].strip().split("/")[0])
                candidate.score = score
                return score

        metrics_path = Path(f"p{problem_number}.json")
        if metrics_path.exists():
            with open(metrics_path) as f:
                candidate.metrics = json.load(f)
            metrics_path.unlink()

    except (subprocess.TimeoutExpired, Exception) as e:
        print(f"  Scoring failed: {e}")

    return 0.0


def rank_candidates(candidates: list[ScoredCandidate]) -> list[ScoredCandidate]:
    return sorted(candidates, key=lambda c: c.score, reverse=True)


async def optimize_candidate(
    candidate: ScoredCandidate,
    spec: Spec,
) -> str:
    system, prompt = build_optimizer_prompt(
        rtl_source=candidate.rtl_source,
        metrics=candidate.metrics,
        score=candidate.score,
        spec=spec,
    )
    response = await llm_call(prompt, system, model="opus")
    return extract_code_block(response)
