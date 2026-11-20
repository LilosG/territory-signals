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


class PermitScope(_Strict):
    """Which permits permit_intent classifies: issued in the last `months` OR on a parcel scoring >= `min_lead_score`."""
    months: int = Field(ge=1)
    min_lead_score: int = Field(ge=0, le=100)


class LlmTask(_Strict):
    model: str | None = None            # overrides llm.model for this task
    fallback_model: str | None = None   # called when the model's reply is still rejected after one retry (Phase 5G)
    scope: PermitScope | None = None    # permit_intent only


class LlmConfig(_Strict):
    """Per-client AI provider (D13). Client data goes to this provider, so it is chosen per client."""
    provider: Literal["openai_compatible", "anthropic", "fake"]
    base_url: str | None = None
    api_key_env: str = "LLM_API_KEY"
    model: str = Field(min_length=1)
    tasks: dict[str, LlmTask] = Field(default_factory=dict)
    monthly_budget_usd: float = Field(ge=0)
    enabled: bool = True

    def model_for(self, task: str) -> str:
        t = self.tasks.get(task)
        return (t.model if t and t.model else self.model)

    def fallback_model_for(self, task: str) -> str | None:
        t = self.tasks.get(task)
        return t.fallback_model if t and t.fallback_model else None


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
    llm: LlmConfig | None = None

    def enabled_recipes(self) -> list[str]:
        return [k for k, v in self.recipes.items() if v.enabled]


def load_config(path: str | Path) -> ClientConfig:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return ClientConfig.model_validate(data)


def load_client(client_id: str) -> ClientConfig:
    return load_config(CLIENTS_DIR / f"{client_id}.yaml")
