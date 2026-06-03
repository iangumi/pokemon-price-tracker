from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .text import clean_text


@dataclass(frozen=True)
class CardIdentity:
    name: str
    set_symbol: str
    language: str
    card_number: str
    rarity: str
    condition: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)

    def tokopedia_query(self) -> str:
        return compact_join([
            self.name,
            self.rarity,
            self.condition,
            self.set_symbol,
            language_query_token(self.language),
        ])

    def ebay_query(self) -> str:
        return self.tokopedia_query()

    def snkrdunk_query(self) -> str:
        return compact_join([self.name, self.rarity, self.set_symbol])


RARITIES = ("SAR", "SR", "UR", "AR", "IR", "SIR", "SEC", "RR", "R", "CHR", "CSR", "PROMO")


def compact_join(parts: list[str]) -> str:
    return clean_text(" ".join(part for part in parts if part))


def language_query_token(language: str) -> str:
    if language == "Japanese":
        return "Japanese"
    if language == "English":
        return "English"
    return ""


def parse_card_identity(title: str) -> CardIdentity:
    clean = clean_text(title)
    lower = f" {clean.lower()} "
    language = "Unknown"
    if any(marker in lower for marker in (" japanese ", " jp ", " jpn ", " jepang ")):
        language = "Japanese"
    elif any(marker in lower for marker in (" english ", " eng ", " en ", " inggris ")):
        language = "English"
    elif " indonesia" in lower:
        language = "Indonesian"

    card_number = ""
    number_match = re.search(r"\b\d{1,3}/\d{1,3}\b", clean)
    if number_match:
        card_number = number_match.group(0)

    set_symbol = ""
    set_match = re.search(r"\b(?:sv|s|m|ma|op|bt|mew|xy)\d+[a-z]?\b", clean, re.I)
    if set_match:
        set_symbol = set_match.group(0)

    rarity = ""
    for candidate in RARITIES:
        if re.search(rf"\b{re.escape(candidate)}\b", clean, re.I):
            rarity = candidate
            break

    condition = "raw NM"
    psa_match = re.search(r"\bPSA\s*(10|9|8|7)\b", clean, re.I)
    if psa_match:
        condition = f"PSA {psa_match.group(1)}"
    elif re.search(r"\bBGS\s*(10|9\.5|9|8\.5|8)\b", clean, re.I):
        condition = clean_text(re.search(r"\bBGS\s*(10|9\.5|9|8\.5|8)\b", clean, re.I).group(0)).upper()
    elif re.search(r"\b(CG C|CGC)\s*(10|9\.5|9|8\.5|8)\b", clean, re.I):
        condition = clean_text(re.search(r"\b(CG C|CGC)\s*(10|9\.5|9|8\.5|8)\b", clean, re.I).group(0)).upper()
    elif re.search(r"\b(NM|Near Mint)\b", clean, re.I):
        condition = "raw NM"

    name = infer_card_name(clean)
    return CardIdentity(
        name=name,
        set_symbol=set_symbol,
        language=language,
        card_number=card_number,
        rarity=rarity,
        condition=condition,
    )


def infer_card_name(title: str) -> str:
    head = re.split(r"\s+-\s+", title, maxsplit=1)[0]
    stop_patterns = [
        r"\bPSA\s*(?:10|9|8|7)\b",
        r"\bBGS\s*(?:10|9\.5|9|8\.5|8)\b",
        r"\bCGC\s*(?:10|9\.5|9|8\.5|8)\b",
        r"\b\d{1,3}/\d{1,3}\b",
        r"\b(?:sv|s|m|ma|op|bt|mew|xy)\d+[a-z]?\b",
    ]
    cut_at = len(head)
    for pattern in stop_patterns:
        match = re.search(pattern, head, re.I)
        if match:
            cut_at = min(cut_at, match.start())
    name = clean_text(head[:cut_at])
    trailing_rarity = "|".join(RARITIES)
    name = clean_text(re.sub(rf"\b(?:{trailing_rarity})\b\s*$", "", name, flags=re.I))
    return name or clean_text(head)
