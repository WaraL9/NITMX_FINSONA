"""LLM gateway (E7-01).

One entry point, `complete_json`, used by every AI feature. Guarantees:
  * JSON output validated against a schema (structured outputs), never free text;
  * responses cached by a hash of the full request, so a demo replays identically and
    works offline once warmed;
  * bounded latency (timeout + SDK retries) and typed error handling;
  * it can always say "unavailable" — callers MUST have a deterministic fallback.

The LLM never produces numbers the engine uses. It labels and it writes prose with
placeholders; the engine's numbers are substituted afterwards (see narrative.py).

Providers: `anthropic` (Claude via the official SDK) is the live adapter. Add another
provider by implementing `_Adapter`; nothing else in the app changes.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.config import settings
from app.models import LlmCache

log = logging.getLogger("finsona.llm")


class LLMUnavailable(Exception):
    """No live provider configured, provider error, refusal, or invalid output."""


@dataclass
class LLMResult:
    data: dict[str, Any]
    source: str  # "live" | "cache"
    provider: str
    model: str


class _Adapter(Protocol):
    provider: str
    model: str

    def complete_json(self, system: str, user: str, schema: dict[str, Any], max_tokens: int) -> dict[str, Any]: ...


class AnthropicAdapter:
    """Claude via the Anthropic SDK: structured JSON output + server-side refusal fallback."""

    provider = "anthropic"

    def __init__(self, model: str, timeout_s: float):
        import anthropic  # imported lazily so the app runs without the SDK configured

        self._anthropic = anthropic
        self.model = model
        # Credentials resolve from the environment (ANTHROPIC_API_KEY, or an `ant auth login` profile).
        self._client = anthropic.Anthropic(timeout=timeout_s, max_retries=2)

    def complete_json(self, system: str, user: str, schema: dict[str, Any], max_tokens: int) -> dict[str, Any]:
        a = self._anthropic
        try:
            response = self._client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                # Short, well-specified tasks: keep thinking adaptive but cheap.
                thinking={"type": "adaptive"},
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
                # If a safety classifier declines, retry server-side on Anthropic's recommended model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except a.AuthenticationError as e:
            raise LLMUnavailable("LLM credentials rejected") from e
        except a.RateLimitError as e:
            raise LLMUnavailable("LLM rate limited") from e
        except a.BadRequestError as e:
            raise LLMUnavailable(f"LLM rejected the request: {e.message}") from e
        except a.APIStatusError as e:
            raise LLMUnavailable(f"LLM error {e.status_code}") from e
        except a.APIConnectionError as e:  # includes timeouts
            raise LLMUnavailable("LLM unreachable or timed out") from e

        if response.stop_reason == "refusal":
            raise LLMUnavailable("LLM declined the request")
        if response.stop_reason == "max_tokens":
            raise LLMUnavailable("LLM output truncated")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise LLMUnavailable("LLM returned no text block")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMUnavailable("LLM returned invalid JSON") from e


_adapter: _Adapter | None = None
_adapter_error: str | None = None


def _get_adapter() -> _Adapter | None:
    global _adapter, _adapter_error
    if _injected:
        return _adapter
    if not settings.use_live_llm:
        return None
    if _adapter is None and _adapter_error is None:
        try:
            if settings.llm_provider != "anthropic":
                raise ValueError(f"unknown LLM provider {settings.llm_provider!r}")
            _adapter = AnthropicAdapter(settings.llm_model, settings.llm_timeout_s)
        except Exception as e:  # missing SDK/credentials: stay in fallback mode
            _adapter_error = str(e)
            log.warning("LLM disabled: %s", e)
    return _adapter


_injected = False


def set_adapter(adapter: _Adapter | None) -> None:
    """Inject an adapter (tests, or a different provider); None restores config-driven behaviour."""
    global _adapter, _adapter_error, _injected
    _adapter, _adapter_error, _injected = adapter, None, adapter is not None


def status() -> dict[str, Any]:
    a = _get_adapter()
    return {
        "live": a is not None,
        "provider": a.provider if a else settings.llm_provider,
        "model": a.model if a else settings.llm_model,
        "note": None if a else (_adapter_error or "live LLM disabled (FINSONA_USE_LIVE_LLM=false) — cached/template mode"),
    }


def _key(purpose: str, provider: str, model: str, system: str, user: str, schema: dict[str, Any]) -> str:
    blob = json.dumps({"p": purpose, "v": provider, "m": model, "s": system, "u": user, "j": schema},
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def complete_json(db: Session, purpose: str, system: str, user: str, schema: dict[str, Any],
                  max_tokens: int = 2048) -> LLMResult:
    """Cached structured completion. Raises LLMUnavailable when nothing can answer."""
    provider, model = settings.llm_provider, settings.llm_model
    adapter = _get_adapter()
    if adapter is not None:
        provider, model = adapter.provider, adapter.model
    key = _key(purpose, provider, model, system, user, schema)
    cached = db.get(LlmCache, key)
    if cached is not None:
        return LLMResult(cached.response, "cache", provider, model)
    if adapter is None:
        raise LLMUnavailable(status()["note"])
    data = adapter.complete_json(system, user, schema, max_tokens)
    db.merge(LlmCache(key=key, provider=provider, model=model, purpose=purpose, response=data))
    db.flush()
    return LLMResult(data, "live", provider, model)
