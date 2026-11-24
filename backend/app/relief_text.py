"""Plain-language text for p_relief. Templates work with no API key.

The Filipino strings need review by a native speaker.
"""

from __future__ import annotations

import json
import os
import re

from app.semantic_guard import forbidden_claim

# needs review by a native speaker
_FIL_READY = (
    "Sa ika-{week} na linggo, ang ulan sa ngayon ay {pct}% ng normal sa puntong ito ng panahon. "
    "Ang posibilidad na ang kabuuang ulan ng season ay mas mababa sa {line} mm na linya ng bayad ay {p}. "
    "Ang tinatayang kabuuang ulan ay mula {p10} hanggang {p90} mm, at ang gitnang tantiya ay {p50} mm. "
    "Payo lamang ang markang ito. Ang relief ay nakasalalay lamang sa huling naobserbahang kabuuang ulan."
)
# needs review by a native speaker
_FIL_WAITING = (
    "Hindi nagtataya ang RainCheck ng posibilidad ng relief bago may isang buong linggo ng ulan. "
    "Ang relief ay nakasalalay lamang sa huling naobserbahang kabuuang ulan."
)

_EN_READY = (
    "By week {week}, rainfall so far is {pct}% of normal for this point in the season. "
    "The chance the season total ends below the {line} mm payment line is {p}. "
    "The projected season total runs from {p10} to {p90} mm, with a middle estimate of {p50} mm. "
    "This score is advisory. Relief depends only on the final observed rainfall total."
)
_EN_WAITING = (
    "RainCheck does not estimate the chance of relief before a full week of rainfall is observed. "
    "Relief depends only on the final observed rainfall total."
)

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def explain(result: dict | None, lang: str) -> str:
    """Fill a template with numbers from result. No other facts are added.

    lang is "en" or "fil". Filipino wording needs review by a native speaker.
    """
    if lang not in {"en", "fil"}:
        raise ValueError("lang must be en or fil")
    if result is None:
        return _FIL_WAITING if lang == "fil" else _EN_WAITING
    fields = _fields(result)
    template = _FIL_READY if lang == "fil" else _EN_READY
    return template.format(**fields)


def explain_pair(result: dict | None) -> dict:
    """Template text, or an LLM rephrase when LLM_API_KEY is set and the numbers check out."""
    english = explain(result, "en")
    filipino = explain(result, "fil")
    source = "template"
    if result is not None and os.getenv("LLM_API_KEY"):
        rephrased = _rephrase(english, result)
        if rephrased is not None and _numbers_allowed(rephrased, result) and _semantics_allowed(rephrased):
            english = rephrased
            source = "llm"
    return {"en": english, "fil": filipino, "source": source}


def _fields(result: dict) -> dict:
    band = result["projected_total_mm"]
    return {
        "week": int(result["week"]),
        "pct": f"{float(result['rain_pct_of_normal']):.1f}",
        "p": f"{float(result['p_relief']):.4f}",
        "p10": f"{float(band['p10']):.1f}",
        "p50": f"{float(band['p50']):.1f}",
        "p90": f"{float(band['p90']):.1f}",
        "line": f"{float(result['payment_line_mm']):.1f}",
    }


def allowed_numbers(result: dict) -> set[str]:
    """The only numeric tokens explain() is allowed to print."""
    return {str(value) for value in _fields(result).values()}


def _semantics_allowed(text: str) -> bool:
    """A rephrase that invents a mechanism is dropped, even when every number is allowed."""
    return forbidden_claim(text) is None


def _numbers_allowed(text: str, result: dict) -> bool:
    allowed = allowed_numbers(result)
    for token in _NUMBER.findall(text.replace(",", "")):
        if token not in allowed:
            return False
    return True


# URL, default model, and request shape. The key always comes from LLM_API_KEY.
_PROVIDERS = {
    "openai": ("https://api.openai.com/v1/chat/completions", "gpt-4o-mini", "openai"),
    "groq": ("https://api.groq.com/openai/v1/chat/completions", "llama-3.1-8b-instant", "openai"),
    "openrouter": ("https://openrouter.ai/api/v1/chat/completions", "openai/gpt-4o-mini", "openai"),
    "anthropic": ("https://api.anthropic.com/v1/messages", "claude-3-5-haiku-latest", "anthropic"),
}

_REPHRASE_INSTRUCTION = (
    "Rephrase the user's text in English. Do not add facts, numbers, "
    "places, dates, or advice. Keep every number exactly as written. "
    "If you cannot, return the original text."
)


def _provider_settings() -> tuple[str, str, str] | None:
    """LLM_PROVIDER picks the endpoint. LLM_MODEL and LLM_API_URL override the defaults."""
    name = os.getenv("LLM_PROVIDER", "openai").strip().lower() or "openai"
    preset = _PROVIDERS.get(name)
    if preset is None:
        url = os.getenv("LLM_API_URL")
        model = os.getenv("LLM_MODEL")
        if not url or not model:
            return None
        return url, model, "openai"
    url, model, style = preset
    return os.getenv("LLM_API_URL", url), os.getenv("LLM_MODEL", model), style


def _rephrase(template_text: str, result: dict) -> str | None:
    """Ask the configured provider to rephrase. Personal data is not sent.

    The instruction forbids new facts, numbers, and advice. Any number in the
    reply that was not in the structured input is rejected by the caller.
    """
    settings = _provider_settings()
    if settings is None:
        return None
    url, model, style = settings
    key = os.environ["LLM_API_KEY"]
    numbers = json.dumps({"numbers": _fields(result), "text": template_text}, ensure_ascii=True)
    try:
        if style == "anthropic":
            payload = {
                "model": model,
                "max_tokens": 400,
                "temperature": 0,
                "system": _REPHRASE_INSTRUCTION,
                "messages": [{"role": "user", "content": numbers}],
            }
            headers = {
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
        else:
            payload = {
                "model": model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": _REPHRASE_INSTRUCTION},
                    {"role": "user", "content": numbers},
                ],
            }
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        body = _post_json(url, payload, headers)
        return _reply_text(body, style)
    except Exception:
        return None


def _post_json(url: str, payload: dict, headers: dict) -> dict:
    import urllib.request

    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _reply_text(body: dict, style: str) -> str:
    if style == "anthropic":
        return str(body["content"][0]["text"]).strip()
    return str(body["choices"][0]["message"]["content"]).strip()
