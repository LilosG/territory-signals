"""Deterministic validation of AI output. Anything that fails is rejected and never shown."""
from __future__ import annotations

import json
import re
from typing import Any, Iterable

from territory.homeowner_text import ADDRESS

NUM = re.compile(r"(?<![A-Za-z0-9])\$?\d[\d,]*(?:\.\d+)?%?")


def _norm_num(tok: str) -> str | None:
    t = tok.replace("$", "").replace(",", "").rstrip("%")
    try:
        f = float(t)
    except ValueError:
        return None
    return str(int(f)) if f == int(f) else repr(round(f, 6))


def numbers_in(text: str) -> set[str]:
    out = set()
    for m in NUM.finditer(text):
        n = _norm_num(m.group(0))
        if n is not None:
            out.add(n)
    # ISO dates and ids inside the packet: 2026-09-14 yields 2026, 09, 14 via the regex already (hyphen breaks tokens)
    return out


def strings_of(obj: Any) -> Iterable[str]:
    """Every string value in a JSON-like object (keys are structure, not prose)."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from strings_of(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings_of(v)


def check_numbers(output_texts: Iterable[str], packet: Any) -> list[str]:
    """Every number in the output must appear in the packet."""
    allowed = numbers_in(json.dumps(packet, default=str))
    bad = sorted({n for t in output_texts for n in numbers_in(t) if n not in allowed})
    return [f"number {n} is not in the facts" for n in bad]


def _addr_key(a: str) -> str:
    parts = re.sub(r"[^a-z0-9 ]", "", a.lower()).split()
    return " ".join(parts[:2]) if parts else ""


def check_addresses(texts: Iterable[str], allowed: Iterable[str] = ()) -> list[str]:
    """No street address other than the allowed ones (the subject parcel's)."""
    ok = {_addr_key(a) for a in allowed if a}
    bad = []
    for t in texts:
        for m in ADDRESS.finditer(t):
            if _addr_key(m.group(0)) not in ok:
                bad.append(f"address {m.group(0).strip()!r} is not the subject parcel")
    return bad


# Speculation about a person's circumstances. Allowed only if the facts packet itself contains the same wording.
SPECULATION = [
    r"\bneeds? (the )?(money|cash)", r"\bstruggl", r"financ\w* (trouble|hardship|strain|distress|difficult|pressure|problem)",
    r"\bdesperate", r"can'?t afford", r"behind on", r"\bforced to sell", r"\bmust sell", r"\bmotivated seller",
    r"\bdivorc", r"\bwidow", r"\belderly", r"\bseniors?\b", r"\bretir", r"\baging\b", r"\bill(ness)?\b", r"\bsick",
    r"\bhealth", r"\bdisab", r"\bdied\b", r"\bdeath\b", r"\bdeceased", r"\bpassed away", r"\bprobate", r"\binherit",
    r"\brace\b", r"\bethnic", r"\breligio", r"national origin", r"\bimmigra", r"\bfamil(y|ies)\b", r"\bchildren\b",
    r"\bkids\b", r"\bpregnan", r"\bgender", r"\bmarital", r"\bsingle (mom|mother|father|dad)", r"\bcouple\b",
    r"\bhusband|\bwife\b", r"\bage of\b", r"\bbankrupt", r"\bforeclos", r"\bunemploy", r"\bjob loss", r"\bdebts?\b",
]


def check_speculation(texts: Iterable[str], packet: Any) -> list[str]:
    ptxt = json.dumps(packet, default=str).lower()
    out = []
    for t in texts:
        t = re.sub(r"\b(single|multi|two)[- ]family\b", "", t, flags=re.I)      # a building type, not a household
        for pat in SPECULATION:
            m = re.search(pat, t, re.I)
            if m and not re.search(pat, ptxt, re.I):
                out.append(f"speculation about the owner: {m.group(0)!r}")
    return out


def words(s: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", s.lower())


def quote_in_source(quote: str, source: str, max_words: int = 12) -> str | None:
    """None if the quote is at most max_words words and appears word-for-word in the source, else the problem."""
    qw = words(quote)
    if not qw:
        return "quote is empty"
    if len(qw) > max_words:
        return f"quote has {len(qw)} words (max {max_words})"
    sw = words(source)
    n = len(qw)
    if any(sw[i:i + n] == qw for i in range(len(sw) - n + 1)):
        return None
    return "quoted words do not appear in the description"
