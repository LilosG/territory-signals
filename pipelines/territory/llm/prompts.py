"""Prompts live in config/prompts/<task>/v<N>.md; prompt_version is the file name."""
from __future__ import annotations

import re
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "config" / "prompts"


def load_prompt(task: str, version: str | None = None, root: Path | None = None) -> tuple[str, str]:
    """Returns (text, version). Default version = the highest vN file."""
    d = (root or PROMPTS_DIR) / task
    if version is None:
        found = sorted((int(m.group(1)), p) for p in d.glob("v*.md") if (m := re.fullmatch(r"v(\d+)\.md", p.name)))
        if not found:
            raise FileNotFoundError(f"no prompt files in {d}")
        n, path = found[-1]
        version = f"v{n}"
    else:
        path = d / f"{version}.md"
    return path.read_text(encoding="utf-8").strip(), version
