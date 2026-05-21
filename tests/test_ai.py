import unittest
from datetime import datetime, timezone

from pokemon_price_scheduler.ai import attach_ai_summaries, build_summary_prompt, strip_thinking
from pokemon_price_scheduler.models import PriceObservation, Product, Source, SourceResult
from pokemon_price_scheduler.analyze import analyze_product


class FakeClient:
    is_configured = True

    def __init__(self):
        self.messages = []

    def chat(self, messages, max_completion_tokens=280):
        self.messages = messages
        return "Market references support the current price. Keep monitoring thin sources before repricing."


class AiTests(unittest.TestCase):
    def test_strip_thinking_removes_minimax_reasoning_tag(self):
        self.assertEqual(strip_thinking("<think>hidden</think>\n\nVisible note"), "Visible note")

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


if __name__ == "__main__":
    unittest.main()
