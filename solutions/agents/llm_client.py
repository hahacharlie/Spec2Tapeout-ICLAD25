from __future__ import annotations
import asyncio
import json
import os
import re
from pathlib import Path

import anthropic

MODEL_MAP = {
    "opus": "claude-opus-4-20250514",
    "sonnet": "claude-sonnet-4-20250514",
}

_client: anthropic.AsyncAnthropic | None = None


def _load_max_plan_token() -> str | None:
    """Load OAuth access token from Claude Code credentials (Max/Pro plan)."""
    creds_path = Path.home() / ".claude" / ".credentials.json"
    if not creds_path.exists():
        return None
    try:
        with open(creds_path) as f:
            creds = json.load(f)
        return creds.get("claudeAiOauth", {}).get("accessToken")
    except (json.JSONDecodeError, KeyError):
        return None


def get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        # Priority: ANTHROPIC_AUTH_TOKEN env > Max plan credentials > ANTHROPIC_API_KEY env
        auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN") or _load_max_plan_token()
        if auth_token:
            _client = anthropic.AsyncAnthropic(auth_token=auth_token)
        else:
            # Falls back to ANTHROPIC_API_KEY env var automatically
            _client = anthropic.AsyncAnthropic()
    return _client


async def llm_call(
    prompt: str,
    system: str,
    model: str = "opus",
    max_tokens: int = 8192,
    max_retries: int = 3,
) -> str:
    client = get_client()
    model_id = MODEL_MAP[model]

    for attempt in range(max_retries):
        try:
            response = await client.messages.create(
                model=model_id,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except anthropic.RateLimitError:
            wait = 2 ** (attempt + 1)
            print(f"  Rate limited, waiting {wait}s...")
            await asyncio.sleep(wait)
        except anthropic.APIError as e:
            if attempt == max_retries - 1:
                raise
            print(f"  API error (attempt {attempt + 1}): {e}")
            await asyncio.sleep(2)

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
