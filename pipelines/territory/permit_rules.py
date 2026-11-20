"""Deterministic permit rules shared by the dev_permits adapter and the Phase 3
re-derivation step (territory.permit_rederive), so both always agree.

Group: the APPROVAL_TYPE map in config/permit_signal_map.yaml decides the signal
group. No approval type names an ADU, so a permit with APPROVAL_ADU_TOTAL > 0 is
regrouped as `adu` (the count stays in signal details).

Residential discretionary types: the types listed under `residential_remodel_types` in the map
(coastal, site development, use permits, variances, planned districts, historic, ...) are
`other` by default and become remodel_addition when the record is residential: the parcel's land
use is a residential code, or the record's own PROJECT_TYPE / APPROVAL_TYPE says residential.

Pre-sale prep (v0.4, D14): the electrical / plumbing / mechanical types are only candidates. The permit's
text decides (presale_rules in the map): cosmetic or remodel scope stays pre_sale_prep, solar goes to
solar_energy, non-residential work to other, and everything else (like-for-like systems work, or no text)
to `maintenance`, which carries no score weight.

Stalled: a permit counts as stalled only when
  - its group is remodel_addition, adu or demolition_lot_split,
  - it was issued, APPROVAL_EXPIRE_DATE is more than 90 days and at most 36 months before the run date,
  - it has no APPROVAL_CLOSE_DATE and its status is not terminal.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Collection, Mapping, Optional

import re

import pandas as pd
import yaml
from dateutil.relativedelta import relativedelta

MAP_PATH = Path(__file__).resolve().parents[2] / "config" / "permit_signal_map.yaml"
SIGNAL_GROUPS = ["pre_sale_prep", "maintenance", "remodel_addition", "adu", "demolition_lot_split",
                 "solar_energy", "other"]
STALLED_GROUPS = ("remodel_addition", "adu", "demolition_lot_split")
STALLED_MIN_DAYS_PAST_EXPIRY = 90
STALLED_MAX_MONTHS_PAST_EXPIRY = 36
TERMINAL_STATUS = {"closed", "final closed", "finaled", "completed", "cancelled",
                   "cancelled utilization not met", "void", "withdrawn"}


def load_map(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else MAP_PATH
    if not p.exists():
        raise FileNotFoundError(f"{p} not found; review permit_type_profile.csv and create it")
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    mapping = data.get("approval_types") or {}
    bad = {k: v for k, v in mapping.items() if v not in SIGNAL_GROUPS}
    if bad:
        raise ValueError(f"permit_signal_map.yaml has unknown signal groups: {bad}")
    res_types = set(data.get("residential_remodel_types") or [])
    unknown = res_types - set(mapping)
    if unknown:
        raise ValueError(f"residential_remodel_types not in approval_types: {sorted(unknown)}")
    rules = data.get("presale_rules") or {}
    # A map without presale_rules (older or test maps) leaves pre_sale_prep types as the bare type says.
    compiled = {k: [re.compile(p, re.I) for p in rules.get(k, [])]
                for k in ("non_residential", "new_construction", "solar", "cosmetic_scope", "weak_scope",
                          "systems_work")} if rules else None
    return {"status": data.get("status"), "approval_types": mapping,
            "residential_remodel_types": res_types, "presale_rules": compiled}


def parse_date(v) -> Optional[date]:
    d = pd.to_datetime(v, errors="coerce")
    return None if pd.isna(d) else d.date()


def adu_total(payload: Mapping[str, Any]) -> float:
    n = pd.to_numeric(payload.get("APPROVAL_ADU_TOTAL"), errors="coerce")
    return 0.0 if pd.isna(n) else float(n)


def record_is_residential(payload: Mapping[str, Any]) -> bool:
    """The record's own fields say residential (PROJECT_TYPE or APPROVAL_TYPE)."""
    for f in ("PROJECT_TYPE", "APPROVAL_TYPE"):
        v = (payload.get(f) or "").lower()
        if "residential" in v and "nonresidential" not in v and "non-residential" not in v:
            return True
    return False


def permit_text(payload: Mapping[str, Any]) -> str:
    """The description the pre-sale rules read: the approval scope, else the job description, else the
    project title and scope (a permit with no text of its own inherits its project's)."""
    for f in ("APPROVAL_SCOPE", "JOB_BC_CODE_DESCRIPTION"):
        v = str(payload.get(f) or "").strip()
        if v:
            return v
    return " ".join(str(payload.get(f) or "").strip() for f in ("PROJECT_TITLE", "PROJECT_SCOPE")).strip()[:1500]


def _any(patterns, text: str) -> bool:
    return any(p.search(text) for p in patterns)


def refine_pre_sale(text: str, rules: Mapping[str, Any]) -> str:
    """Group for a permit whose TYPE makes it a pre_sale_prep candidate (see presale_rules in the map)."""
    if _any(rules["non_residential"], text) or _any(rules["new_construction"], text):
        return "other"
    if _any(rules["solar"], text):
        return "solar_energy"
    if _any(rules["cosmetic_scope"], text):
        return "pre_sale_prep"
    if _any(rules["weak_scope"], text) and not _any(rules["systems_work"], text):
        return "pre_sale_prep"
    return "maintenance"


def group_for(approval_type: str, adu: float, mapping: Mapping[str, str],
              residential: bool = False, residential_types: Collection[str] = (),
              text: str = "", presale_rules: Optional[Mapping[str, Any]] = None) -> str:
    """Signal group for one approval. Unmapped types are 'other'. A pre_sale_prep type is refined by its
    description when `presale_rules` is given (without rules the bare type decides, as before v0.4)."""
    if adu > 0:
        return "adu"
    group = mapping.get(approval_type, "other")
    if group == "other" and residential and approval_type in residential_types:
        return "remodel_addition"
    if group == "pre_sale_prep" and presale_rules:
        return refine_pre_sale(text, presale_rules)
    return group


def is_stalled(group: str, issue: Optional[date], expire: Optional[date], close: Optional[date],
               status: Optional[str], run_date: date) -> bool:
    return bool(
        group in STALLED_GROUPS and issue and expire and close is None
        and (run_date - expire).days > STALLED_MIN_DAYS_PAST_EXPIRY
        and expire >= run_date - relativedelta(months=STALLED_MAX_MONTHS_PAST_EXPIRY)
        and (status or "").strip().lower() not in TERMINAL_STATUS)


def derive(payload: Mapping[str, Any], approval_id: str, mapping: Mapping[str, str],
           run_date: date, parcel_residential: bool = False,
           residential_types: Collection[str] = (),
           presale_rules: Optional[Mapping[str, Any]] = None) -> list[dict[str, Any]]:
    """Permit signals for one approval: [{signal_type, group, signal_date, details}]."""
    atype = payload.get("APPROVAL_TYPE", "")
    adu = adu_total(payload)
    residential = parcel_residential or record_is_residential(payload)
    group = group_for(atype, adu, mapping, residential, residential_types, permit_text(payload), presale_rules)
    issue, expire, close = (parse_date(payload.get("APPROVAL_ISSUE_DATE")),
                            parse_date(payload.get("APPROVAL_EXPIRE_DATE")),
                            parse_date(payload.get("APPROVAL_CLOSE_DATE")))
    base = {
        "approval_id": approval_id, "approval_type": atype or None,
        "approval_status": payload.get("APPROVAL_STATUS"), "project_type": payload.get("PROJECT_TYPE"),
        "project_id": payload.get("PROJECT_ID"), "job_description": payload.get("JOB_BC_CODE_DESCRIPTION"),
        "scope": (payload.get("APPROVAL_SCOPE") or "")[:500] or None,
        "valuation": payload.get("APPROVAL_VALUATION"), "adu_total": payload.get("APPROVAL_ADU_TOTAL"),
        "du_net_change": payload.get("APPROVAL_DU_NET_CHANGE"),
        "floor_area": payload.get("APPROVAL_FLOOR_AREA"),
        "issue_date": str(issue) if issue else None, "expire_date": str(expire) if expire else None,
        "close_date": str(close) if close else None, "sets": payload.get("_sets"),
        "residential_record": residential,
    }
    out: list[dict[str, Any]] = []
    if issue:
        out.append({"signal_type": "permit_approved", "group": group, "signal_date": issue,
                    "details": dict(base)})
    if is_stalled(group, issue, expire, close, payload.get("APPROVAL_STATUS"), run_date):
        out.append({"signal_type": "permit_stalled", "group": group, "signal_date": expire,
                    "details": {**base, "days_past_expiry": (run_date - expire).days}})
    return out
