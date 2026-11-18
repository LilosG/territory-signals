"""Salutation formatter for owner names (assessor / ATTOM style, upper case, LAST FIRST order).

Deterministic, no AI. When the name is anything we cannot read with confidence the salutation falls back
to "To the owners of <situs address>," so a wrong greeting is never produced. Names that are not entirely
upper case are not trusted to be LAST FIRST and also fall back. A salutation never mentions death,
estates or the owner's circumstances.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

ORG_WORDS = {
    "LLC", "INC", "INCORPORATED", "CORP", "CORPORATION", "LP", "LLP", "LTD", "CO", "COMPANY", "PARTNERS",
    "PARTNERSHIP", "HOLDINGS", "PROPERTIES", "INVESTMENTS", "INVESTMENT", "ASSOCIATION", "ASSOC", "ASSN",
    "BANK", "CHURCH", "FUND", "FOUNDATION", "GROUP", "ENTERPRISES", "VENTURES", "REALTY", "HOA",
    "UNIVERSITY", "SCHOOL", "DISTRICT", "HOMEOWNERS", "CONDOMINIUM", "APARTMENTS", "CAPITAL",
}
ORG_PHRASES = ("CITY OF", "COUNTY OF", "STATE OF", "UNITED STATES", "L L C", "ET AL", "ET UX", "ET VIR")
ESTATE_WORDS = {"ESTATE", "ESTATES", "EST", "DECEASED", "DECD", "DEC'D", "DEC", "LIFE", "PROBATE"}
OTHERS_WORDS = {"ETAL", "ETUX", "ETVIR"}
MARITAL_CODES = {"JT", "TC", "CP", "HW", "JTWROS", "MM", "SP", "HUSBAND", "WIFE", "HUSB"}
TRUSTEE_CODES = {"TR", "TRS", "TTEE", "TTEES", "TRUSTEE", "TRUSTEES"}
SUFFIXES = {"JR": "Jr", "SR": "Sr", "II": "II", "III": "III", "IV": "IV"}
PARTICLES = {"DE", "DEL", "DELA", "LA", "LE", "VAN", "VON", "DER", "DEN", "DI", "DA", "DOS", "SAN", "ST"}
TRUST_DESCRIPTORS = {"FAMILY", "LIVING", "REVOCABLE", "IRREVOCABLE", "SURVIVORS", "SURVIVOR", "MARITAL",
                     "BYPASS", "REV", "LIV", "FAM", "INTER", "VIVOS", "JOINT", "SEPARATE"}
TRUST_ABBREV = {"REV": "Revocable", "LIV": "Living", "FAM": "Family"}
_NAME_TOKEN = re.compile(r"^[A-Z][A-Z'\-]+$")
_DIRECTIONS = {"N", "S", "E", "W", "NE", "NW", "SE", "SW"}


@dataclass(frozen=True)
class Salutation:
    text: str                 # the full line, e.g. "Dear John Smith,"
    uses_owner_name: bool     # False for the address fallback (the owner name was not used)
    kind: str                 # person | couple | trustee | trust | fallback


def pretty_address(address: str | None) -> str:
    """'2307 CALLE DE LA GARZA' -> '2307 Calle De La Garza'. Directions stay upper case."""
    if not address:
        return ""
    out = []
    for w in " ".join(address.split()).split(" "):
        out.append(w if w in _DIRECTIONS else (w.title() if w.isupper() or w.islower() else w))
    return " ".join(out)


def fallback(situs_address: str | None) -> Salutation:
    where = pretty_address(situs_address)
    return Salutation(f"To the owners of {where}," if where else "To the property owner,", False, "fallback")


def _title(tok: str) -> str:
    t = tok.title()
    return re.sub(r"^Mc([a-z])", lambda m: "Mc" + m.group(1).upper(), t)


class _Unreadable(Exception):
    pass


def _clean_tokens(name: str) -> list[str]:
    s = name.replace(",", " ").replace(".", " ").replace("H/W", "HW")
    s = re.sub(r"\bAND\b", "&", s).replace("&", " & ")
    return s.split()


def _parse_first_segment(tokens: list[str]) -> tuple[str, str, str | None]:
    """'SURNAME [particles] FIRST [initials] [suffix]' -> (surname, first name, suffix)."""
    toks = list(tokens)
    suffix = None
    if toks and toks[-1] in SUFFIXES:
        suffix = SUFFIXES[toks.pop()]
    i = 0
    while i < len(toks) - 1 and toks[i] in PARTICLES:
        i += 1
    surname_toks, rest = toks[: i + 1], toks[i + 1:]
    if not rest or not all(_NAME_TOKEN.match(t) for t in surname_toks):
        raise _Unreadable
    first, middles = rest[0], rest[1:]
    if not _NAME_TOKEN.match(first) or len(first) < 2 or any(len(m) != 1 for m in middles):
        raise _Unreadable                  # initial-only first name, or a middle part we cannot read
    return " ".join(_title(t) for t in surname_toks), _title(first), suffix


def _parse_next_segment(tokens: list[str], surname: str) -> str:
    """Later owner: 'FIRST [initial]' (shares the surname) or 'SURNAME FIRST [initial]' (same surname)."""
    toks = list(tokens)
    sur = surname.upper().split()
    if toks[: len(sur)] == sur and len(toks) > len(sur):
        toks = toks[len(sur):]
    if not toks or not _NAME_TOKEN.match(toks[0]) or len(toks[0]) < 2 or any(len(m) != 1 for m in toks[1:]):
        raise _Unreadable
    return _title(toks[0])


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _people(tokens: list[str]) -> tuple[list[str], str, str | None]:
    segs: list[list[str]] = [[]]
    for t in tokens:
        if t == "&":
            segs.append([])
        else:
            segs[-1].append(t)
    if any(not s for s in segs):
        raise _Unreadable
    surname, first, suffix = _parse_first_segment(segs[0])
    return [first] + [_parse_next_segment(s, surname) for s in segs[1:]], surname, suffix


def _trust_entity(tokens: list[str]) -> str:
    """'SMITH FAMILY TRUST' -> 'Smith Family Trust'; 'SMITH JOHN & MARY TRUST' -> 'John and Mary Smith Trust'.
    Anything after the word TRUST (such as 'DTD 3/4/2001') is ignored."""
    toks = tokens[: tokens.index("TRUST")]
    while toks and toks[0] == "THE":
        toks = toks[1:]
    desc: list[str] = []
    while len(toks) > 1 and toks[-1] in TRUST_DESCRIPTORS:
        desc.insert(0, toks.pop())
    if not toks or any(not re.match(r"^[A-Z'&\-]+$", t) for t in toks):
        raise _Unreadable
    if len(toks) == 1:
        owners = _title(toks[0])
    else:
        firsts, surname, suffix = _people(toks)
        owners = f"{_join(firsts)} {surname}" + (f" {suffix}" if suffix else "")
    return owners + "".join(f" {TRUST_ABBREV.get(d, _title(d))}" for d in desc) + " Trust"


def format_salutation(owner_name: str | None, situs_address: str | None, is_sample: bool = False) -> Salutation:
    name = " ".join((owner_name or "").split())
    if not name or is_sample or name.upper().startswith("SAMPLE OWNER") or name != name.upper():
        return fallback(situs_address)
    toks = _clean_tokens(name)
    words = set(toks)
    joined = " ".join(toks)
    if words & (ESTATE_WORDS | OTHERS_WORDS | ORG_WORDS) or any(p in joined for p in ORG_PHRASES):
        return fallback(situs_address)
    try:
        if "TRUST" in words:
            core = [t for t in toks if t not in TRUSTEE_CODES]
            return Salutation(f"To the Trustee of the {_trust_entity(core)},", True, "trust")
        if re.search(r"\d", joined):
            return fallback(situs_address)
        trustee = bool(words & TRUSTEE_CODES)
        core = [t for t in toks if t not in TRUSTEE_CODES and t not in MARITAL_CODES]
        while core and core[-1] == "&":
            core.pop()
        firsts, surname, suffix = _people(core)
        who = f"{_join(firsts)} {surname}" + (f" {suffix}" if suffix and len(firsts) == 1 else "")
        if trustee:                              # individual trustees are greeted as people
            return Salutation(f"Dear {who},", True, "trustee")
        return Salutation(f"Dear {who},", True, "couple" if len(firsts) > 1 else "person")
    except _Unreadable:
        return fallback(situs_address)
