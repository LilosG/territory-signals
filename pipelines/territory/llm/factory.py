"""Build the provider a client config names. Returns (provider, None) or (None, reason) when AI must skip cleanly."""
from __future__ import annotations

import os

from territory.config import ClientConfig
from territory.llm.base import Provider


def get_provider(client: ClientConfig, env=None) -> tuple[Provider | None, str | None]:
    cfg = client.llm
    env = os.environ if env is None else env
    if cfg is None:
        return None, "no llm section in the client config"
    if not cfg.enabled:
        return None, "llm.enabled is false"
    if cfg.provider == "fake":
        from territory.llm.fake import FakeProvider
        return FakeProvider(model=cfg.model), None
    key = env.get(cfg.api_key_env)
    if not key:
        return None, f"environment variable {cfg.api_key_env} is not set"
    if cfg.provider == "openai_compatible":
        if not cfg.base_url:
            return None, "llm.base_url is required for openai_compatible"
        from territory.llm.openai_compatible import OpenAICompatibleProvider
        return OpenAICompatibleProvider(cfg.base_url, key, cfg.model), None
    from territory.llm.anthropic_provider import AnthropicProvider
    return AnthropicProvider(key, cfg.model), None
