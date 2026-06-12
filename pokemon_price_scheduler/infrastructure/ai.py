"""MiniMax LLM client — infrastructure concern."""

from __future__ import annotations

import json
import os
import re
import hashlib
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..domain.models import ProductAnalysis

REPRICING_ADVICE_MAX_COMPLETION_TOKENS = 1800


def idr(value: int | None) -> str:
    if value is None:
        return "-"
    return f"Rp {value:,.0f}".replace(",", ".")


def pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:+.1f}%"


class MiniMaxClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ):
        env = load_project_env()
        self.api_key = api_key or env.get("MINIMAX_API_KEY", "")
        self.base_url = (base_url or env.get("MINIMAX_BASE_URL") or "https://api.minimax.io/v1").rstrip("/")
        self.model = model or env.get("MINIMAX_MODEL") or "MiniMax-M2.7-highspeed"
        self.timeout_seconds = timeout_seconds or float(env.get("MINIMAX_TIMEOUT_SECONDS", "30"))

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def chat(self, messages: list[dict[str, str]], max_completion_tokens: int = 280) -> str:
        if not self.api_key:
            raise RuntimeError("MINIMAX_API_KEY is not set.")

        body = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "max_completion_tokens": max_completion_tokens,
                "temperature": 0.2,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"MiniMax request failed with HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"MiniMax request failed: {exc.reason}") from exc

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"MiniMax response did not include message content: {payload}") from exc
        return strip_thinking(str(content)).strip()


def strip_thinking(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def load_project_env(start: Path | None = None) -> dict[str, str]:
    """Return os.environ plus values from the nearest .env, without overriding exports."""
    values = dict(os.environ)
    env_path = find_dotenv(start or Path.cwd())
    if not env_path:
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        key, value = parse_env_line(line)
        if key and key not in values:
            values[key] = value
    return values


def find_dotenv(start: Path) -> Path | None:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for directory in [current, *current.parents]:
        candidate = directory / ".env"
        if candidate.exists():
            return candidate
    return None


def parse_env_line(line: str) -> tuple[str, str]:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return "", ""
    key, value = stripped.split("=", 1)
    key = key.strip()
    value = value.strip()
    if value and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value


def attach_ai_summaries(
    analyses: list[ProductAnalysis],
    client: MiniMaxClient | None = None,
) -> tuple[list[ProductAnalysis], list[str]]:
    client = client or MiniMaxClient()
    if not client.is_configured:
        return analyses, ["AI summaries skipped: MINIMAX_API_KEY is not set."]

    enriched = []
    warnings = []
    for analysis in analyses:
        try:
            summary = summarize_analysis(analysis, client)
            enriched.append(replace(analysis, ai_summary=summary))
        except RuntimeError as exc:
            warnings.append(f"AI summary skipped for {analysis.product.title}: {exc}")
            enriched.append(analysis)
    return enriched, warnings


def summarize_analysis(analysis: ProductAnalysis, client: MiniMaxClient) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                "You help a Pokemon card seller review marketplace price checks. "
                "Use only the provided data. Be concise, practical, and cautious when evidence is thin."
            ),
        },
        {
            "role": "user",
            "content": build_summary_prompt(analysis),
        },
    ]
    return client.chat(messages)


def build_summary_prompt(analysis: ProductAnalysis) -> str:
    payload = {
        "product": analysis.product.title,
        "own_price": idr(analysis.product.own_price_idr),
        "language": analysis.product.language,
        "market_min": idr(analysis.market_min_idr),
        "market_median": idr(analysis.market_median_idr),
        "global_average": idr(analysis.global_average_idr),
        "delta_vs_global_average": pct(analysis.price_delta_percent),
        "alert_level": analysis.alert_level,
        "deterministic_recommendation": analysis.recommendation,
        "sources": compact_sources(analysis),
    }
    return (
        "Write a 2-sentence seller note for this product. "
        "Sentence 1 should summarize the price signal. "
        "Sentence 2 should give the next action or caveat. "
        "Do not invent prices, counts, market conditions, or card facts.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def compact_sources(analysis: ProductAnalysis) -> list[dict[str, Any]]:
    sources = []
    for result in analysis.source_results:
        observations = [
            {
                "title": obs.title,
                "price": idr(obs.price_idr),
                "used": obs.is_legit,
                "match_score": obs.relevance_score,
            }
            for obs in result.observations[:5]
        ]
        sources.append(
            {
                "name": result.source.name,
                "kind": result.source.kind,
                "warnings": result.warnings,
                "observations": observations,
            }
        )
    return sources


DEFAULT_REPRICING_ADVICE = {
    "headline": "AI advice is not available yet.",
    "recommended_action": "Review manually",
    "recommended_price_idr": None,
    "confidence": "low",
    "rationale": "",
    "risks": [],
    "next_steps": [],
}


def build_repricing_advice_payload(
    *,
    product,
    info: dict[str, Any],
    observations: list[dict[str, Any]],
    price_history: list[dict[str, Any]],
    trend_7d: float | None,
    trend_30d: float | None,
    suggested: dict[str, int | None],
    counterparts: list[dict[str, Any]],
) -> dict[str, Any]:
    latest = price_history[0] if price_history else {}
    market_avg = latest.get("market_avg_price", info.get("global_average_idr"))
    tokopedia_price = latest.get("tokopedia_price", product.own_price_idr)
    return {
        "product": {
            "title": product.title,
            "slug": product.slug,
            "language": product.language,
            "status": product.status,
            "search_term": product.search_terms[0] if product.search_terms else "",
            "own_price_idr": tokopedia_price,
        },
        "pricing": {
            "market_avg_price_idr": market_avg,
            "delta_percent": latest.get("delta_percent", info.get("price_delta_percent")),
            "alert_level": latest.get("alert_status", info.get("alert_level", "none")),
            "trend_7d_percent": trend_7d,
            "trend_30d_percent": trend_30d,
            "suggested_prices_idr": suggested,
        },
        "source_observations": [
            {
                "source": obs.get("source_name"),
                "kind": obs.get("source_kind"),
                "title": obs.get("title"),
                "price_idr": obs.get("price_idr"),
                "raw_price": obs.get("raw_price"),
                "is_legit": obs.get("is_legit"),
                "match_score": obs.get("relevance_score"),
            }
            for obs in observations[:12]
        ],
        "counterparts": [
            {
                "source": item.get("source_name"),
                "title": item.get("title"),
                "language": item.get("language"),
                "version": item.get("version"),
                "raw_price": item.get("raw_price"),
                "currency": item.get("currency"),
                "converted_price_idr": item.get("converted_price_idr"),
                "confidence": item.get("confidence"),
                "match_reason": item.get("match_reason"),
            }
            for item in counterparts[:10]
        ],
    }


def repricing_advice_input_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_repricing_advice_prompt(payload: dict[str, Any]) -> str:
    return (
        "Return strict JSON for a Pokemon card repricing copilot. "
        "Use only the provided data. Do not invent prices, exchange rates, or market facts. "
        "Fields: headline (string), recommended_action (string), recommended_price_idr (integer or null), "
        "confidence (low|medium|high), rationale (string), risks (array of strings), next_steps (array of strings). "
        "Be practical for a Tokopedia seller in Indonesia.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def generate_repricing_advice(payload: dict[str, Any], client: MiniMaxClient | None = None) -> dict[str, Any]:
    client = client or MiniMaxClient()
    if not client.is_configured:
        raise RuntimeError("MINIMAX_API_KEY is not set.")
    messages = [
        {
            "role": "system",
            "content": (
                "You are a cautious repricing assistant for a Pokemon TCG seller. "
                "Only reason over supplied evidence and return valid JSON."
            ),
        },
        {"role": "user", "content": build_repricing_advice_prompt(payload)},
    ]
    return parse_repricing_advice_response(
        client.chat(messages, max_completion_tokens=REPRICING_ADVICE_MAX_COMPLETION_TOKENS)
    )


def parse_repricing_advice_response(text: str) -> dict[str, Any]:
    cleaned = strip_thinking(text)
    match = re.search(r"\{.*\}", cleaned, flags=re.S)
    if not match:
        return _advice_from_prose(cleaned)
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        return _advice_from_prose(cleaned, warning=f"AI returned invalid JSON: {exc}")
    advice = dict(DEFAULT_REPRICING_ADVICE)
    advice.update({key: payload.get(key, advice[key]) for key in advice})
    if not isinstance(advice["risks"], list):
        advice["risks"] = [str(advice["risks"])]
    if not isinstance(advice["next_steps"], list):
        advice["next_steps"] = [str(advice["next_steps"])]
    if advice["confidence"] not in {"low", "medium", "high"}:
        advice["confidence"] = "low"
    if advice["recommended_price_idr"] is not None:
        try:
            advice["recommended_price_idr"] = int(advice["recommended_price_idr"])
        except (TypeError, ValueError):
            advice["recommended_price_idr"] = None
    return advice


def _advice_from_prose(text: str, warning: str = "AI returned prose instead of structured JSON.") -> dict[str, Any]:
    cleaned = " ".join((text or "").split())
    headline = cleaned[:140] if cleaned else "AI advice needs manual review."
    sentence_match = re.match(r"(.+?[.!?])(?:\s|$)", cleaned)
    if sentence_match:
        headline = sentence_match.group(1)[:140]
    advice = dict(DEFAULT_REPRICING_ADVICE)
    advice.update(
        {
            "headline": headline,
            "recommended_action": "Review manually",
            "confidence": "low",
            "rationale": cleaned,
            "risks": [warning],
            "next_steps": ["Review the pricing evidence and retry AI generation if needed."],
        }
    )
    return advice
