"""TP-037 query variants for the offline retrieval experiment.

Shared by the live generator (test/live/gen_retrieval_vectors.py) and
the offline suite, so the embedded string of every variant is
reproducible and hash-checked. Variants change only the query text;
corpus title vectors are unchanged (no re-index). The definitions were
fixed in TP-037 before any variant was measured.

Implements: REQ-SI-QA-002, REQ-SI-FR-007 (ADR-003)
"""

from __future__ import annotations

import re
from typing import Callable

#: V1: one fixed retrieval instruction (asymmetric query embedding).
INSTRUCTION = "Given a financial news search query, retrieve news headlines that are relevant to the query"

#: V2: a watchlist-shaped symbol map. Production stores, per symbol, the
#: canonical symbol, the vendor's official name, and aliases (empty for
#: stocks resolved by the vendor search; set for the benchmark indices).
SYMBOL_MAP: tuple[dict[str, object], ...] = (
    {"code": "AAPL", "official_name": "Apple Inc", "aliases": ()},
    {"code": "MSFT", "official_name": "Microsoft Corporation", "aliases": ()},
    {"code": "NVDA", "official_name": "NVIDIA Corporation", "aliases": ()},
    {"code": "TSLA", "official_name": "Tesla Inc", "aliases": ()},
    {"code": "AMZN", "official_name": "Amazon.com Inc", "aliases": ()},
    {"code": "0700", "official_name": "Tencent Holdings Ltd", "aliases": ()},
    {"code": "9988", "official_name": "Alibaba Group Holding Ltd", "aliases": ()},
    {"code": "HSI", "official_name": "Hang Seng Index", "aliases": ("Hang Seng",)},
)


def _name_head(official_name: str) -> str:
    """First word of the official name, letters and digits only."""
    return re.split(r"[^A-Za-z0-9]+", official_name)[0]


def _matches(query: str, entry: dict[str, object]) -> bool:
    code = str(entry["code"])
    if re.search(rf"(?<![A-Za-z0-9]){re.escape(code)}(?![A-Za-z0-9])", query):
        return True  # ticker: case-sensitive, word-bounded (the S2 rule)
    names = [_name_head(str(entry["official_name"])), *[str(a) for a in entry["aliases"]]]  # type: ignore[union-attr]
    return any(re.search(rf"\b{re.escape(name)}\b", query, re.IGNORECASE) for name in names)


def expand(query: str) -> str:
    """V2: append the official name and code of every matched entity."""
    tags = [f"{entry['official_name']} ({entry['code']})" for entry in SYMBOL_MAP if _matches(query, entry)]
    return f"{query} [{'; '.join(tags)}]" if tags else query


def instruct(query: str) -> str:
    """V1: the instruction-prefixed query form."""
    return f"Instruct: {INSTRUCTION}\nQuery: {query}"


VARIANTS: dict[str, Callable[[str], str]] = {
    "V0": lambda query: query,
    "V1": instruct,
    "V2": expand,
    "V3": lambda query: instruct(expand(query)),
}
