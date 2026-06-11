"""Shared Anthropic client for all AI modules.

Every AI feature degrades gracefully: when no ANTHROPIC_API_KEY is set
(or the SDK is unavailable), modules fall back to deterministic
rule-based logic so the platform remains fully demoable and testable.
"""

import json
import os

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None

MODEL = "claude-opus-4-8"

_client = None


def get_client():
    global _client
    if anthropic is None or not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def ai_available() -> bool:
    return get_client() is not None


def structured_request(system: str, user_content: str, schema: dict, max_tokens: int = 16000) -> dict:
    """Run a Messages API call constrained to a JSON schema and return the parsed dict.

    Caller must verify ai_available() first.
    """
    client = get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": user_content}],
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def text_request(system: str, user_content: str, max_tokens: int = 16000) -> str:
    """Run a plain Messages API call and return the response text."""
    client = get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": user_content}],
    )
    return next(b.text for b in response.content if b.type == "text")
