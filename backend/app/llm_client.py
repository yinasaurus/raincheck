"""Server-side LLM calls. The key stays in the process environment.

Gemini is the default. LLM_PROVIDER and LLM_MODEL swap the implementation.
This module cannot create a loan, apply relief, or change a payment.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Protocol

# Stable id from the Gemini model list (fetched 24 Nov 2026).
# Flash-Lite is the high-volume model; free-tier input and output are free of charge.
# Override with LLM_MODEL. Do not hard-code a key.
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MAX_OUTPUT_TOKENS = 256
TIMEOUT_SECONDS = 6


class LlmError(Exception):
    """A failed model call. The message is a short kind, never a key or a body."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        super().__init__(kind)


def error_kind(code: int, body: str) -> str:
    """Classify an HTTP failure. The body is not kept. Quota and billing do not retry."""
    if code in {402, 429} or "RESOURCE_EXHAUSTED" in (body or ""):
        return "quota"
    if 500 <= code <= 599:
        return "server"
    return "http"


def _read_error(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


class Provider(Protocol):
    def generate(self, system: str, user: str, schema: dict | None) -> str: ...


def scrub(text: str, secret: str) -> str:
    if not secret or not text:
        return text
    return text.replace(secret, "")


def gemini_key() -> str:
    return os.environ.get("GEMINI_API_KEY", "").strip()


def provider_name() -> str:
    return os.environ.get("LLM_PROVIDER", "gemini").strip().lower() or "gemini"


def model_name() -> str:
    chosen = os.environ.get("LLM_MODEL", "").strip()
    return chosen or DEFAULT_GEMINI_MODEL


class GeminiProvider:
    def __init__(self, key: str, model: str) -> None:
        self.key = key
        self.model = model

    def generate(self, system: str, user: str, schema: dict | None) -> str:
        config: dict = {
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
            "temperature": 0,
        }
        if schema is not None:
            config["responseMimeType"] = "application/json"
            config["responseJsonSchema"] = schema
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": config,
        }
        url = GEMINI_URL.format(model=self.model)
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise LlmError(error_kind(exc.code, _read_error(exc))) from None
        except TimeoutError as exc:
            raise LlmError("timeout") from exc
        except urllib.error.URLError as exc:
            kind = "timeout" if isinstance(getattr(exc, "reason", None), TimeoutError) else "http"
            raise LlmError(kind) from None
        return _gemini_text(raw)


class OpenAICompatibleProvider:
    """Swap-in for an OpenAI-style chat endpoint. Unused unless LLM_PROVIDER selects it."""

    def __init__(self, key: str, model: str, url: str) -> None:
        self.key = key
        self.model = model
        self.url = url

    def generate(self, system: str, user: str, schema: dict | None) -> str:
        payload: dict = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if schema is not None:
            payload["response_format"] = {"type": "json_object"}
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise LlmError(error_kind(exc.code, _read_error(exc))) from None
        except TimeoutError as exc:
            raise LlmError("timeout") from exc
        except urllib.error.URLError as exc:
            kind = "timeout" if isinstance(getattr(exc, "reason", None), TimeoutError) else "http"
            raise LlmError(kind) from None
        try:
            data = json.loads(raw)
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            raise LlmError("bad-response") from None


def _gemini_text(raw: str) -> str:
    try:
        data = json.loads(raw)
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        raise LlmError("bad-response") from None
    chunks = []
    for part in parts:
        if not isinstance(part, dict) or part.get("thought"):
            continue
        text = part.get("text")
        if isinstance(text, str):
            chunks.append(text)
    if not chunks:
        raise LlmError("bad-response")
    return "".join(chunks)


def build_provider() -> Provider | None:
    name = provider_name()
    if name == "gemini":
        key = gemini_key()
        if not key:
            return None
        return GeminiProvider(key, model_name())
    if name in {"openai", "groq", "openrouter", "anthropic"}:
        key = os.environ.get("LLM_API_KEY", "").strip()
        url = os.environ.get("LLM_API_URL", "").strip()
        if not key or not url:
            return None
        return OpenAICompatibleProvider(key, model_name(), url)
    return None
