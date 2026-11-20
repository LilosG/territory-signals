"""What homeowner-facing text may never contain. One list, used by the outreach template tests (Phase 5A) and by the
weekly newsletter validator (Phase 5F)."""
from __future__ import annotations

import re

# Solicitation phrasing that implies we are watching a household (outreach drafts only).
PHRASING = [r"\bneighbors?\b", r"public records?", r"records show", r"our records", r"we (know|noticed|saw|found)",
            r"according to"]
# Sensitive life-event and financial words.
SENSITIVE = [r"\bdeath\b", r"\bdied\b", r"\bdeceased\b", r"passed away", r"inherit", r"probate",
             r"\bestate of\b", r"tax[- ]default", r"delinquen", r"\bdebt", r"foreclos", r"non-?renewal", r"insurance",
             r"\blien", r"\bmortgage", r"distress", r"\bdefault", r"\bbankrupt", r"\bpower[- ]to[- ]sell"]
BANNED = PHRASING + SENSITIVE
INTERNAL_LABELS = [r"\(estimated\)", r"\(sample data\)", r"\bestimated\b", r"\bsample\b", r"\bscores?\b",
                   r"\bsignals?\b", r"\btier\b", r"\brecipe\b", r"\bSB ?9\b", r"\bSB ?79\b", r"\bconfidence\b"]
# Extra words the newsletter must not use (internal vocabulary).
NEWSLETTER_EXTRA = [r"\bleads?\b", r"\bpermits? signals?\b", r"\bstro\b", r"\bupzoning\b"]
ADDRESS = re.compile(r"\b\d{2,5}\s+(?:[NSEW]\.?\s+)?[A-Za-z][A-Za-z']+(?:\s+[A-Za-z][A-Za-z']+)?\s+"
                     r"(?:st|street|ave|avenue|blvd|boulevard|dr|drive|ln|lane|rd|road|way|ct|court|pl|place|ter|"
                     r"terrace|cir|circle|walk|pkwy|parkway)\b\.?", re.I)


def internal_names() -> set[str]:
    """Every signal type, group, component key, recipe key and band name in the catalog (snake_case or with a colon)."""
    from territory.config import load_client
    from territory.export_catalog import build_catalog
    cat = build_catalog(load_client("kaiser-team"))
    names = {t["key"] for t in cat["signal_types"]} | {g["key"] for g in cat["signal_groups"]}
    names |= {c["key"] for c in cat["components"]} | {r["key"] for r in cat["recipes"]}
    return {n for n in names if "_" in n or ":" in n}


def check_homeowner_text(text: str, extra_names: set[str] | None = None, recipe_labels: set[str] | None = None) -> list[str]:
    """Problems found in text a homeowner could read (empty list = clean)."""
    problems: list[str] = []
    for pat in INTERNAL_LABELS + SENSITIVE + NEWSLETTER_EXTRA:
        if re.search(pat, text, re.I):
            problems.append(f"internal or sensitive wording {pat!r}")
    if ADDRESS.search(text):
        problems.append("contains a street address")
    for n in (internal_names() | (extra_names or set())):
        if n.lower() in text.lower():
            problems.append(f"internal name {n!r}")
    for label in (recipe_labels or set()):
        if label and re.search(rf"\b{re.escape(label)}\b", text, re.I):
            problems.append(f"recipe name {label!r}")
    if "[" in text or "{" in text:
        problems.append("unfilled placeholder or banner")
    return problems
