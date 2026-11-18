import pytest
from pydantic import ValidationError

from territory.config import CLIENTS_DIR, ClientConfig, load_client, load_config
from territory.scoring_engine import load_scoring_config


def test_kaiser_team_loads():
    cfg = load_client("kaiser-team")
    assert cfg.client_id == "kaiser-team"
    assert cfg.territory.zips == ["92037", "92109"]
    assert cfg.owner_data_provider == "sample"
    assert cfg.outreach.mode == "preview"
    assert cfg.team_members == []                       # empty until Mike supplies agents and DRE numbers


def test_phase5_client_settings():
    cfg = load_client("kaiser-team")
    assert cfg.team_profile.display_name == "The Kaiser Team"
    assert cfg.team_profile.brokerage == "" and cfg.team_profile.office_address == ""
    o = cfg.outreach
    assert (o.weekly_send_cap_per_agent, o.drafts_per_run, o.cooldown_days) == (25, 50, 90)
    assert o.approval_required_recipes == ["quiet_inheritance", "financial_pressure", "insurance_squeeze"]
    enabled = {k for k, v in cfg.recipes.items() if v.enabled}
    assert set(cfg.recipes) - enabled == {"quiet_inheritance"}           # the only disabled recipe
    assert cfg.recipes["insurance_squeeze"].enabled                      # enabled, idle until fire zones load
    assert cfg.enabled_recipes() == [k for k in cfg.recipes if k != "quiet_inheritance"]


def test_recipe_keys_match_scoring_yaml():
    cfg = load_client("kaiser-team")
    scoring = set(load_scoring_config()["recipes"])
    assert set(cfg.recipes) == scoring
    assert set(cfg.outreach.approval_required_recipes) <= scoring


def test_team_members_accepts_entries_and_empty():
    data = load_config(CLIENTS_DIR / "kaiser-team.yaml").model_dump()
    assert ClientConfig.model_validate(data).team_members == []
    data["team_members"] = [
        {"name": "Test Agent", "email": "agent@example.test", "role": "agent",
         "dre_license": "01234567", "phone": "(619) 555-0100"},
        {"name": "Test Assistant", "email": "asst@example.test", "role": "assistant"},    # license/phone optional
    ]
    cfg = ClientConfig.model_validate(data)
    assert [m.role for m in cfg.team_members] == ["agent", "assistant"]
    assert cfg.team_members[1].dre_license == ""
    data["team_members"][0]["role"] = "janitor"
    with pytest.raises(ValidationError):
        ClientConfig.model_validate(data)


def test_empty_team_profile_strings_allowed():
    data = load_config(CLIENTS_DIR / "kaiser-team.yaml").model_dump()
    data["team_profile"] = {"display_name": "X", "brokerage": "", "office_address": ""}
    assert ClientConfig.model_validate(data).team_profile.office_address == ""


def test_invalid_config_fails(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "client_id: Bad ID\ndisplay_name: X\nterritory: {planning_areas: [], zips: [], neighborhoods: []}\n"
        "owner_data_provider: nope\noutreach: {mode: send}\n"
    )
    with pytest.raises(ValidationError):
        load_config(bad)


def test_only_preview_mode_exists():
    data = load_config(CLIENTS_DIR / "kaiser-team.yaml").model_dump()
    data["outreach"]["mode"] = "send"
    with pytest.raises(ValidationError):
        ClientConfig.model_validate(data)


def test_unknown_field_rejected():
    data = load_config(CLIENTS_DIR / "kaiser-team.yaml").model_dump()
    data["surprise"] = 1
    with pytest.raises(ValidationError):
        ClientConfig.model_validate(data)
