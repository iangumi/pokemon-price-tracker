import unittest

from pokemon_price_scheduler.card_parser import parse_card_identity


class CardParserTests(unittest.TestCase):
    def test_meowth_title_extracts_search_identity(self):
        identity = parse_card_identity("Meowth Ex SAR 114/080 m3 - Munikis / Nihility Zero - Kartu Pokemon TCG Japanese")

        self.assertEqual(identity.name, "Meowth Ex")
        self.assertEqual(identity.rarity, "SAR")
        self.assertEqual(identity.card_number, "114/080")
        self.assertEqual(identity.set_symbol, "m3")
        self.assertEqual(identity.language, "Japanese")
        self.assertEqual(identity.tokopedia_query(), "Meowth Ex SAR raw NM m3 Japanese")
        self.assertEqual(identity.snkrdunk_query(), "Meowth Ex SAR m3")


if __name__ == "__main__":
    unittest.main()
