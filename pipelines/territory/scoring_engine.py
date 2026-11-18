"""Deterministic scoring engine: pure functions, no database, no AI, no clock.

Everything here is computed from the inputs passed in (signals, the owner row, the
as-of date and config/scoring.yaml), so the same inputs always give the same output.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import yaml
from dateutil.relativedelta import relativedelta

SCORING_PATH = Path(__file__).resolve().parents[2] / "config" / "scoring.yaml"
LABELS_PATH = Path(__file__).resolve().parents[2] / "config" / "permit_labels.yaml"
TRANSFER_TYPES_PATH = Path(__file__).resolve().parents[2] / "config" / "transfer_types.yaml"
SAMPLE_LABEL = "(sample data)"
ESTIMATE_LABEL = "(estimated)"
SAMPLE_ESTIMATE_LABEL = "(sample data, estimated)"


# ---------------------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Sig:
    id: str
    type: str
    group: str
    date: Optional[date]
    source_key: str
    source_record_id: str
    confidence: float
    match_method: str
    is_estimate: bool = False
    is_sample: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Owner:
    last_sale_date: Optional[date] = None
    owner_occupied: Optional[bool] = None
    absentee: Optional[bool] = None
    out_of_state: Optional[bool] = None
    mortgage_open: Optional[bool] = None
    est_equity: Optional[float] = None
    is_sample: bool = False
    provider: str = "sample"
    as_of: Optional[date] = None
    # Set by resolve_tenure() when the latest record is a transfer by death, trust or inheritance.
    # last_sale_date is then the transfer date: the CURRENT owner's tenure starts there.
    transfer_date: Optional[date] = None
    transfer_kind: Optional[str] = None
    prior_owner_years: Optional[int] = None


def load_scoring_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg = yaml.safe_load(Path(path or SCORING_PATH).read_text(encoding="utf-8"))
    for key in ("model_version", "residential_land_use", "signals", "owner_modifiers",
                "stacking", "recipes", "suppression", "reason_text"):
        if key not in cfg:
            raise ValueError(f"scoring config is missing '{key}'")
    cfg["residential_codes"] = [str(c) for c in cfg["residential_land_use"]]
    cfg["permit_labels"] = load_permit_labels()
    cfg["transfer_types"] = load_transfer_types()
    return cfg


class MissingPermitLabel(KeyError):
    """A permit type used in a signal has no plain-English label in config/permit_labels.yaml."""


def load_permit_labels(path: str | Path | None = None) -> dict[str, str]:
    return yaml.safe_load(Path(path or LABELS_PATH).read_text(encoding="utf-8"))["labels"]


def norm_doc_type(v: Any) -> str:
    return " ".join(str(v or "").lower().split())


def load_transfer_types(path: str | Path | None = None) -> dict[str, dict[str, str]]:
    """doc_type (normalized) -> {kind, label} for transfers by death, trust or inheritance."""
    raw = yaml.safe_load(Path(path or TRANSFER_TYPES_PATH).read_text(encoding="utf-8"))["transfer_types"]
    return {norm_doc_type(k): dict(v) for k, v in raw.items()}


def resolve_tenure(owner: Optional[Owner], sales: Sequence[tuple[Optional[date], Optional[str]]],
                   transfer_types: Mapping[str, Mapping[str, str]]) -> Optional[Owner]:
    """Ownership rule. `sales` is the parcel's sales_history as (sale_date, doc_type).

    If the latest dated record is a transfer by death, trust or inheritance (doc_type in
    transfer_types.yaml) and no later arm's-length sale is on the owners row, the current owner's
    tenure starts at that transfer date. The tenure before it is kept as prior_owner_years (whole
    years between the previous recorded sale and the transfer), never as the current owner's tenure."""
    if owner is None:
        return None
    dated = [(d, t) for d, t in sales if d is not None]
    if not dated:
        return owner
    last_date, last_type = max(dated, key=lambda x: (x[0], norm_doc_type(x[1]) in transfer_types))
    kind = transfer_types.get(norm_doc_type(last_type), {}).get("kind")
    if kind is None or (owner.last_sale_date is not None and owner.last_sale_date > last_date):
        return owner
    earlier = [d for d, _t in dated if d < last_date]
    if owner.last_sale_date is not None and owner.last_sale_date < last_date:
        earlier.append(owner.last_sale_date)
    prior = relativedelta(last_date, max(earlier)).years if earlier else None
    return replace(owner, last_sale_date=last_date, transfer_date=last_date, transfer_kind=kind,
                   prior_owner_years=prior)


def permit_label(approval_type: Optional[str], cfg: Mapping[str, Any]) -> str:
    labels = cfg["permit_labels"]
    if approval_type not in labels:
        raise MissingPermitLabel(f"no label in permit_labels.yaml for permit type {approval_type!r}")
    return labels[approval_type]


# ---------------------------------------------------------------------------------------
# small deterministic helpers
# ---------------------------------------------------------------------------------------
def round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def decay_factor(age_days: float, half_life_days: Optional[float]) -> float:
    """Exponential recency decay: 0.5 ** (age / half_life). Static signals (None) and
    future-dated signals (negative age) do not decay."""
    if half_life_days is None or age_days <= 0:
        return 1.0
    return 0.5 ** (age_days / half_life_days)


def stacking_multiplier(n_families: int, cfg: Mapping[str, Any]) -> float:
    st = cfg["stacking"]
    extra = max(0, n_families - 1)
    return 1.0 + min(float(st["cap"]), float(st["bonus_per_extra_family"]) * extra)


def percentile(values: Sequence[float], pct: float) -> Optional[float]:
    """Linear-interpolation percentile (same as numpy's default)."""
    vals = sorted(values)
    if not vals:
        return None
    k = (len(vals) - 1) * pct / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)


def years_owned(owner: Optional[Owner], as_of: date) -> Optional[int]:
    if owner is None or owner.last_sale_date is None:
        return None
    return max(0, relativedelta(as_of, owner.last_sale_date).years)


def fmt_date(d: Optional[date | str]) -> Optional[str]:
    if d is None:
        return None
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return f"{d:%b} {d.day}, {d.year}"


def norm_class(v: Any) -> str:
    return " ".join(str(v or "").lower().replace("_", " ").split())


# ---------------------------------------------------------------------------------------
# which signals count
# ---------------------------------------------------------------------------------------
def latest_snapshot_dates(signals: Sequence[Sig], cfg: Mapping[str, Any]) -> dict[str, date]:
    """Latest signal_date per snapshot signal type, over ALL live signals (not one parcel)."""
    out: dict[str, date] = {}
    for s in signals:
        if cfg["signals"].get(s.type, {}).get("snapshot") and s.date is not None:
            if s.type not in out or s.date > out[s.type]:
                out[s.type] = s.date
    return out


def effective_signals(signals: Sequence[Sig], cfg: Mapping[str, Any],
                      snapshot_dates: Mapping[str, date]) -> list[Sig]:
    """Signals that may score or trigger a recipe. Applies the snapshot rule (only the latest
    snapshot, so repeated rows never stack) and the permit_stalled group restriction."""
    out = []
    for s in signals:
        sc = cfg["signals"].get(s.type)
        if sc is None:
            continue
        if sc.get("snapshot") and s.date != snapshot_dates.get(s.type):
            continue
        if s.type == "permit_stalled" and s.group not in sc.get("groups", ()):
            continue
        out.append(s)
    return out


def _weight_and_halflife(s: Sig, sc: Mapping[str, Any]) -> tuple[float, Optional[float]]:
    if "by_group" in sc:
        g = sc["by_group"].get(s.group)
        return (float(g["weight"]), g.get("half_life_days")) if g else (0.0, None)
    if "by_detail" in sc:
        raw = s.details.get(sc["by_detail"])
        table = {norm_class(k): v for k, v in sc["values"].items()}
        return float(table.get(norm_class(raw), 0)), sc.get("half_life_days")
    return float(sc["weight"]), sc.get("half_life_days")


def _signal_facts(s: Sig, cfg: Mapping[str, Any]) -> dict[str, Any]:
    d = s.details or {}
    if s.type == "tax_default":
        # signal_date is the date of the notice/list the parcel appears on; recency decays from it.
        return {"tax_defaulted_on": d.get("tax_defaulted_on"), "notice": d.get("list"),
                "notice_date": str(s.date) if s.date else None}
    if s.type == "permit_approved":
        return {"permit_label": permit_label(d.get("approval_type"), cfg),
                "approval_id": d.get("approval_id"), "group": s.group,
                "issue_date": str(s.date) if s.date else None}
    if s.type == "permit_stalled":
        return {"permit_label": permit_label(d.get("approval_type"), cfg),
                "approval_id": d.get("approval_id"), "group": s.group,
                "expire_date": d.get("expire_date"), "days_past_expiry": d.get("days_past_expiry")}
    if s.type == "stro_license_removed":
        return {"license_id": d.get("license_id"), "removed_as_of": str(s.date) if s.date else None,
                "last_seen_date": d.get("last_seen_date")}
    if s.type == "stro_license_active":
        return {"license_id": d.get("license_id"), "tier": d.get("tier"),
                "snapshot_date": str(s.date) if s.date else None}
    if s.type == "sb79_transit_estimate":
        return {"distance_band": d.get("distance_band"), "nearest_mode": d.get("nearest_mode")}
    if s.type == "sb9_lot_split_estimate":
        return {"zoning": d.get("zoning"), "lot_sqft": d.get("lot_sqft")}
    if s.type == "fire_hazard_zone":
        return {"hazard_class": d.get("hazard_class")}
    return {}


def signal_components(signals: Sequence[Sig], cfg: Mapping[str, Any], as_of: date) -> list[dict[str, Any]]:
    """One component per signal key (type, plus group for permits): the strongest instance,
    which is the most recent one. `signals` must already be effective."""
    best: dict[str, dict[str, Any]] = {}
    same_day: dict[tuple, set] = {}
    for s in signals:
        if s.type in ("permit_approved", "permit_stalled"):
            d = s.details or {}
            when = str(s.date) if s.type == "permit_approved" else d.get("expire_date")
            same_day.setdefault((s.type, s.group, when, permit_label(d.get("approval_type"), cfg)),
                                set()).add(d.get("approval_id") or s.id)
    for s in sorted(signals, key=lambda x: (x.date or date.min, x.id)):
        sc = cfg["signals"][s.type]
        weight, half_life = _weight_and_halflife(s, sc)
        if weight <= 0:
            continue
        age = (as_of - s.date).days if s.date else 0
        factor = decay_factor(age, half_life)
        conf = float(s.confidence)
        comp = {
            "key": f"{s.type}:{s.group}" if s.type == "permit_approved" else s.type,
            "kind": "signal", "family": sc["family"],
            "signal_id": s.id, "signal_type": s.type, "group": s.group,
            "source_key": s.source_key, "source_record_id": s.source_record_id,
            "signal_date": str(s.date) if s.date else None,
            "confidence": float(s.confidence), "match_method": s.match_method,
            "raw_weight": weight, "half_life_days": half_life, "age_days": age,
            "decay_factor": round(factor, 6), "confidence_multiplier": conf,
            "contribution": round(weight * factor * conf, 4),
            "is_sample": bool(s.is_sample), "is_estimate": bool(s.is_estimate),
            "facts": _signal_facts(s, cfg),
        }
        if s.type in ("permit_approved", "permit_stalled"):
            f = comp["facts"]
            when = f.get("issue_date") if s.type == "permit_approved" else f.get("expire_date")
            # Several permits of one kind approved/expired the same day read as one phrase.
            f["permit_count"] = len(same_day[(s.type, s.group, when, f["permit_label"])])
        cur = best.get(comp["key"])
        if cur is None or comp["contribution"] >= cur["contribution"]:
            best[comp["key"]] = comp
    return [best[k] for k in sorted(best)]


def owner_components(owner: Optional[Owner], cfg: Mapping[str, Any], as_of: date,
                     equity_cutoff: Optional[float]) -> list[dict[str, Any]]:
    if owner is None:
        return []
    om = cfg["owner_modifiers"]
    out: list[dict[str, Any]] = []

    def add(key: str, field_name: str, weight: float, facts: dict[str, Any], estimate: bool = False):
        out.append({
            "key": key, "kind": "owner", "family": "owner", "owner_field": field_name,
            "provider": owner.provider, "as_of": str(owner.as_of) if owner.as_of else None,
            "raw_weight": float(weight), "decay_factor": 1.0, "contribution": float(weight),
            "is_sample": bool(owner.is_sample), "is_estimate": estimate, "facts": facts})

    yrs = years_owned(owner, as_of)
    if yrs is not None:
        for tier in sorted(om["years_owned"], key=lambda t: -t["min_years"]):
            if yrs >= tier["min_years"]:
                add("owner:years_owned", "last_sale_date", tier["weight"],
                    {"years_owned": yrs, "last_sale_date": str(owner.last_sale_date)})
                out[-1]["tenure_basis"] = "transfer" if owner.transfer_date else "sale"
                break
    if owner.transfer_date is not None:
        # Context only (zero points, never in reason_text): the prior owner's tenure is stored here and
        # is never described as the current owner's tenure.
        add("owner:ownership_transfer", "last_sale_date", 0,
            {"transfer_kind": owner.transfer_kind, "transfer_date": str(owner.transfer_date)})
        out[-1]["prior_owner_years"] = owner.prior_owner_years
    # out_of_state and absentee are not additive: out_of_state when true, otherwise absentee.
    if owner.out_of_state is True:
        add("owner:out_of_state", "out_of_state", om["out_of_state"]["weight"], {"out_of_state": True})
    elif owner.absentee is True:
        add("owner:absentee", "absentee", om["absentee"]["weight"], {"absentee": True})
    if owner.mortgage_open is False:
        add("owner:mortgage_open_false", "mortgage_open", om["mortgage_open_false"]["weight"],
            {"mortgage_open": False})
    if (equity_cutoff is not None and owner.est_equity is not None
            and owner.est_equity >= equity_cutoff):
        eq = om["est_equity_top_quartile"]
        add("owner:est_equity_top_quartile", "est_equity", eq["weight"],
            {"est_equity": float(owner.est_equity), "territory_cutoff": round(float(equity_cutoff), 2),
             "percentile": eq["percentile"]}, estimate=True)
    # Total owner-modifier contribution is capped; over the cap every owner component is scaled
    # by the same factor (recorded as cap_multiplier).
    total = sum(c["contribution"] for c in out)
    cap = float(om["cap"])
    scale = cap / total if total > cap else 1.0
    for c in out:
        c["cap_multiplier"] = round(scale, 6)
        c["contribution"] = round(c["raw_weight"] * scale, 4)
    return out


def compute_score(components: Sequence[Mapping[str, Any]], cfg: Mapping[str, Any]) -> dict[str, Any]:
    weighted = sum(c["contribution"] for c in components)
    families = sorted({c["family"] for c in components if c["contribution"] > 0})
    mult = stacking_multiplier(len(families), cfg)
    return {"weighted_sum": round(weighted, 4), "families": families, "multiplier": round(mult, 4),
            "score": min(100, round_half_up(weighted * mult))}


# ---------------------------------------------------------------------------------------
# recipes
# ---------------------------------------------------------------------------------------
def _owner_value(owner: Optional[Owner], name: str, as_of: date):
    if owner is None:
        return None
    return years_owned(owner, as_of) if name == "years_owned" else getattr(owner, name, None)


def eval_condition(cond: Mapping[str, Any], signals: Sequence[Sig], owner: Optional[Owner],
                   as_of: date, parcel: Optional[Mapping[str, Any]] = None) -> bool:
    if "all" in cond:
        return all(eval_condition(c, signals, owner, as_of, parcel) for c in cond["all"])
    if "any" in cond:
        return any(eval_condition(c, signals, owner, as_of, parcel) for c in cond["any"])
    if "not" in cond:
        return not eval_condition(cond["not"], signals, owner, as_of, parcel)
    if "parcel" in cond:
        # lot_vs_area_median: parcel lot_sqft divided by the median residential lot_sqft of its planning area
        lot, med = (parcel or {}).get("lot_sqft"), (parcel or {}).get("area_median_lot_sqft")
        if cond["parcel"] != "lot_vs_area_median" or not lot or not med:
            return False
        return float(lot) / float(med) >= cond["gte"]
    if "signal" in cond:
        for s in signals:
            if s.type != cond["signal"]:
                continue
            if "group" in cond and s.group != cond["group"]:
                continue
            if "within_days" in cond:
                if s.date is None or (as_of - s.date).days > cond["within_days"]:
                    continue
            if "detail" in cond and any(
                    norm_class(s.details.get(k)) not in {norm_class(v) for v in vals}
                    for k, vals in cond["detail"].items()):
                continue
            return True
        return False
    if "owner" in cond:
        val = _owner_value(owner, cond["owner"], as_of)
        if val is None:
            return False
        if "is" in cond:
            return isinstance(val, bool) and val == cond["is"]
        if "gte" in cond:
            return val >= cond["gte"]
        if "lt" in cond:
            return val < cond["lt"]
    raise ValueError(f"unknown recipe condition: {cond}")


def match_recipes(signals: Sequence[Sig], owner: Optional[Owner], cfg: Mapping[str, Any],
                  as_of: date, loaded_data: Sequence[str] = (),
                  parcel: Optional[Mapping[str, Any]] = None) -> list[str]:
    matches = []
    for name, rec in cfg["recipes"].items():
        if rec.get("active") is False:
            continue
        if any(req not in loaded_data for req in rec.get("requires_data", ())):
            continue
        if eval_condition(rec["when"], signals, owner, as_of, parcel):
            matches.append(name)
    return sorted(matches)


# ---------------------------------------------------------------------------------------
# reason text (only facts present in the components)
# ---------------------------------------------------------------------------------------
_BAND_TEXT = {"within_200ft": "within 200 ft", "within_quarter_mile": "within 1/4 mile",
              "within_half_mile": "within 1/2 mile"}
_MODE_TEXT = {"rail_station": "a rail station", "brt_stop_proxy": "a bus rapid transit stop"}


_COUNTABLE_ENDINGS = {
    "permit", "map", "approval", "agreement", "request", "certificate", "extension", "authorization",
    "modification", "nomination", "change", "adjustment", "correction", "waiver", "assessment",
    "review", "letter", "variance",
}
_KEEP_CAPITAL_FIRST = {"City", "La"}


def _flags(c: Mapping[str, Any]) -> str:
    """Sample/estimate label: one combined parenthesis, never two."""
    if c.get("is_sample") and c.get("is_estimate"):
        return f" {SAMPLE_ESTIMATE_LABEL}"
    if c.get("is_sample"):
        return f" {SAMPLE_LABEL}"
    if c.get("is_estimate"):
        return f" {ESTIMATE_LABEL}"
    return ""


def _lower_first(text: str) -> str:
    first = text.split(" ", 1)[0]
    if first in _KEEP_CAPITAL_FIRST or first.isupper() or any(ch.isdigit() for ch in first):
        return text
    return text[0].lower() + text[1:]


_PLURAL_BLOCKERS = {"to", "of", "for", "with", "and", "or", "from", "in", "by"}


def counted_permit_label(label: str, count: int) -> str:
    """'Building permit (x)' x2 -> '2 building permits (x)'. A label that cannot be pluralized safely
    (mass nouns like 'Electrical work', or phrases like 'Change to a building permit') reads
    '2 permits for electrical work'."""
    if count <= 1:
        return label
    m = re.match(r"^(.*?)(\s*\([^()]*\))?$", label)
    head, tail = m.group(1), m.group(2) or ""
    words = head.split(" ")
    if (len(words) <= 4 and "(" not in head and words[-1].lower() in _COUNTABLE_ENDINGS
            and not _PLURAL_BLOCKERS & {w.lower() for w in words}):
        words[-1] += "s"
        return f"{count} {_lower_first(' '.join(words))}{tail}"
    return f"{count} permits for {_lower_first(label)}"


def tier_text(tier: Any) -> Optional[str]:
    """'Tier 3', 'tier 3' and '3' all print as 'Tier 3' (the word Tier appears once)."""
    t = str(tier or "").strip()
    if not t:
        return None
    m = re.match(r"(?i)^tier\s*(.+)$", t)
    return f"Tier {m.group(1).strip()}"if m else f"Tier {t}"


def _whole_years(v: Any) -> int:
    return int(float(v))


def phrase(c: Mapping[str, Any], permit_count: Optional[int] = None) -> str:
    f, key = c["facts"], c["key"]
    if key == "owner:years_owned":
        n = _whole_years(f["years_owned"])
        p = f"owned {n} year{'s' if n != 1 else ''}"
    elif key == "owner:absentee":
        p = "owner is absentee"
    elif key == "owner:out_of_state":
        p = "owner is out of state"
    elif key == "owner:mortgage_open_false":
        p = "no open mortgage"
    elif key == "owner:est_equity_top_quartile":
        p = "equity in the top quarter of the territory"
    elif key.startswith("permit_approved"):
        n = permit_count or f.get("permit_count") or 1
        p = f"{counted_permit_label(f['permit_label'], n)} approved" + (
            f" {fmt_date(f['issue_date'])}" if f.get("issue_date") else "")
    elif key == "permit_stalled":
        n = permit_count or f.get("permit_count") or 1
        p = f"{counted_permit_label(f['permit_label'], n)} expired" + (
            f" {fmt_date(f['expire_date'])}" if f.get("expire_date") else "") + " with no close date"
    elif key == "tax_default":
        since = (f.get("tax_defaulted_on") or "")[:4]
        m = re.search(r"([A-Za-z]+ \d{4})\s*$", f.get("notice") or "")
        month = m.group(1) if m else (f"{date.fromisoformat(f['notice_date']):%B %Y}" if f.get("notice_date") else None)
        p = ("tax-defaulted" + (f" since {since}" if since else "")
             + f", on the {month + ' ' if month else ''}power-to-sell notice")
    elif key == "stro_license_removed":
        p = "short-term rental license removed" + (
            f" (as of {fmt_date(f['removed_as_of'])})" if f.get("removed_as_of") else "")
    elif key == "stro_license_active":
        tier = tier_text(f.get("tier"))
        p = f"holds an active {tier + ' ' if tier else ''}short-term rental license"
    elif key == "sb79_transit_estimate":
        p = (f"{_BAND_TEXT.get(f.get('distance_band'), 'near')} of "
             f"{_MODE_TEXT.get(f.get('nearest_mode'), 'a transit stop')}, "
             "which may qualify for SB 79 transit upzoning")
    elif key == "sb9_lot_split_estimate":
        p = "lot may qualify for an SB 9 split"
    elif key == "fire_hazard_zone":
        p = f"in a {norm_class(f.get('hazard_class'))} fire hazard severity zone"
    else:  # pragma: no cover - every configured key has a phrase
        raise ValueError(f"no reason phrase for component {key}")
    return p + _flags(c)


def reason_phrases(components: Sequence[Mapping[str, Any]], cfg: Mapping[str, Any]) -> list[str]:
    """The phrases of the top components. Same-day permits of one kind merge into one counted phrase
    (the count is summed across components that print identically), and a phrase is never repeated."""
    ranked = sorted((c for c in components if c["contribution"] > 0), key=lambda c: (-c["contribution"], c["key"]))
    order: list[tuple] = []
    counts: dict[tuple, int] = {}
    comp_of: dict[tuple, Mapping[str, Any]] = {}
    for c in ranked:
        f = c["facts"]
        if c["key"].startswith("permit_"):
            ident = (c["key"].split(":")[0], f["permit_label"], f.get("issue_date") or f.get("expire_date"),
                     bool(c.get("is_sample")), bool(c.get("is_estimate")))
            counts[ident] = counts.get(ident, 0) + (f.get("permit_count") or 1)
        else:
            ident = ("phrase", phrase(c))
            counts.setdefault(ident, 1)
        if ident not in comp_of:
            comp_of[ident] = c
            order.append(ident)
    out: list[str] = []
    for ident in order:
        text = phrase(comp_of[ident], counts[ident]) if ident[0].startswith("permit_") else ident[1]
        if text not in out:
            out.append(text)
    return out[: cfg["reason_text"]["max_components"]]


def reason_text(components: Sequence[Mapping[str, Any]], cfg: Mapping[str, Any]) -> str:
    phrases = reason_phrases(components, cfg)
    if not phrases:
        return "No scoring signals on file."
    text = ", ".join(phrases)
    return text[0].upper() + text[1:] + "."


# ---------------------------------------------------------------------------------------
# one parcel
# ---------------------------------------------------------------------------------------
def score_parcel(signals: Sequence[Sig], owner: Optional[Owner], cfg: Mapping[str, Any], as_of: date,
                 snapshot_dates: Mapping[str, date], equity_cutoff: Optional[float],
                 loaded_data: Sequence[str] = (),
                 parcel: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    eff = effective_signals(signals, cfg, snapshot_dates)
    comps = signal_components(eff, cfg, as_of) + owner_components(owner, cfg, as_of, equity_cutoff)
    res = compute_score(comps, cfg)
    return {
        "score": res["score"], "weighted_sum": res["weighted_sum"], "multiplier": res["multiplier"],
        "families": res["families"], "components": comps,
        "recipe_matches": match_recipes(eff, owner, cfg, as_of, loaded_data, parcel),
        "uses_sample_data": any(c["is_sample"] for c in comps),
        "reason_text": reason_text(comps, cfg), "model_version": cfg["model_version"],
    }
