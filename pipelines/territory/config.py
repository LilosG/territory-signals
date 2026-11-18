"""Per-client configuration: loads and validates config/clients/<client_id>.yaml."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

CLIENTS_DIR = Path(__file__).resolve().parents[2] / "config" / "clients"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Territory(_Strict):
    planning_areas: list[str] = Field(min_length=1)
    zips: list[str] = Field(min_length=1)
    neighborhoods: list[str] = Field(min_length=1)


class Outreach(_Strict):
    # Only "preview" exists: drafts are written to the database and nothing is ever sent.
    mode: Literal["preview"]
    weekly_send_cap_per_agent: int = Field(ge=0)
    drafts_per_run: int = Field(ge=1)
    cooldown_days: int = Field(ge=0)
    approval_required_recipes: list[str] = Field(default_factory=list)


class TeamMember(_Strict):
    name: str = Field(min_length=1)
    email: str = Field(min_length=3)
    role: Literal["owner", "agent", "assistant"]
    # D11: required before outreach can be approved. May be blank in config; the draft is then blocked.
    dre_license: str = ""
    phone: str = ""


class TeamProfile(_Strict):
    display_name: str = Field(min_length=1)
    brokerage: str = ""
    office_address: str = ""


class RecipeToggle(_Strict):
    enabled: bool


class ClientConfig(_Strict):
    client_id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    display_name: str = Field(min_length=1)
    territory: Territory
    owner_data_provider: Literal["sample", "attom"]
    outreach: Outreach
    team_members: list[TeamMember] = Field(default_factory=list)
    team_profile: TeamProfile
    recipes: dict[str, RecipeToggle]

    def enabled_recipes(self) -> list[str]:
        return [k for k, v in self.recipes.items() if v.enabled]


def load_config(path: str | Path) -> ClientConfig:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return ClientConfig.model_validate(data)


def load_client(client_id: str) -> ClientConfig:
    return load_config(CLIENTS_DIR / f"{client_id}.yaml")
