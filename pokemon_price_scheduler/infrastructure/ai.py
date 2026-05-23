"""MiniMax LLM client — infrastructure concern."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import replace
from typing import Any

from ..domain.models import ProductAnalysis


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
        self.api_key = api_key or os.environ.get("MINIMAX_API_KEY", "")
        self.base_url = (base_url or os.environ.get("MINIMAX_BASE_URL") or "https://api.minimax.io/v1").rstrip("/")
        self.model = model or os.environ.get("MINIMAX_MODEL") or "MiniMax-M2.7-highspeed"
        self.timeout_seconds = timeout_seconds or float(os.environ.get("MINIMAX_TIMEOUT_SECONDS", "30"))

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