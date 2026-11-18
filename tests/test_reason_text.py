"""Phase 5A reason-text rules: no repeated phrase, same-day permits merge, tier prints once,
(sample data, estimated), whole-number years."""
import re
from datetime import date, timedelta


from territory.scoring_engine import (
    Owner, Sig, counted_permit_label, load_scoring_config, phrase, reason_text, score_parcel, tier_text,
    latest_snapshot_dates,
)

CFG = load_scoring_config()
AS_OF = date(2026, 11, 18)
_n = 0


def sig(type_, group="other", on=None, details=None, sample=False, estimate=False, approval_type="Building Permit",
        approval_id=None):
    global _n
    _n += 1
    details = dict(details or {})
    if type_.startswith("permit"):
        details.setdefault("approval_type", approval_type)
        details.setdefault("approval_id", approval_id or f"A{_n}")
    return Sig(f"s{_n}", type_, group, on or AS_OF - timedelta(days=2), "test", f"r{_n}", 1.0, "apn",
               estimate, sample, details)


def run(signals, owner=None):
    return score_parcel(signals, owner, CFG, AS_OF, latest_snapshot_dates(signals, CFG), None)


def test_same_day_permits_merge_into_one_phrase():
    cfg = dict(CFG, permit_labels={**CFG["permit_labels"], "Plain Building": "Building permit"})
    day = date(2026, 11, 16)
    sigs = [sig("permit_approved", "remodel_addition", day, approval_type="Plain Building") for _ in range(2)]
    r = score_parcel(sigs, None, cfg, AS_OF, {}, None)
    assert r["reason_text"] == "2 building permits approved Nov 16, 2026."


def test_same_day_permits_merge_with_the_real_label():
    day = date(2026, 11, 16)
    r = run([sig("permit_approved", "remodel_addition", day), sig("permit_approved", "remodel_addition", day),
             sig("permit_approved", "remodel_addition", day)])
    assert r["reason_text"] == ("3 building permits (remodel, addition or new construction) "
                                "approved Nov 16, 2026.")


def test_different_days_do_not_merge():
    r = run([sig("permit_approved", "remodel_addition", date(2026, 11, 16)),
             sig("permit_approved", "remodel_addition", date(2026, 11, 10))])
    assert r["reason_text"].count("approved") == 1 and "2 " not in r["reason_text"]   # one component per key


def test_same_day_permits_in_different_groups_merge_into_one_phrase():
    day = date(2026, 11, 16)
    r = run([sig("permit_approved", "remodel_addition", day), sig("permit_approved", "adu", day)])
    assert r["reason_text"] == ("2 building permits (remodel, addition or new construction) "
                                "approved Nov 16, 2026.")


def test_mass_noun_labels_count_without_a_broken_plural():
    assert counted_permit_label("Electrical work", 2) == "2 permits for electrical work"
    assert counted_permit_label("Electrical work (commercial or multifamily)", 3) == (
        "3 permits for electrical work (commercial or multifamily)")
    assert counted_permit_label("Building permit", 1) == "Building permit"
    assert counted_permit_label("City Council approval", 2) == "2 City Council approvals"
    for label in CFG["permit_labels"].values():                                  # every real label pluralizes to something readable
        out = counted_permit_label(label, 2)
        assert out.startswith("2 ") and "  " not in out and "None" not in out


def test_a_phrase_is_never_repeated():
    r = run([sig("permit_approved", "remodel_addition", date(2026, 11, 16)),
             sig("permit_approved", "adu", date(2026, 11, 16)),
             sig("permit_stalled", "adu", date(2026, 11, 16), details={"expire_date": "2026-01-10"})],
            Owner(last_sale_date=date(1990, 1, 1), absentee=True, mortgage_open=False, is_sample=True))
    parts = [p.strip() for p in re.split(r", (?=[a-z0-9])", r["reason_text"].rstrip("."))]
    assert len(parts) == len({p.lower() for p in parts})
    assert r["reason_text"].lower().count("building permit") <= 2


def test_tier_value_prints_once():
    for raw in ("Tier 3", "tier 3", "3", " Tier 3 "):
        assert tier_text(raw) == "Tier 3"
    c = run([sig("stro_license_active", "stro", details={"tier": "Tier 3"})])["components"][0]
    assert phrase(c) == "holds an active Tier 3 short-term rental license"
    assert phrase(c).lower().count("tier") == 1
    c = run([sig("stro_license_active", "stro", details={"tier": "2"})])["components"][0]
    assert phrase(c) == "holds an active Tier 2 short-term rental license"
    c = run([sig("stro_license_active", "stro", details={})])["components"][0]
    assert phrase(c) == "holds an active short-term rental license"


def test_sample_and_estimated_reads_as_one_label():
    comps = run([sig("sb9_lot_split_estimate", "upzoning", estimate=True, sample=True)])["components"]
    assert phrase(comps[0]) == "lot may qualify for an SB 9 split (sample data, estimated)"
    only_est = run([sig("sb9_lot_split_estimate", "upzoning", estimate=True)])["components"][0]
    assert phrase(only_est) == "lot may qualify for an SB 9 split (estimated)"
    only_sample = run([sig("tax_default", "distress", details={"tax_defaulted_on": "2021-06-30"}, sample=True)]
                      )["components"][0]
    assert phrase(only_sample).endswith("(sample data)") and "estimated" not in phrase(only_sample)
    # the est_equity owner component is both sample and estimated
    owner = Owner(last_sale_date=date(2000, 1, 1), est_equity=5_000_000.0, is_sample=True)
    r = score_parcel([], owner, CFG, AS_OF, {}, 1_000_000.0)
    eq = next(c for c in r["components"] if c["key"] == "owner:est_equity_top_quartile")
    assert phrase(eq) == "equity in the top quarter of the territory (sample data, estimated)"


def test_years_are_whole_numbers():
    for last in (date(2005, 5, 1), date(2005, 11, 19), date(1996, 11, 18)):
        r = run([], Owner(last_sale_date=last, is_sample=False))
        text = r["reason_text"]
        assert re.search(r"(?i)owned \d+ years?(?!\.\d)", text) and not re.search(r"\d+\.\d+", text)
    c = run([], Owner(last_sale_date=date(2005, 5, 1)))["components"][0]
    assert phrase(c) == "owned 21 years"
    c["facts"] = dict(c["facts"], years_owned=21.0)                  # even a float prints as a whole number
    assert phrase(c) == "owned 21 years"
    c["facts"] = dict(c["facts"], years_owned=1)
    assert phrase(c) == "owned 1 year"


def test_reason_text_is_unchanged_for_plain_cases():
    r = run([sig("tax_default", "distress", details={"tax_defaulted_on": "2021-06-30", "list": "June 2026"},
                 on=date(2026, 7, 1))])
    assert reason_text(r["components"], CFG) == "Tax-defaulted since 2021, on the June 2026 power-to-sell notice."
