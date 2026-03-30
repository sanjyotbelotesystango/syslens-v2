"""
llm_client.py — Unified LLM client.

STABILITY FIXES:
  1. extract_json: replaced greedy regex with JSONDecoder.raw_decode().
  2. call_llm: added retry wrapper (3 attempts, exponential backoff).
  3. call_vision_llm: same retry wrapper.
"""

from __future__ import annotations
import json
import re
import time
import logging
from typing import Any, List, Dict

from .config import settings

_logger = logging.getLogger("syslens.llm")

_RETRYABLE = ("429", "rate_limit", "timeout", "connection", "503", "502", "internal server", "overload")


def _openai_client():
    from openai import OpenAI
    return OpenAI(api_key=settings.OPENAI_API_KEY)

def _groq_client():
    from openai import OpenAI
    return OpenAI(api_key=settings.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")

def _anthropic_client():
    import anthropic
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

def _azure_client():
    from openai import AzureOpenAI
    return AzureOpenAI(
        api_key=settings.AZURE_OPENAI_API_KEY,
        api_version=settings.AZURE_OPENAI_API_VERSION,
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
    )


def _model_for(provider: str, fast: bool = False) -> str:
    if provider == "openai":    return settings.OPENAI_MODEL
    if provider == "groq":      return settings.GROQ_FAST_MODEL if fast else settings.GROQ_MODEL
    if provider == "anthropic": return settings.ANTHROPIC_MODEL
    if provider == "azure":     return settings.AZURE_OPEN_AI_MODEL
    raise ValueError(f"Unknown provider: '{provider}'. Use: openai, groq, anthropic, azure")


def _call_once(prov, system_prompt, messages, max_tokens, temperature, fast):
    if prov == "anthropic":
        client = _anthropic_client()
        resp = client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=messages,
        )
        return resp.content[0].text

    if prov in ("openai", "groq", "azure"):
        client = {"openai": _openai_client, "groq": _groq_client, "azure": _azure_client}[prov]()
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        resp = client.chat.completions.create(
            model=_model_for(prov, fast=fast),
            messages=full_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return resp.choices[0].message.content

    raise ValueError(f"Unsupported provider: '{prov}'")


def call_llm(
    system_prompt: str,
    messages: List[Dict[str, Any]],
    max_tokens: int = 3000,
    temperature: float = 0.1,
    provider: str | None = None,
    fast: bool = False,
) -> str:
    prov = provider or settings.LLM_PROVIDER
    last_exc: Exception | None = None

    for attempt in range(3):
        try:
            return _call_once(prov, system_prompt, messages, max_tokens, temperature, fast)
        except Exception as e:
            last_exc = e
            err_str = str(e).lower()
            is_retryable = any(k in err_str for k in _RETRYABLE)
            if is_retryable and attempt < 2:
                wait = (2 ** attempt) + 0.5
                _logger.warning(
                    f"LLM call failed (attempt {attempt + 1}/3), "
                    f"retrying in {wait:.1f}s: {type(e).__name__}: {e}"
                )
                time.sleep(wait)
            else:
                raise

    raise last_exc  # type: ignore[misc]


def call_vision_llm(
    system_prompt: str,
    user_text: str,
    image_b64: str,
    media_type: str = "image/png",
    max_tokens: int = 2000,
    provider: str | None = None,
) -> str:
    prov = provider or settings.LLM_PROVIDER
    last_exc: Exception | None = None

    for attempt in range(3):
        try:
            return _vision_once(prov, system_prompt, user_text, image_b64, media_type, max_tokens)
        except Exception as e:
            last_exc = e
            err_str = str(e).lower()
            is_retryable = any(k in err_str for k in _RETRYABLE)
            if is_retryable and attempt < 2:
                wait = (2 ** attempt) + 0.5
                _logger.warning(f"Vision LLM retry {attempt + 1}/3 in {wait:.1f}s: {e}")
                time.sleep(wait)
            else:
                raise

    raise last_exc  # type: ignore[misc]


def _vision_once(prov, system_prompt, user_text, image_b64, media_type, max_tokens):
    if prov == "anthropic":
        client = _anthropic_client()
        resp = client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                    {"type": "text", "text": user_text or "Extract all data from this image."},
                ],
            }],
        )
        return resp.content[0].text

    if prov in ("openai", "groq", "azure"):
        if prov == "openai":
            client, model = _openai_client(), settings.OPENAI_MODEL
        elif prov == "groq":
            client, model = _groq_client(), "llama-3.2-90b-vision-preview"
        else:
            client, model = _azure_client(), settings.AZURE_OPEN_AI_MODEL

        resp = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{image_b64}", "detail": "high"}},
                    {"type": "text", "text": user_text or "Extract all data from this image."},
                ]},
            ],
        )
        return resp.choices[0].message.content

    raise ValueError(f"Unsupported provider for vision: '{prov}'")


def call_router_llm(system_prompt: str, messages: List[Dict[str, Any]], max_tokens: int = 120) -> str:
    provider = settings.effective_router_provider()

    if provider == settings.LLM_PROVIDER:
        return call_llm(system_prompt, messages, max_tokens=max_tokens,
                        temperature=0.0, provider=provider, fast=True)
    try:
        return call_llm(system_prompt, messages, max_tokens=max_tokens,
                        temperature=0.0, provider=provider, fast=True)
    except Exception as e:
        _logger.debug(
            f"Router provider '{provider}' failed ({type(e).__name__}), "
            f"falling back to '{settings.LLM_PROVIDER}'"
        )
        return call_llm(system_prompt, messages, max_tokens=max_tokens,
                        temperature=0.0, provider=settings.LLM_PROVIDER, fast=True)


def extract_json(text: str) -> dict | list:
    """
    Robustly extract JSON using raw_decode — stops at first complete JSON value.
    Fixes greedy regex bug that matched from first to LAST } in the string.
    """
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fence = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass

    # FIX: use raw_decode — finds FIRST complete JSON object/array, ignores rest
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch in ('{', '['):
            try:
                obj, _ = decoder.raw_decode(text, i)
                return obj
            except json.JSONDecodeError:
                continue

    raise ValueError(f"No valid JSON found in LLM response. First 400 chars:\n{text[:400]}")