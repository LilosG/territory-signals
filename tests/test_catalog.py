"""export_catalog: the single source of truth for names (dashboard reads only catalog.generated.json)."""
import json
import re
from datetime import date

import yaml

from territory import export_catalog as ec
from territory.config import load_client
from territory.export_catalog import build_catalog, component_specs, load_signal_labels, write_catalog
from territory.scoring_engine import Owner, load_scoring_config
from test_scoring_engine import rich_parcel

CFG = load_scoring_config()
CLIENT = load_client("kaiser-team")
CAT = build_catalog(CLIENT)
ROOT = ec.ROOT

PROPER = {"City", "La", "Jolla", "Shores", "Council", "Manager", "Mills", "Act"}


def sentence_case(label):
    words = re.sub(r"\([^)]*\)", lambda m: m.group(0), label).replace("(", " ( ").replace(")", " ) ").split()
    words = [w for w in words if w not in "()"]
    if not words or not words[0][0].isupper():
        return False
    for w in words[1:]:
        w = w.strip(",;/")
        if not w or not w[0].isalpha() or not w[0].isupper():
            continue
        if w.isupper() or any(ch.isdigit() for ch in w) or w in PROPER or w == "I":
            continue
        return False
    return "-" not in "".join(re.findall(r"[a-z]-[A-Z]", label))


def all_labels(cat):
    for section in ("signal_types", "signal_groups", "permit_types", "recipes", "components", "stages", "score_bands"):
        for item in cat[section]:
            yield section, item["key"], item["label"]
    for c in cat["components"]:
        yield "families", c["family"], c["family_label"]


def test_catalog_contents_and_counts():
    assert CAT["model_version"] == CFG["model_version"] == "v0.3-handset"
    assert CAT["client_id"] == "kaiser-team"
    assert {t["key"] for t in CAT["signal_types"]} == set(CFG["signals"]) | {"ownership_transfer"}
    assert len(CAT["permit_types"]) == len(CFG["permit_labels"]) == 147
    assert [r["key"] for r in CAT["recipes"]] == list(CFG["recipes"])
    assert len(CAT["recipes"]) == 9 and sum(r["enabled"] for r in CAT["recipes"]) == 8
    assert [s["key"] for s in CAT["stages"]] == ["signal", "contacted", "conversation", "appointment", "listing",
                                                 "not_interested", "bad_data"]


def test_every_signal_type_and_group_has_a_label():
    labels = load_signal_labels()
    assert set(CFG["signals"]) <= set(labels["signal_types"])
    pmap = yaml.safe_load((ROOT / "config" / "permit_signal_map.yaml").read_text())
    groups = {v for v in json.dumps(pmap).replace('"', " ").split() if v in labels["signal_groups"]}
    assert {"pre_sale_prep", "demolition_lot_split", "adu", "remodel_addition", "solar_energy", "other"} <= {
        g["key"] for g in CAT["signal_groups"]}
    # groups written by the adapters (stro, distress, upzoning, risk) and every permit group in scoring.yaml
    assert {"stro", "distress", "upzoning", "risk"} <= {g["key"] for g in CAT["signal_groups"]}
    assert set(CFG["signals"]["permit_approved"]["by_group"]) <= {g["key"] for g in CAT["signal_groups"]}
    assert groups                                                       # the permit map names groups we can label


def test_every_component_the_scorer_can_write_is_in_the_catalog():
    keys = {c["key"] for c in CAT["components"]}
    r = rich_parcel()
    assert {c["key"] for c in r["components"]} <= keys
    assert {c["key"] for c in component_specs(CFG)} == keys
    from territory.scoring_engine import owner_components, resolve_tenure
    o = resolve_tenure(Owner(last_sale_date=date(1990, 1, 1), absentee=True, out_of_state=True, mortgage_open=False,
                             est_equity=10.0), [(date(2010, 1, 1), "trust transfer deed")], CFG["transfer_types"])
    assert {c["key"] for c in owner_components(o, CFG, date(2026, 11, 18), 1.0)} <= keys


def test_component_labels_and_max_points():
    by = {c["key"]: c for c in CAT["components"]}
    assert by["tax_default"]["max_points"] == 30 and by["tax_default"]["family"] == "financial"
    assert by["permit_approved:pre_sale_prep"]["max_points"] == 20
    assert by["sb79_transit_estimate"]["max_points"] == 14 and by["fire_hazard_zone"]["max_points"] == 10
    assert by["owner:years_owned"]["max_points"] == 15 and by["owner:out_of_state"]["max_points"] == 12
    assert by["owner:ownership_transfer"]["max_points"] == 0
    assert "permit_approved:other" not in by                             # weight 0: never scores
    assert CAT["owner_modifier_cap"] == 30
    assert by["sb9_lot_split_estimate"]["label"] == "SB 9 lot-split eligibility (estimated)"
    assert by["permit_approved:adu"]["label"] == "ADU permit approved"


def test_recipes_carry_label_description_and_enabled_flag():
    by = {r["key"]: r for r in CAT["recipes"]}
    assert by["quiet_inheritance"]["enabled"] is False
    assert by["insurance_squeeze"]["enabled"] is True and by["insurance_squeeze"]["requires_data"] == ["fire_zones"]
    assert by["builder_bait"]["label"] == "Builder bait" and by["str_exit"]["label"] == "Short-term rental exit"
    assert all(r["short_description"] and r["label"] for r in CAT["recipes"])
    assert {k for k, r in by.items() if r["enabled"]} == set(CLIENT.enabled_recipes())


def test_score_band_thresholds():
    assert [(b["key"], b["min"]) for b in CAT["score_bands"]] == [("hot", 80), ("warm", 60), ("watch", 40), ("low", 0)]


def test_all_labels_are_sentence_case_with_acronyms_kept():
    bad = [(s, k, l) for s, k, l in all_labels(CAT) if not sentence_case(l)]
    assert bad == []
    labels = {l for _s, _k, l in all_labels(CAT)}
    assert {"ADU permit approved", "SB 9 lot-split eligibility (estimated)", "SB 79 transit eligibility (estimated)",
            "Active STR license", "STR license removed"} <= labels
    assert not any(re.search(r"\b(Sb|Adu|Str)\b", l) for l in labels)         # acronyms are never lower-cased


def test_sentence_case_checker_rejects_title_case():
    assert not sentence_case("Permit Approved") and not sentence_case("short label") and sentence_case("ADU permit")


def test_labels_are_never_empty_or_duplicated_within_a_section():
    for section in ("signal_types", "signal_groups", "recipes", "components"):
        labels = [i["label"] for i in CAT[section]]
        assert all(labels) and len(labels) == len(set(labels)), section


def test_catalog_is_deterministic_and_the_committed_file_is_current(tmp_path):
    out = write_catalog(CLIENT, tmp_path / "catalog.generated.json")
    assert json.loads(out.read_text()) == CAT == build_catalog(CLIENT)
    committed = ROOT / "dashboard" / "src" / "data" / "catalog.generated.json"
    assert committed.exists(), "run: cd pipelines && python -m territory.export_catalog"
    assert json.loads(committed.read_text()) == CAT, "catalog.generated.json is stale: re-run export_catalog"
    assert committed.read_text().endswith("}\n")


def test_missing_label_fails_loudly():
    import pytest
    labels = load_signal_labels()
    labels["components"].pop("tax_default")
    with pytest.raises(KeyError, match="components.tax_default"):
        build_catalog(CLIENT, labels=labels)


def test_adapter_signal_types_and_groups_in_the_database_are_all_labeled(db, tmp_path):
    """After the adapter fixtures run (test_data_rules does the same), every signal_type/group is in the catalog."""
    import pandas as pd
    from helpers import FIXTURES, add_parcel, run
    from test_dev_permits import MAP, _setup as setup_permits
    from test_tax_default import PDF
    setup_permits(db)
    df = pd.read_csv(FIXTURES / "stro_licenses_fixture.csv", dtype=str)
    for i, r in enumerate(df.itertuples()):
        if r.license_id != "STR-OUTSIDE":
            add_parcel(db, f"{3100000000 + i}", float(r.longitude), float(r.latitude))
    for i, apn in enumerate(["3461201100", "3500701802", "3504004715"]):
        add_parcel(db, apn, -117.21 + i * 0.001, 32.80)
    runs = [run("stro_licenses", local_files={"stro_licenses": FIXTURES / "stro_licenses_fixture.csv"},
                report_dir=tmp_path),
            run("dev_permits", local_files={"dev_permits": [FIXTURES / "approvals_issued_fixture.csv"],
                                            "permit_signal_map": MAP}, report_dir=tmp_path),
            run("tax_default", local_files={"tax_default": PDF}, report_dir=tmp_path)]
    assert all(r.status == "success" for r in runs)
    types = {k["key"] for k in CAT["signal_types"]}
    groups = {g["key"] for g in CAT["signal_groups"]}
    for t, g in db.execute("select distinct signal_type, signal_group from signals"):
        assert t in types and g in groups, (t, g)
