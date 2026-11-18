"""Deterministic outreach rendering (D10): recipe templates + the agent's sign-off. No AI, no network.

Templates live in config/outreach_templates/<recipe>/<channel>.md with a small front matter block:

    ---
    facts: [component keys the text relies on]      # become source_facts; most templates use none
    subject: "..."                                   # email only
    ---
    body with {neighborhood} / {agent_intro} placeholders

Channels: mail -> letter.md, email -> email.md, call_task -> call_script.md. A recipe without its own
template falls back to config/outreach_templates/general/.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from territory.config import TeamMember, TeamProfile

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "config" / "outreach_templates"
CHANNEL_FILE = {"mail": "letter", "email": "email", "call_task": "call_script"}
GENERAL = "general"
CALL_REMINDER = "Manual dial only. Check Do Not Call status before calling."
EMAIL_OPT_OUT = 'If you would rather not receive emails from us, reply "unsubscribe" and we will take you off our list right away.'
BLOCKED_AGENT = "missing agent name or DRE license"
BLOCKED_OFFICE = "missing office address"
SAMPLE_BANNER = "[SAMPLE DATA: owner details come from sample records. Do not send.]"

# Word-count limits (tests enforce them on every template).
LETTER_WORDS = (120, 180)     # whole letter with a complete sign-off; the body alone is at least 120
EMAIL_WORDS = (80, 130)       # body and sign-off, without the subject line and footer
CALL_WORDS_MAX = 120          # whole script including the reminder line


@dataclass(frozen=True)
class Template:
    key: str                  # "<recipe>/<file>", stored in outreach.template_key
    facts: tuple[str, ...]
    subject: Optional[str]
    body: str


@dataclass(frozen=True)
class Rendered:
    text: str
    subject: Optional[str]
    body: str
    template_key: str
    blocked_reason: Optional[str]
    fact_keys: tuple[str, ...]


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def load_template(recipe: str, channel: str, root: Path | None = None) -> Template:
    root = root or TEMPLATES_DIR
    fname = CHANNEL_FILE[channel]
    name = recipe if (root / recipe / f"{fname}.md").exists() else GENERAL
    raw = (root / name / f"{fname}.md").read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    if not m:
        raise ValueError(f"template {name}/{fname}.md has no front matter")
    meta = yaml.safe_load(m.group(1)) or {}
    return Template(f"{name}/{fname}", tuple(meta.get("facts") or ()), meta.get("subject"), m.group(2).strip())


def all_template_files(root: Path | None = None) -> list[Path]:
    return sorted((root or TEMPLATES_DIR).glob("*/*.md"))


def dre_text(dre_license: str) -> str:
    digits = re.sub(r"^\s*(dre|lic(ense)?|bre)?\s*(#|no\.?|number)?\s*", "", dre_license.strip(), flags=re.I)
    return f"DRE #{digits}" if digits else ""


def signoff_lines(agent: Optional[TeamMember], team: TeamProfile) -> list[str]:
    """Agent name, DRE license, phone, team display name, brokerage; empty values are omitted."""
    lines = []
    if agent is not None:
        lines += [agent.name, dre_text(agent.dre_license), agent.phone.strip()]
    lines += [team.display_name, team.brokerage]
    return [x.strip() for x in lines if x and x.strip()]


def agent_intro(agent: Optional[TeamMember], team: TeamProfile) -> str:
    if agent is None:
        return f"a local agent with {team.display_name}"
    parts = [agent.name]
    if dre_text(agent.dre_license):
        parts.append(dre_text(agent.dre_license))
    who = ", ".join(parts)
    return f"{who}, with {team.display_name}"


def blocked_reason(channel: str, agent: Optional[TeamMember], team: TeamProfile) -> Optional[str]:
    """D11 and the email-footer rule. A draft with a reason is still written but cannot be approved."""
    reasons = []
    if agent is None or not agent.name.strip() or not dre_text(agent.dre_license):
        reasons.append(BLOCKED_AGENT)
    if channel == "email" and not team.office_address.strip():
        reasons.append(BLOCKED_OFFICE)
    return "; ".join(reasons) or None


def render(channel: str, template: Template, salutation: str, neighborhood: str, situs_address: str,
           agent: Optional[TeamMember], team: TeamProfile) -> Rendered:
    values = {"neighborhood": neighborhood, "situs_address": situs_address, "team_name": team.display_name,
              "agent_name": agent.name if agent else "", "agent_intro": agent_intro(agent, team)}
    body = template.body.format_map(values)            # an unknown placeholder raises KeyError
    subject = template.subject.format_map(values) if template.subject else None
    sign = "\n".join(signoff_lines(agent, team))
    if channel == "mail":
        text = f"{salutation}\n\n{body}\n\nSincerely,\n{sign}"
    elif channel == "email":
        footer = "\n".join(x for x in (team.office_address.strip(), EMAIL_OPT_OUT) if x)
        text = f"Subject: {subject}\n\n{salutation}\n\n{body}\n\nBest regards,\n{sign}\n\n--\n{footer}"
    elif channel == "call_task":
        text = f"{body}\n\n{CALL_REMINDER}"
    else:
        raise ValueError(f"unknown channel {channel!r}")
    return Rendered(text, subject, body, template.key, blocked_reason(channel, agent, team), template.facts)


def counted_text(channel: str, r: Rendered) -> str:
    """The text the word-count limits apply to (see the limits above)."""
    if channel == "email":
        head = r.text.split("\n\n", 1)[1]                       # drop the subject line
        return head.split("\n\n--\n")[0]                        # drop the footer
    return r.text
