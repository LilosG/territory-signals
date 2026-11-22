"""Phase 5G (D14): the electrical / plumbing / mechanical types are only pre_sale_prep CANDIDATES; the permit's
text decides. Every description below is a real permit description from the San Diego data."""
from datetime import date

import pytest

from territory import permit_rules as rules

MAP = rules.load_map()
RULES = MAP["presale_rules"]
COMBO = "No-Plan - Residential - Combination Mech/Elec/Plum"


def group(text, atype=COMBO, **extra):
    payload = {"APPROVAL_TYPE": atype, "APPROVAL_SCOPE": text, "APPROVAL_ISSUE_DATE": "2026-09-14", **extra}
    out = rules.derive(payload, "1", MAP["approval_types"], date(2026, 11, 19), True,
                       MAP["residential_remodel_types"], RULES)
    return out[0]["group"]


# ---- maintenance: like-for-like systems work (includes the permit-intent-agreement disagreements) ----------
MAINTENANCE = [
    ("Mechanical Permit", "SFR ReplaceFurnace and add all Duct Work with Electrical"),
    ("Electrical Pmt", "OVERHEAD TO UNDERGROUND"),
    ("Electrical Pmt", "OH TO UG CONV. PROG."),
    ("Mechanical Permit", "Mechanical permit change out heat pump 2 ton at a SDU"),
    ("Electrical Permit", "underground utility district. 100 amp. rvf"),
    (COMBO, "1. x2 3 ton heat pump 2. x2 3 ton upflow air handler"),
    (COMBO, "DUCT WORK ONLY"),
    ("Plumbing Permit ", "REPLACE TANKLESS WATER HEATER SFD"),
    (COMBO, "FAU CHANGE OUT."),
    (COMBO, "Drains repipe"),
    (COMBO, "Main Panel Upgrade 200A"),
    ("Mechanical Permit", "E-Permit Condo Replace The Sewer LIne"),
    (COMBO, "40 Gallon natural gas water heater replacement like for like"),
    (COMBO, "SINGLE ZONE MINI SPLIT ADD ON"),
    (COMBO, "Install new A/C system connected to existing ducted furnace, upgrade main electrical panel to 200 amps"),
    # a bathroom word does not make a repipe or a drain job cosmetic
    (COMBO, "Master bathroom drain repipe"),
    (COMBO, "CAST IRON CRAWLSPACE REPIPE FOR 2 BATHROOMS & KITCHEN & PERMA LINE MAINLINE 20FT 2\"ABS 10FT 3\"ABS"),
    (COMBO, "Install new Schedule 40 ABS drain piping from the main line back to the toilet, vanity, and shower.(approx 10 feet)"),
    (COMBO, "Replace zinsco electrical panel with new modern type, zero load additions"),
    (COMBO, "Apt Replace Wall Floor Furance"),
    (COMBO, "REPLACE WALL/FLOOR FURNACE"),
    ("Plumbing Pmt", "E-permit Plumbing 5410 LA JOLLA BL Building \"A\"   Remove (66) existing deck drains and replace with new."),
    (COMBO, "Replacement of roof-top mechanical equipment and associated screen."),
    (COMBO, "Installation of a 24kW generator on a prefabricated concrete pad and an automatic transfer switch"),
    (COMBO, ""),                                                    # no text, no scope
    ("Electrical Pmt", ""),
]


@pytest.mark.parametrize("atype,text", MAINTENANCE)
def test_systems_replacement_is_maintenance(atype, text):
    assert group(text, atype) == "maintenance"


# ---- pre_sale_prep: cosmetic or remodel scope ---------------------------------------------------------------
PREP = [
    ("Plumbing Permit ", "For plumbing work associated with the bathroom remodel to an existing MDU."),
    ("Electrical Pmt", "Electrical work associated with a proposed interior remodel on the third floor of an existing MDU."),
    ("Plumbing Permit ", "Interior remodeling*****epermit***1882"),
    (COMBO, "bathroom and kitchen remodel."),
    (COMBO, "REMODEL OF EXISTING HOME. UPDATE TO MECHANICAL, ELECTRICAL, AND PLUMBING SYSTEMS"),
    (COMBO, "Like-in-kind remodel. Electrical, Plumbing, Drywall replacement, through entire home."),
    (COMBO, "Re-Roof in Kind,Replace Windows in Kind,Insulation from exterior \"Plywood\" Extend Stucco 455 Linear Sq Ft"),
    (COMBO, "Minor Renovation works - Kitchen cabinet and floor tiles replacement, bathroom tiles replacement"),
    (COMBO, "Bathroom remodel, tub to curbless walk in shower. update plumbing and electrical."),
    ("Plumbing Pmt", "ELEC AND PLBG REMODEL KITCHEN"),
    ("Electrical Permit", "Electrical Permit for Addition to existing SDU and existing DUP to create 3-story MDU."),
    (COMBO, "Change Ex.Picture  Window to Sliding glass door in same opening"),
    (COMBO, "Removal and replacement of existing shower pan and tile surround due to water leak. Includes subfloor repairs"),
    ("Mechanical Permit", "For mechanical work associated with proposed interior remodel & replacement of garage door & exterior window."),
]


@pytest.mark.parametrize("atype,text", PREP)
def test_cosmetic_or_remodel_scope_stays_pre_sale_prep(atype, text):
    assert group(text, atype) == "pre_sale_prep"


def test_combined_mep_permit_inherits_the_project_text_when_it_has_none():
    assert group("", COMBO, PROJECT_TITLE="Chalcedony St Remod Unit 3",
                 PROJECT_SCOPE="PACIFIC BEACH; Building, Electrical, Mechanical, Plumbing permits to add new bath") == "pre_sale_prep"
    assert group("", COMBO, PROJECT_TITLE="Epermit plumbing",
                 PROJECT_SCOPE="Epermit plumbing --- Replace water heater like for like same location") == "maintenance"


# ---- other types of work filed under the same permit types -----------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("Mechanical work associated with interior tenant improvement to existing 4-story office building (suite 206).", "other"),
    ("Plumbing work associated with the proposed interior remodel to accommodate an ice cream shop.", "other"),
    ("For electrical work associated with the replacement of (2) (E) canopy structures to an (E) gas station.", "other"),
    ("Electrical work associated with removal of 6 panel antennas, RRUS, TMAS, power cabinets, batteries.", "other"),
    ("Associated electrical work for the proposed new three-story 3-unit MDU with (3) attached garages. Work to include decks.", "other"),
    ("For installation of 6.8 KW roof mounted photovoltaic system with a battery at existing MDU.", "solar_energy"),
    ("Residential Roof-Mounted Solar: System Size: 5.475 kW/DC, 3.8 kW/AC, 15 Mods, 1 Inverter. New Main Panel Service.", "solar_energy"),
    ("Electrical permit for installation of (2) Tesla Powerwall 2 batteries and (1) Tesla Backup Gateway", "solar_energy"),
    ("We will be replacing the old electrical panel with a new 200AMP Solar-Rated panel.", "maintenance"),
])
def test_non_residential_new_construction_and_solar_are_not_pre_sale_prep(text, expected):
    assert group(text, "Electrical Pmt") == expected


# ---- the type is a precondition, and nothing else changes ------------------------------------------------------
def test_only_the_pre_sale_prep_types_are_refined():
    assert group("Kitchen remodel", "Building Permit") == "remodel_addition"
    assert group("Replace furnace", "Building Permit") == "remodel_addition"
    assert group("Replace furnace", "Traffic Control Permit") == "other"
    assert group("Replace furnace", "Photovoltaic - SB 379") == "solar_energy"


def test_without_rules_the_bare_type_still_decides():
    assert rules.group_for(COMBO, 0, MAP["approval_types"]) == "pre_sale_prep"


def test_maintenance_is_a_known_group_with_no_weight():
    import yaml
    cfg = yaml.safe_load((rules.MAP_PATH.parent / "scoring.yaml").read_text())
    assert "maintenance" in rules.SIGNAL_GROUPS
    assert cfg["signals"]["permit_approved"]["by_group"]["maintenance"]["weight"] == 0
    assert cfg["model_version"] == "v0.7-attom"


# ---- v0.4.1: MEP permits for ADU work are ADU permits (same weight as other ADU permits) ---------------------
ADU_TEXTS = [
    # the real 1505 Felspar St permits
    ("Mechanical Pmt", "***SCOPE CHANGE_04/10/2026***- Mechanical work associated with the proposed conversion of existing storages and garages into (5) new attached ADUs at a lot with an existing detached MDU building."),
    ("Electrical Pmt", "***SCOPE CHANGE_04/10/2026***- Electrical work associated with the proposed conversion of existing storages and garages into (5) new attached ADUs at a lot with an existing detached MDU building."),
    ("Plumbing Pmt", "***SCOPE CHANGE_04/10/2026***- Plumbing work associated with the proposed conversion of existing storages and garages into (5) new attached ADUs at a lot with an existing detached MDU building."),
    (COMBO, "Electrical and plumbing for a new accessory dwelling unit in the backyard"),
    (COMBO, "JADU conversion of existing bedroom"),
    ("Mechanical Permit", "Mechanical for conversion of garage into 2 units"),
    ("Electrical Pmt", "Electrical work for new detached rear units"),
]


@pytest.mark.parametrize("atype,text", ADU_TEXTS)
def test_mep_permit_for_adu_work_goes_to_adu(atype, text):
    assert group(text, atype) == "adu"


def test_adu_rule_does_not_catch_other_scopes():
    assert group("Replace furnace and ducts", "Mechanical Permit") == "maintenance"
    assert group("Kitchen remodel with new plumbing", "Plumbing Permit ") == "pre_sale_prep"
    assert group("Garage conversion to family room", COMBO) == "pre_sale_prep"
    assert group("Tenant improvement conversion into 3 office units", COMBO) == "other"


def test_adu_group_weight_is_the_same_for_every_adu_permit():
    import yaml
    cfg = yaml.safe_load((rules.MAP_PATH.parent / "scoring.yaml").read_text())
    assert cfg["signals"]["permit_approved"]["by_group"]["adu"]["weight"] == 18
