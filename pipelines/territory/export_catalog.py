"""Single source of truth for names: python -m territory.export_catalog [--client kaiser-team]

Writes dashboard/src/data/catalog.generated.json from config/scoring.yaml, config/permit_labels.yaml,
config/signal_labels.yaml and the client's recipe toggles. The dashboard (Phase 5B) reads only this file for
signal, recipe, component and band names; it keeps no list of its own. Deterministic: no database, no clock.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import yaml

from territory.config import ClientConfig, load_client
from territory.scoring_engine import load_scoring_config

ROOT = Path(__file__).resolve().parents[2]
SIGNAL_LABELS_PATH = ROOT / "config" / "signal_labels.yaml"
OUTPUT_PATH = ROOT / "dashboard" / "src" / "data" / "catalog.generated.json"
CATALOG_VERSION = 1


def load_signal_labels(path: Path | None = None) -> dict[str, Any]:
    return yaml.safe_load((path or SIGNAL_LABELS_PATH).read_text(encoding="utf-8"))


def component_specs(cfg: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every component key the scorer can write, with its family and the most points it can contribute."""
    specs: list[dict[str, Any]] = []
    for stype, sc in cfg["signals"].items():
        if "by_group" in sc:
            for group, g in sc["by_group"].items():
                if float(g["weight"]) > 0:
                    specs.append({"key": f"{stype}:{group}", "kind": "signal", "family": sc["family"],
                                  "max_points": float(g["weight"])})
        elif "by_detail" in sc:
            specs.append({"key": stype, "kind": "signal", "family": sc["family"],
                          "max_points": max(float(v) for v in sc["values"].values())})
        else:
            specs.append({"key": stype, "kind": "signal", "family": sc["family"],
                          "max_points": float(sc["weight"])})
    om = cfg["owner_modifiers"]
    specs += [
        {"key": "owner:years_owned", "kind": "owner", "family": "owner",
         "max_points": float(max(t["weight"] for t in om["years_owned"]))},
        {"key": "owner:absentee", "kind": "owner", "family": "owner", "max_points": float(om["absentee"]["weight"])},
        {"key": "owner:out_of_state", "kind": "owner", "family": "owner",
         "max_points": float(om["out_of_state"]["weight"])},
        {"key": "owner:mortgage_open_false", "kind": "owner", "family": "owner",
         "max_points": float(om["mortgage_open_false"]["weight"])},
        {"key": "owner:est_equity_top_quartile", "kind": "owner", "family": "owner",
         "max_points": float(om["est_equity_top_quartile"]["weight"])},
        {"key": "owner:portfolio_owner_multi", "kind": "owner", "family": "owner",
         "max_points": float(om["portfolio_owner_multi"]["weight"])},
        {"key": "owner:ownership_transfer", "kind": "owner", "family": "owner", "max_points": 0.0},
    ]
    return specs


def build_catalog(client: ClientConfig, cfg: Mapping[str, Any] | None = None,
                  labels: Mapping[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or load_scoring_config()
    labels = labels or load_signal_labels()
    missing = []

    def lab(section: str, key: str) -> str:
        v = labels[section].get(key)
        if v is None:
            missing.append(f"{section}.{key}")
        return v or key

    components = []
    for spec in component_specs(cfg):
        components.append({**spec, "label": lab("components", spec["key"]),
                           "family_label": lab("families", spec["family"])})
    recipes = []
    for key, rec in cfg["recipes"].items():
        toggle = client.recipes.get(key)
        recipes.append({
            "key": key, "label": rec["label"], "short_description": rec["short_description"],
            "enabled": bool(toggle and toggle.enabled and rec.get("active") is not False),
            "requires_data": list(rec.get("requires_data", [])),
        })
    signal_types = [{"key": k, "label": lab("signal_types", k)} for k in sorted(set(cfg["signals"]) | set(labels["signal_types"]))]
    groups = {rec for rec in labels["signal_groups"]}
    signal_groups = [{"key": k, "label": lab("signal_groups", k)} for k in sorted(groups)]
    permit_types = [{"key": k, "label": v} for k, v in sorted(cfg["permit_labels"].items())]
    if missing:
        raise KeyError("config/signal_labels.yaml is missing labels: " + ", ".join(missing))
    return {
        "catalog_version": CATALOG_VERSION,
        "client_id": client.client_id,
        "model_version": cfg["model_version"],
        "signal_types": signal_types,
        "signal_groups": signal_groups,
        "permit_types": permit_types,
        "recipes": recipes,
        "components": components,
        "owner_modifier_cap": float(cfg["owner_modifiers"]["cap"]),
        "score_bands": [{"key": b["key"], "label": b["label"], "min": b["min"]} for b in cfg["score_bands"]],
        "stages": [{"key": k, "label": v} for k, v in labels["stages"].items()],
    }


def write_catalog(client: ClientConfig, path: Path | None = None) -> Path:
    path = path or OUTPUT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_catalog(client), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="territory.export_catalog")
    ap.add_argument("--client", default="kaiser-team")
    args = ap.parse_args(argv)
    path = write_catalog(load_client(args.client))
    cat = json.loads(path.read_text(encoding="utf-8"))
    print(f"wrote {path.relative_to(ROOT)}: model {cat['model_version']}, {len(cat['signal_types'])} signal types, "
          f"{len(cat['signal_groups'])} signal groups, {len(cat['permit_types'])} permit types, "
          f"{len(cat['recipes'])} recipes ({sum(r['enabled'] for r in cat['recipes'])} enabled), "
          f"{len(cat['components'])} components, {len(cat['score_bands'])} bands")
    return 0


if __name__ == "__main__":
    sys.exit(main())
