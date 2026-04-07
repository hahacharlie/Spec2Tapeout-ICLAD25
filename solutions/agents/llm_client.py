from __future__ import annotations
import asyncio
import re

from openai import AsyncOpenAI

MODEL_MAP = {
    "opus": "gpt-5.3-codex",
    "sonnet": "gpt-5.4",
}

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI()
    return _client


async def llm_call(
    prompt: str,
    system: str,
    model: str = "opus",
    max_tokens: int = 8192,
    max_retries: int = 3,
) -> str:
    """Call OpenAI API via Responses API."""
    client = get_client()
    model_id = MODEL_MAP.get(model, model)

    for attempt in range(max_retries):
        try:
            response = await client.responses.create(
                model=model_id,
                instructions=system,
                input=prompt,
            )
            return response.output_text
        except Exception as e:
            error_str = str(e)
            if "rate" in error_str.lower() or "429" in error_str:
                wait = 2 ** (attempt + 1)
                print(f"  Rate limited, waiting {wait}s...")
                await asyncio.sleep(wait)
            elif attempt == max_retries - 1:
                raise
            else:
                print(f"  API error (attempt {attempt + 1}): {error_str[:200]}")
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
