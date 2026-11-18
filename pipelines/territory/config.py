"""Per-client configuration: loads and validates config/clients/<client_id>.yaml."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

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
    # Only "preview" exists until Phase 5 approval work defines more modes.
    mode: Literal["preview"]


class ClientConfig(_Strict):
    client_id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    display_name: str = Field(min_length=1)
    territory: Territory
    owner_data_provider: Literal["sample", "attom"]
    outreach: Outreach
    team_members: list[dict[str, Any]] = Field(default_factory=list)


def load_config(path: str | Path) -> ClientConfig:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return ClientConfig.model_validate(data)


def load_client(client_id: str) -> ClientConfig:
    return load_config(CLIENTS_DIR / f"{client_id}.yaml")
