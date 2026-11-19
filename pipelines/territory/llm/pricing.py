"""Token prices for providers that do not report cost. Never guessed: a model not listed costs "unknown"."""
from __future__ import annotations

from pathlib import Path

import yaml

PRICING_FILE = Path(__file__).resolve().parents[3] / "config" / "llm_pricing.yaml"


def load_pricing(path: Path | None = None) -> dict:
    with open(path or PRICING_FILE, encoding="utf-8") as fh:
        return (yaml.safe_load(fh) or {}).get("models") or {}


def cost_from_pricing(model: str, input_tokens: int, output_tokens: int, pricing: dict | None = None) -> float | None:
    p = (pricing if pricing is not None else load_pricing()).get(model)
    if not p:
        return None
    return round((input_tokens * p["input_per_m"] + output_tokens * p["output_per_m"]) / 1_000_000, 6)
