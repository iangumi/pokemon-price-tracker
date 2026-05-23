"""Pure text-processing utilities — domain concern, no I/O."""

from __future__ import annotations

import html
import re


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()