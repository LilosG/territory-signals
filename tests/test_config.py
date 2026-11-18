import pytest
from pydantic import ValidationError

from territory.config import CLIENTS_DIR, ClientConfig, load_client, load_config


def test_kaiser_team_loads():
    cfg = load_client("kaiser-team")
    assert cfg.client_id == "kaiser-team"
    assert cfg.territory.zips == ["92037", "92109"]
    assert cfg.owner_data_provider == "sample"
    assert cfg.outreach.mode == "preview"
    assert cfg.team_members == []


def test_invalid_config_fails(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "client_id: Bad ID\ndisplay_name: X\nterritory: {planning_areas: [], zips: [], neighborhoods: []}\n"
        "owner_data_provider: nope\noutreach: {mode: send}\n"
    )
    with pytest.raises(ValidationError):
        load_config(bad)


def test_unknown_field_rejected():
    data = load_config(CLIENTS_DIR / "kaiser-team.yaml").model_dump()
    data["surprise"] = 1
    with pytest.raises(ValidationError):
        ClientConfig.model_validate(data)
