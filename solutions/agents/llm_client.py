from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import re
import shlex
import shutil
import tempfile
from pathlib import Path

CODEX_MODEL = os.getenv("CODEX_MODEL", "gpt-5.4")
CODEX_CLI_PATH = os.getenv("CODEX_CLI_PATH", "codex")
CODEX_SANDBOX = os.getenv("CODEX_SANDBOX", "read-only")
CODEX_EXTRA_ARGS = shlex.split(os.getenv("CODEX_EXTRA_ARGS", ""))
PROJECT_ROOT = Path(__file__).resolve().parents[2]

MODEL_MAP = {
    "codex": CODEX_MODEL,
    "opus": CODEX_MODEL,
    "sonnet": CODEX_MODEL,
}

PURPOSE_MODEL_CHAINS = {
    "rtl_generation": [CODEX_MODEL],
    "rtl_fix": [CODEX_MODEL],
    "timing_optimization": [CODEX_MODEL],
    "score_optimization": [CODEX_MODEL],
    "generic": [CODEX_MODEL],
}

LLM_MAX_CONCURRENCY = max(1, int(os.getenv("LLM_MAX_CONCURRENCY", "1")))
LLM_MAX_RETRIES = max(3, int(os.getenv("LLM_MAX_RETRIES", "8")))
LLM_BACKOFF_CAP_SECONDS = max(8, int(os.getenv("LLM_BACKOFF_CAP_SECONDS", "90")))
LLM_ENABLE_CACHE = os.getenv("LLM_ENABLE_CACHE", "1") != "0"
LLM_CACHE_DIR = Path(
    os.getenv("LLM_CACHE_DIR", Path(__file__).resolve().parent.parent / ".llm_cache")
)

_llm_semaphore: asyncio.Semaphore | None = None


def get_llm_semaphore() -> asyncio.Semaphore:
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(LLM_MAX_CONCURRENCY)
    return _llm_semaphore


def resolve_model(model: str) -> str:
    return MODEL_MAP.get(model, model)


def model_chain_for_purpose(primary_model: str, purpose: str) -> list[str]:
    chain = [resolve_model(primary_model)]
    chain.extend(PURPOSE_MODEL_CHAINS.get(purpose, PURPOSE_MODEL_CHAINS["generic"]))

    deduped: list[str] = []
    seen = set()
    for model_id in chain:
        if model_id not in seen:
            seen.add(model_id)
            deduped.append(model_id)
    return deduped


def cache_key_for_request(
    prompt: str,
    system: str,
    models: list[str],
    purpose: str,
) -> str:
    payload = {
        "prompt": prompt,
        "system": system,
        "models": models,
        "purpose": purpose,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def cache_path_for_key(cache_key: str) -> Path:
    return LLM_CACHE_DIR / f"{cache_key}.json"


def load_cached_response(cache_key: str) -> str | None:
    if not LLM_ENABLE_CACHE:
        return None
    path = cache_path_for_key(cache_key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return str(data["response"])
    except Exception:
        return None


def save_cached_response(
    cache_key: str, model: str, response: str, purpose: str
) -> None:
    if not LLM_ENABLE_CACHE:
        return
    LLM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = cache_path_for_key(cache_key)
    payload = {
        "backend": "codex_cli",
        "model": model,
        "purpose": purpose,
        "response": response,
    }
    path.write_text(json.dumps(payload, indent=2))


def ensure_codex_available() -> None:
    if shutil.which(CODEX_CLI_PATH) is None and not Path(CODEX_CLI_PATH).exists():
        raise RuntimeError(
            "Codex CLI not found. Install @openai/codex and make sure `codex` is on PATH."
        )


def build_codex_prompt(system: str, prompt: str) -> str:
    return (
        "You are being called as the LLM backend for an automated ASIC design pipeline.\n"
        "Follow the SYSTEM instructions as highest priority and then answer the USER request.\n"
        "Return only the requested content.\n\n"
        f"<SYSTEM>\n{system.strip()}\n</SYSTEM>\n\n"
        f"<USER>\n{prompt.strip()}\n</USER>\n"
    )


async def call_codex_cli(prompt: str, system: str, model_id: str) -> str:
    ensure_codex_available()
    combined_prompt = build_codex_prompt(system, prompt)

    with tempfile.TemporaryDirectory(prefix="spec2tapeout_codex_") as tmpdir:
        output_path = Path(tmpdir) / "last_message.txt"
        cmd = [
            CODEX_CLI_PATH,
            "exec",
            "--model",
            model_id,
            "--sandbox",
            CODEX_SANDBOX,
            "--cd",
            str(PROJECT_ROOT),
            "--skip-git-repo-check",
            "--color",
            "never",
            "--output-last-message",
            str(output_path),
            *CODEX_EXTRA_ARGS,
            "-",
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(combined_prompt.encode("utf-8"))

        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")
        response_text = output_path.read_text() if output_path.exists() else stdout_text

        if proc.returncode != 0:
            detail = (stderr_text or stdout_text).strip()
            if not detail:
                detail = f"Codex CLI exited with status {proc.returncode}"
            raise RuntimeError(
                f"Codex CLI call failed for model {model_id}: {detail[:500]}. "
                "If this is an auth issue, run `codex login`."
            )

        if not response_text.strip():
            detail = (stderr_text or stdout_text).strip()
            raise RuntimeError(
                f"Codex CLI returned an empty response for model {model_id}: {detail[:500]}"
            )

        return response_text


async def llm_call(
    prompt: str,
    system: str,
    model: str = "codex",
    max_tokens: int = 8192,
    max_retries: int = LLM_MAX_RETRIES,
    purpose: str = "generic",
    use_cache: bool = True,
) -> str:
    """Call Codex CLI with caching and retry/backoff."""
    del max_tokens  # Codex CLI controls token budgeting internally.

    semaphore = get_llm_semaphore()
    model_chain = model_chain_for_purpose(model, purpose)
    cache_key = cache_key_for_request(prompt, system, model_chain, purpose)

    if use_cache:
        cached = load_cached_response(cache_key)
        if cached is not None:
            print(f"  LLM cache hit ({purpose})")
            return cached

    async with semaphore:
        last_error: Exception | None = None
        for model_index, model_id in enumerate(model_chain):
            if model_index > 0:
                print(f"  Retrying with fallback model: {model_id}")
            for attempt in range(max_retries):
                try:
                    output_text = await call_codex_cli(prompt, system, model_id)
                    if use_cache:
                        save_cached_response(cache_key, model_id, output_text, purpose)
                    return output_text
                except Exception as e:
                    last_error = e
                    error_str = str(e)
                    if "rate" in error_str.lower() or "429" in error_str:
                        base_wait = min(LLM_BACKOFF_CAP_SECONDS, 2 ** (attempt + 1))
                        wait = min(
                            LLM_BACKOFF_CAP_SECONDS,
                            base_wait + random.uniform(0.0, min(3.0, base_wait / 2)),
                        )
                        print(f"  Rate limited on {model_id}, waiting {wait:.1f}s...")
                        await asyncio.sleep(wait)
                    elif attempt == max_retries - 1:
                        break
                    else:
                        print(
                            f"  LLM error on {model_id} (attempt {attempt + 1}): {error_str[:200]}"
                        )
                        await asyncio.sleep(2)

    if last_error is not None:
        raise RuntimeError(
            f"LLM call failed after model fallbacks: {last_error}"
        ) from last_error
    raise RuntimeError("LLM call failed after max retries")


def extract_code_block(response: str, lang: str = "systemverilog") -> str:
    patterns = [
        rf"```{lang}\s*\n(.*?)```",
        rf"```{lang[:2]}.*?\s*\n(.*?)```",
        r"```\s*\n(.*?)```",
    ]
    for pattern in patterns:
        match = re.search(pattern, response, re.DOTALL)
        if match:
            return match.group(1).strip()

    if "module " in response:
        lines = response.split("\n")
        start = next((i for i, l in enumerate(lines) if "module " in l), 0)
        end = len(lines)
        for i in range(start, len(lines)):
            if "endmodule" in lines[i]:
                end = i + 1
                break
        return "\n".join(lines[start:end]).strip()

    return response.strip()
