"""Deterministic validation of AI output. Anything that fails is rejected and never shown."""
from __future__ import annotations

import json
import re
from typing import Any, Iterable

from territory.homeowner_text import ADDRESS

NUM = re.compile(r"(?<![A-Za-z0-9])\$?\d[\d,]*(?:\.\d+)?%?")
# One number as written in prose: optional $, digits, optional K / M / B / thousand / million / billion, optional %.
TOKEN = re.compile(r"(?<![A-Za-z0-9])(\$)?\s?(\d[\d,]*(?:\.\d+)?)(?:\s?(thousand|million|billion|[kKmMbB])(?![A-Za-z]))?(\s?%|\s?per ?cent\b)?")
MULT = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "billion": 1e9}


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


def _values(text: str) -> list[float]:
    vals = []
    for m in NUM.finditer(text):
        n = _norm_num(m.group(0))
        if n is not None:
            vals.append(float(n))
    return vals


def _decimals(num: str) -> int:
    return len(num.split(".")[1]) if "." in num else 0


def rounded_from(num: str, mult: float, pct: bool, money: bool, source_values: list[float]) -> bool:
    """Is this written number a rounded or abbreviated form of a number in the facts?
    $3.05M and $3.0M and $3M all come from 3,047,960; 3.0M is 3.048 rounded to the one decimal it shows.
    Percentages round to a whole number. Plain money written with trailing zeros ($3,050,000) is a rounding too.
    Years, counts and dates are never rounded: those must match exactly."""
    text = num.replace(",", "")
    v = float(text)
    if mult != 1:                                   # "$3.05M": it is right if rounding the fact to the shown decimals gives it
        half = 0.5 * 10 ** -_decimals(text) * mult
        return any(abs(p - v * mult) <= half + 1e-9 for p in source_values if p >= 1000)
    if pct:                                         # "26%": the fact rounded to a whole number
        return any(int(p + 0.5) == int(v) for p in source_values)
    if money and v >= 1000:                         # "$3,050,000" or "$3,048,000": zeros at the end mean it was rounded
        zeros = len(text.split(".")[0]) - len(text.split(".")[0].rstrip("0"))
        half = 0.5 * 10 ** zeros
        return zeros >= 2 and any(abs(p - v) <= half and p >= 1000 for p in source_values)
    return False


def number_problems(output_text: str, allowed: set[str], source_values: list[float]) -> set[str]:
    bad = set()
    for m in TOKEN.finditer(output_text):
        dollar, num, suffix, pct = m.group(1), m.group(2), m.group(3), m.group(4)
        written = m.group(0).strip()
        exact = _norm_num(num)
        if exact is None:
            continue
        mult = MULT[suffix.lower()] if suffix else 1
        if mult == 1 and exact in allowed:
            continue
        if rounded_from(num, mult, bool(pct), bool(dollar), source_values):
            continue
        if mult != 1 and exact in allowed and not dollar:       # "13 thousand" style is never used for counts
            continue
        bad.add(written)
    return bad


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
    """Every number in the output must appear in the packet, exactly or as a rounded or abbreviated form of a
    packet number ($3,047,960 may be written $3.05M or $3.0M; 25.6% may be written 26%)."""
    ptxt = json.dumps(packet, default=str)
    allowed, vals = numbers_in(ptxt), _values(ptxt)
    bad = sorted({n for t in output_texts for n in number_problems(t, allowed, vals)})
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


# ---- lead brief v2 style rules (Phase 5G) ----------------------------------------------------------------------------
ZONING_CODE = re.compile(r"\b[A-Z]{1,5}-\d+(?:-\d+)?[A-Z]?\b")
MONTHS = "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
# The page header already shows these; the summary may use at most one of them.
HEADER_FACTS: dict[str, re.Pattern] = {
    "lot size": re.compile(r"\b\d[\d,.]*\s*(?:sq\.?\s?ft|sqft|square[- ]f(?:oo|ee)t|acres?)\b|\blot size\b", re.I),
    "zoning": re.compile(r"\bzon(?:ed|ing)\b|" + ZONING_CODE.pattern),
    "permit date": re.compile(
        rf"\b(?:{MONTHS})[a-z]*\.?\s+\d{{1,2}}\b|\b(?:{MONTHS}|May)[a-z]*\.?,?\s+\d{{4}}\b|\b\d{{4}}-\d{{2}}-\d{{2}}\b|"
        r"\b(?:January|February|March|April|June|July|August|September|October|November|December)\b"),
    "years owned": re.compile(
        r"\b(?:owned|owner(?:ship)?|held|held for|tenure)\b[^.]{0,40}?\b\d+\s*(?:\+\s*)?years?\b|"
        r"\b\d+[- ]?(?:\+\s*)?years?\b[^.]{0,25}?\b(?:owner(?:ship)?|owned|tenure|held)\b", re.I),
}


def header_facts_in(text: str) -> list[str]:
    return [k for k, p in HEADER_FACTS.items() if p.search(text)]


def check_header_facts(summary: str, limit: int = 1) -> list[str]:
    """The summary must say why this home and why now, not restate the page header (lot size, zoning, permit
    dates, years owned). One header fact is allowed when it supports the why."""
    found = header_facts_in(summary)
    return [f"summary restates the page header ({', '.join(found)}); use at most {limit} header fact"] if len(found) > limit else []


BANNED_WORDS = [(re.compile(r"\bsample data\b", re.I), "sample data"), (re.compile(r"\bplaybooks?\b", re.I), "playbook"),
                (re.compile(r"\brecipes?\b", re.I), "recipe")]


def check_banned_words(texts: Iterable[str]) -> list[str]:
    """Badges show sample data; recipes are described by what they mean. Neither word appears in prose."""
    out = []
    for pat, name in BANNED_WORDS:
        if any(pat.search(t) for t in texts):
            out.append(f"the word {name!r} must not appear in the text")
    return out


HEADLINE_JARGON = [re.compile(p, re.I) for p in (
    r"\bSB ?\d+\b", r"\bzon(?:ed|ing)\b", r"\bsq\.? ?ft\b", r"\bAPN\b", r"\bADU\b", r"\bupzon\w*", r"\bmulti-?family\b")]
HEADLINE_FLAT_START = re.compile(r"^\W*(?:recent|new|latest|several|multiple|two|three|\d+)?\s*(?:building |remodel |solar )?permits?\b", re.I)


def check_headline(headline: str, max_words: int = 10, internal_names: Iterable[str] = ()) -> list[str]:
    """Names the angle in plain words: at most 10 words, no zoning code or jargon, and not "Recent permits ..."."""
    problems = []
    if len(headline.split()) > max_words:
        problems.append(f"headline is longer than {max_words} words")
    if ZONING_CODE.search(headline) or any(p.search(headline) for p in HEADLINE_JARGON):
        problems.append("headline contains a zoning code or jargon; name the angle in plain words")
    names = [*internal_names, "pre-sale prep", "pre-list prep"]
    if any(re.search(r"\b" + re.escape(n) + r"\b", headline, re.I) for n in names):
        problems.append("headline uses an internal category name; describe the angle in plain words")
    if HEADLINE_FLAT_START.search(headline) or re.match(r"^\W*recent\b", headline, re.I):
        problems.append("headline starts with 'Recent permits'-style wording; name the angle, not the document")
    return problems


GENERIC_ANGLE = [re.compile(p, re.I) for p in (
    r"market (update|report|overview|snapshot|conditions|trends)", r"(neighbou?rhood|area|local) (update|overview|snapshot)",
    r"\b(current|recent) market\b", r"inventory (levels|numbers)", r"recent (sales|activity) (nearby|in the area)")]


def check_angle(angle: str) -> list[str]:
    """One sentence about THIS property; no generic "market update" opener."""
    problems = []
    if any(p.search(angle) for p in GENERIC_ANGLE):
        problems.append("suggested angle is a generic market-update opener; make it specific to this property's signals")
    if len([s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", angle.strip()) if s]) != 1:
        problems.append("suggested angle must be one sentence")
    return problems


# Phase 5G: what a brief may not claim about the owner, and how it may talk about its own sources.
INTENT_AS_FACT = re.compile(
    r"\b(?:prepp?ing|preparing|getting ready|gets? ready|readying)\b[^.]{0,30}\b(?:to sell|for sale|to list|to move)\b|"
    r"\b(?:plans?|planning|intends?|intending|wants?|wanting|looking|hoping|aims?) to (?:sell|list|move|downsize)\b|"
    r"\bis (?:about|ready) to (?:sell|list)\b|\bwill (?:sell|list)\b", re.I)
META_TALK = re.compile(r"\b(?:our|the) (?:configuration|config|notes|packet|methodology)\b|\baccording to (?:our|the) (?:notes|records|data)\b|\bour (?:records|data|rules)\b", re.I)


HEDGE = re.compile(r"\b(?:may|might|could|possibly|perhaps|whether|if|ask(?:s|ing)?|about|consider(?:ing)?|any|sign of|signs of)\b[^.]{0,25}$", re.I)


def _intent_as_fact(text: str):
    """The first intent-to-sell phrase in `text` that is not hedged ("may plan to sell", "ask whether they plan to sell")."""
    for m in INTENT_AS_FACT.finditer(text):
        if not HEDGE.search(text[max(0, m.start() - 40):m.start()]):
            return m
    return None


def check_intent_and_meta(texts: Iterable[str]) -> list[str]:
    """No intent stated as fact ("prepping the home to sell"), and no talk about our own configuration or notes."""
    out = []
    for t in texts:
        if m := _intent_as_fact(t):
            out.append(f"states the owner's intent as fact ({m.group(0)!r}); say what the records show, or 'may'")
        if m := META_TALK.search(t):
            out.append(f"talks about our own configuration or notes ({m.group(0)!r}); state the meaning directly")
    return out


GENERALITIES = re.compile(
    r"\b(?:often|usually|typically|generally|commonly|tends? to|this time of year|seasons?|seasonal|demand|prices?|"
    r"market conditions|the market|buyers?|sellers?)\b", re.I)


def check_newsletter_generalities(text: str) -> list[str]:
    """A newsletter may only say what the facts say: no claims about seasons, prices, demand or what is "often" true."""
    m = GENERALITIES.search(text)
    return [f"newsletter makes a general claim not in the facts ({m.group(0)!r})"] if m else []
