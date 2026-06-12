import unittest
import tempfile
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from pokemon_price_scheduler.ai import (
    MiniMaxClient,
    attach_ai_summaries,
    build_repricing_advice_payload,
    build_summary_prompt,
    generate_repricing_advice,
    load_project_env,
    parse_env_line,
    parse_repricing_advice_response,
    repricing_advice_input_hash,
    strip_thinking,
)
from pokemon_price_scheduler.models import PriceObservation, Product, Source, SourceResult
from pokemon_price_scheduler.analyze import analyze_product


class FakeClient:
    is_configured = True

    def __init__(self):
        self.messages = []
        self.max_completion_tokens = None

    def chat(self, messages, max_completion_tokens=280):
        self.messages = messages
        self.max_completion_tokens = max_completion_tokens
        return "Market references support the current price. Keep monitoring thin sources before repricing."


class AiTests(unittest.TestCase):
    def test_strip_thinking_removes_minimax_reasoning_tag(self):
        self.assertEqual(strip_thinking("<think>hidden</think>\n\nVisible note"), "Visible note")

    def test_parse_env_line_supports_quotes_and_ignores_comments(self):
        self.assertEqual(parse_env_line('MINIMAX_API_KEY="abc123"'), ("MINIMAX_API_KEY", "abc123"))
        self.assertEqual(parse_env_line("# comment"), ("", ""))

    def test_minimax_client_loads_project_dotenv_without_overriding_exported_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text(
                "MINIMAX_API_KEY=from-dotenv\nMINIMAX_MODEL=dotenv-model\n",
                encoding="utf-8",
            )
            child = root / "nested"
            child.mkdir()

            old_cwd = Path.cwd()
            with patch.dict("os.environ", {"MINIMAX_MODEL": "exported-model"}, clear=True):
                try:
                    os.chdir(child)
                    env = load_project_env(child)
                    client = MiniMaxClient()
                finally:
                    os.chdir(old_cwd)

            self.assertEqual(env["MINIMAX_API_KEY"], "from-dotenv")
            self.assertEqual(env["MINIMAX_MODEL"], "exported-model")
            self.assertEqual(client.api_key, "from-dotenv")
            self.assertEqual(client.model, "exported-model")

    def test_attach_ai_summaries_adds_note_without_changing_analysis_numbers(self):
        source = Source(name="tokopedia", kind="tokopedia_find", url="https://example.com")
        product = Product(title="Pokemon Japanese PSA 10", own_price_idr=750000)
        analysis = analyze_product(
            product,
            [
                SourceResult(
                    source=source,
                    observations=[
                        PriceObservation("tokopedia", "tokopedia_find", source.url, 900000, title="Pokemon Japanese PSA 10"),
                    ],
                )
            ],
            datetime(2026, 5, 20, tzinfo=timezone.utc),
            {},
        )

        enriched, warnings = attach_ai_summaries([analysis], FakeClient())

        self.assertEqual(warnings, [])
        self.assertEqual(enriched[0].market_median_idr, analysis.market_median_idr)
        self.assertIn("Market references", enriched[0].ai_summary)

    def test_build_summary_prompt_contains_only_compact_observations(self):
        source = Source(name="tokopedia", kind="tokopedia_find", url="https://example.com")
        product = Product(title="Pokemon Japanese PSA 10", own_price_idr=750000)
        observations = [
            PriceObservation("tokopedia", "tokopedia_find", source.url, 900000 + index, title=f"Listing {index}")
            for index in range(8)
        ]
        analysis = analyze_product(
            product,
            [SourceResult(source=source, observations=observations)],
            datetime(2026, 5, 20, tzinfo=timezone.utc),
            {},
        )

        prompt = build_summary_prompt(analysis)

        self.assertIn("Listing 0", prompt)
        self.assertIn("Listing 4", prompt)
        self.assertNotIn("Listing 5", prompt)

    def test_parse_repricing_advice_response_requires_json_and_normalizes_fields(self):
        advice = parse_repricing_advice_response(
            """
            {
              "headline": "Lower the price slightly.",
              "recommended_action": "Lower price",
              "recommended_price_idr": "900000",
              "confidence": "medium",
              "rationale": "Market average is below own price.",
              "risks": "Thin source coverage",
              "next_steps": ["Check Tokopedia before changing"]
            }
            """
        )

        self.assertEqual(advice["recommended_price_idr"], 900000)
        self.assertEqual(advice["confidence"], "medium")
        self.assertEqual(advice["risks"], ["Thin source coverage"])

    def test_parse_repricing_advice_response_wraps_prose_as_low_confidence_advice(self):
        advice = parse_repricing_advice_response("The card looks slightly above market. Check sources before repricing.")

        self.assertEqual(advice["recommended_action"], "Review manually")
        self.assertEqual(advice["confidence"], "low")
        self.assertIn("slightly above market", advice["rationale"])
        self.assertIn("structured JSON", advice["risks"][0])

    def test_generate_repricing_advice_gives_reasoning_model_room_for_json(self):
        client = FakeClient()
        advice = generate_repricing_advice({"product": {"title": "Pokemon"}}, client)

        self.assertGreaterEqual(client.max_completion_tokens, 1800)
        self.assertEqual(advice["confidence"], "low")

    def test_repricing_advice_payload_hash_is_stable(self):
        product = Product(title="Pokemon Japanese PSA 10", own_price_idr=750000, search_terms=["Pokemon"])
        payload = build_repricing_advice_payload(
            product=product,
            info={"global_average_idr": 900000, "price_delta_percent": -16.7},
            observations=[{"source_name": "tokopedia", "title": "Pokemon", "price_idr": 900000}],
            price_history=[],
            trend_7d=None,
            trend_30d=None,
            suggested={"quick_sale": 828000, "normal": 882000, "max_profit": 945000},
            counterparts=[],
        )

        self.assertEqual(repricing_advice_input_hash(payload), repricing_advice_input_hash(dict(payload)))
        self.assertIn("source_observations", payload)


if __name__ == "__main__":
    unittest.main()
