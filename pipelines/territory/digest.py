"""Monday Executive Digest: HTML and plain-text email payloads for the internal team.

The digest is built only from rows already in the database:
  - the latest valid ``weekly_brief`` summary and its copy-ready newsletter paragraph
  - the top five active leads from the most recent scoring run
  - deterministic territory facts (``weekly_brief.compute_facts``) and source health

Privacy: it never selects owner names, mailing addresses, emails or phone numbers.
Recipients are the internal team only (``team_members``); see ``send_digest``.
"""
from __future__ import annotations

import html
import os
import re
import smtplib
from datetime import date, datetime, timezone
from email.message import EmailMessage
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from territory.config import ClientConfig
from territory.scoring_engine import load_scoring_config

DASHBOARD_BASE_URL = os.environ.get(
    "DASHBOARD_BASE_URL", "https://kaiser-team-signals.mike-1d7.workers.dev"
).rstrip("/")
PACIFIC = ZoneInfo("America/Los_Angeles")
GCI_RATE = 0.025
AWAITING_MESSAGE = "awaiting manual download"
SENSITIVE_HEADLINE = re.compile(
    r"tax|default|delinquen|distress|foreclos|ownership transfer|estate|trust|probate|inherit",
    re.I,
)


# ---------------------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------------------
def _first_sentence(text: str | None) -> str:
    if not text:
        return ""
    line = " ".join(str(text).split())
    return line.split(". ", 1)[0].rstrip(".")


def _public_headline(reason_text: str | None, recipe_label: str | None) -> str:
    """A one-line headline that never surfaces distress or life-event wording. AI lead briefs are preferred by the caller;
    this deterministic fallback is only used when no valid brief exists."""
    first = _first_sentence(reason_text)
    if first and not SENSITIVE_HEADLINE.search(first):
        return first
    return recipe_label or "Review this lead"


def _recipe_label(primary: str | None, matches: list[str] | None, cfg: Mapping[str, Any]) -> str | None:
    key = primary or next(iter(matches or []), None)
    if not key:
        return None
    return (cfg.get("recipes", {}).get(key) or {}).get("label", key)


def _title_address(value: str | None) -> str:
    if not value:
        return ""
    return value.title() if value.isupper() else value


def _week_range(facts: Mapping[str, Any], today: date) -> dict[str, str]:
    week = facts.get("week") if facts else None
    if isinstance(week, dict) and week.get("start") and week.get("end"):
        return {"start": str(week["start"]), "end": str(week["end"])}
    from datetime import timedelta

    return {"start": (today - timedelta(days=7)).isoformat(), "end": today.isoformat()}


def _safe_facts(conn, today: date) -> dict:
    """Deterministic territory facts. A digest must still render if a fresh database has no scores yet."""
    try:
        from territory.llm.tasks.weekly_brief import compute_facts

        return compute_facts(conn, today)
    except Exception:  # noqa: BLE001 - a report must not fail because trend inputs are absent
        return {}


def _latest_weekly_brief(conn, client_id: str) -> dict | None:
    row = conn.execute(
        "select subject_id, output, uses_sample, created_at from ai_outputs "
        "where client_id = %s and task = 'weekly_brief' and subject_type = 'territory' and status = 'valid' "
        "order by created_at desc, id desc limit 1",
        (client_id,),
    ).fetchone()
    if not row:
        return None
    subject_id, output, uses_sample, created_at = row
    output = output or {}
    return {
        "week_start": subject_id,
        "title": output.get("title") or "",
        "intro": output.get("intro") or "",
        "sections": output.get("sections") or [],
        "newsletter_paragraph": output.get("newsletter_paragraph") or "",
        "uses_sample": bool(uses_sample),
        "created_at": created_at,
    }


def _latest_lead_headline(conn, client_id: str, apn: str) -> str | None:
    row = conn.execute(
        "select output from ai_outputs where client_id = %s and task = 'lead_brief' "
        "and subject_type = 'parcel' and subject_id = %s and status = 'valid' "
        "order by created_at desc, id desc limit 1",
        (client_id, apn),
    ).fetchone()
    if not row or not isinstance(row[0], dict):
        return None
    headline = " ".join(str(row[0].get("headline") or "").split())
    return headline or None


def _top_leads(conn, client: ClientConfig, cfg: Mapping[str, Any], limit: int = 5) -> list[dict]:
    latest = conn.execute("select max(scored_at) from scores").fetchone()[0]
    if latest is None:
        return []
    rows = conn.execute(
        """select s.apn, p.situs_address, coalesce(p.neighborhood, p.planning_area), s.score,
                  s.primary_recipe, s.recipe_matches, s.reason_text, s.uses_sample_data,
                  o.est_value, o.is_sample
             from scores s
             join parcels p on p.apn = s.apn
             left join latest_owners o on o.apn = s.apn
            where s.scored_at = %s
            order by s.score desc, s.apn
            limit %s""",
        (latest, limit),
    ).fetchall()
    leads: list[dict] = []
    for rank, r in enumerate(rows, 1):
        (apn, situs, hood, score, primary, matches, reason, score_sample,
         est_value, owner_sample) = r
        label = _recipe_label(primary, list(matches or []), cfg)
        ai_headline = _latest_lead_headline(conn, client.client_id, apn)
        gci = round(float(est_value) * GCI_RATE) if est_value is not None and float(est_value) > 0 else None
        leads.append({
            "rank": rank,
            "apn": apn,
            "address": _title_address(situs) or f"Parcel {apn}",
            "neighborhood": hood or "Territory",
            "score": int(score),
            "recipe": label or "—",
            "headline": ai_headline or _public_headline(reason, label),
            "gci": gci,
            "sample": bool(score_sample or owner_sample),
            "url": f"{DASHBOARD_BASE_URL}/leads/{apn}",
        })
    return leads


def _source_health(conn) -> list[dict]:
    rows = conn.execute(
        "select source_key, status, started_at, finished_at, rows_fetched, error_message "
        "from source_latest order by source_key"
    ).fetchall()
    out = []
    for key, status, started, finished, fetched, error in rows:
        shown = status
        if status == "failed" and error == AWAITING_MESSAGE:
            shown = "awaiting manual download"
        out.append({
            "source_key": key,
            "status": shown,
            "started_at": started,
            "finished_at": finished,
            "rows_fetched": int(fetched or 0),
            "error": None if shown == "awaiting manual download" else error,
        })
    return out


def _any_estimate_this_week(conn, week_start: str) -> bool:
    row = conn.execute(
        "select exists (select 1 from signals where superseded_by is null and is_estimate "
        "and detected_at >= %s::date)", (week_start,)
    ).fetchone()
    return bool(row and row[0])


def collect_digest_data(conn, client: ClientConfig, today: date | None = None) -> dict:
    """Everything the digest shows, assembled from the database only. No AI calls, no owner contact details."""
    today = today or date.today()
    cfg = load_scoring_config()
    facts = _safe_facts(conn, today)
    week = _week_range(facts, today)
    brief = _latest_weekly_brief(conn, client.client_id)
    leads = _top_leads(conn, client, cfg)
    territory = (facts.get("territory") or {}) if facts else {}
    signals = {
        "new_this_week": territory.get("new_this_week") or {},
        "new_pre_sale_permits": territory.get("new_pre_sale_permits"),
        "new_str_removals": territory.get("new_str_removals"),
        "tax_default_new_this_week": territory.get("tax_default_new_this_week"),
        "strong_leads_now": territory.get("strong_leads_now"),
        "new_strong_leads": territory.get("new_strong_leads"),
        "top_new_signals": (facts or {}).get("top_new_signals") or [],
        "scoring_model_changed": bool((facts or {}).get("scoring_model_changed")),
    }
    sample = any(l["sample"] for l in leads) or bool(brief and brief["uses_sample"])
    estimated = _any_estimate_this_week(conn, week["start"]) or any(l["gci"] is not None for l in leads)
    return {
        "client_id": client.client_id,
        "display_name": client.display_name,
        "generated_at": datetime.now(timezone.utc),
        "week": week,
        "brief": brief,
        "leads": leads,
        "signals": signals,
        "source_health": _source_health(conn),
        "disclosures": {"sample": sample, "estimated": estimated},
        "dashboard_url": DASHBOARD_BASE_URL,
    }


# ---------------------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------------------
def _fmt_money(value: int | None) -> str:
    if value is None:
        return "—"
    if value >= 1_000_000:
        return f"${value / 100_000:.1f}".rstrip("0").rstrip(".") + "M"
    return f"${round(value / 1000)}k"


def _fmt_when(data: Mapping[str, Any]) -> str:
    dt = data["generated_at"].astimezone(PACIFIC)
    return dt.strftime("%A, %B %-d, %Y at %-I:%M %p %Z")


def subject_for(data: Mapping[str, Any]) -> str:
    return f"{data['display_name']} | Monday territory digest | {data['week']['end']}"


def _signal_lines(signals: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    for what, n in sorted((signals.get("new_this_week") or {}).items()):
        lines.append(f"{n} new {what}")
    if signals.get("top_new_signals"):
        for s in signals["top_new_signals"]:
            where = s.get("neighborhood")
            lines.append(f"{s.get('what')}" + (f" · {where}" if where else ""))
    if signals.get("new_strong_leads") is not None:
        lines.append(f"{signals['new_strong_leads']} new strong leads this week")
    elif signals.get("strong_leads_now") is not None:
        lines.append(f"{signals['strong_leads_now']} strong leads now")
    if not lines:
        lines.append("No new territory signals were recorded this week.")
    return lines


def render_html(data: Mapping[str, Any]) -> str:
    esc = html.escape
    d = data
    week = d["week"]
    brief = d.get("brief")

    lead_cards = []
    for l in d["leads"]:
        sample = ' <span class="tag tag-sample">Sample data</span>' if l["sample"] else ""
        gci = f'<span class="tag tag-est">Est. {esc(_fmt_money(l["gci"]))} GCI</span>' if l["gci"] is not None else ""
        lead_cards.append(f"""
        <div class="lead">
          <div class="lead-top">
            <span class="rank">{l['rank']}</span>
            <span class="addr"><a href="{esc(l['url'])}">{esc(l['address'])}</a></span>
            <span class="score">{l['score']}</span>
          </div>
          <div class="meta">{esc(l['neighborhood'])} · <span class="recipe">{esc(l['recipe'])}</span></div>
          <div class="headline">{esc(l['headline'])}</div>
          <div class="gci">{gci}{sample}</div>
        </div>""")

    brief_html = "<p class=\"muted\">No weekly brief is available yet.</p>"
    if brief:
        sections = []
        for sec in brief["sections"]:
            bullets = "".join(f"<li>{esc(b)}</li>" for b in sec.get("bullets") or [])
            sections.append(f"<h4>{esc(sec.get('neighborhood', ''))}</h4><ul>{bullets}</ul>")
        newsletter = ""
        if brief["newsletter_paragraph"]:
            newsletter = (
                '<div class="newsletter"><div class="newsletter-label">Copy-ready newsletter</div>'
                f'<p>{esc(brief["newsletter_paragraph"])}</p></div>'
            )
        sample_tag = ' <span class="tag tag-sample">Sample data</span>' if brief["uses_sample"] else ""
        brief_html = f"""
        <h3>{esc(brief['title'])}{sample_tag}</h3>
        <p>{esc(brief['intro'])}</p>
        {''.join(sections)}
        {newsletter}
        <p class="muted">Brief for the week of {esc(str(brief['week_start']))}.</p>"""

    signal_items = "".join(f"<li>{esc(x)}</li>" for x in _signal_lines(d["signals"]))
    health_rows = "".join(
        f"<tr><td>{esc(h['source_key'])}</td><td class=\"{'ok' if h['status'] == 'success' else 'warn'}\">"
        f"{esc(h['status'])}</td><td class=\"num\">{h['rows_fetched']}</td></tr>"
        for h in d["source_health"]
    ) or '<tr><td colspan="3" class="muted">No source runs recorded yet.</td></tr>'

    disclosures = []
    if d["disclosures"]["sample"]:
        disclosures.append(
            "<li><strong>Sample data</strong>: some owner values and owner-derived facts are labeled sample data until "
            "ATTOM is connected.</li>")
    if d["disclosures"]["estimated"]:
        disclosures.append(
            "<li><strong>Estimated</strong>: estimated GCI is 2.5% of the estimated property value; upzoning eligibility "
            "is an in-house screen, not an official determination.</li>")
    disclosures_html = (
        '<div class="disclosures"><h3>Disclosures</h3><ul>' + "".join(disclosures) + "</ul></div>"
        if disclosures else ""
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(subject_for(d))}</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ margin:0; padding:0; background:#f6f4ef; color:#1f2937;
         font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }}
  .wrap {{ max-width:640px; margin:0 auto; padding:24px 18px 36px; }}
  .card {{ background:#ffffff; border:1px solid #e5e0d5; border-radius:12px; padding:20px; margin:0 0 16px; }}
  .kicker {{ color:#8a6d1f; font-size:12px; letter-spacing:.12em; text-transform:uppercase; font-weight:700; }}
  h1 {{ margin:6px 0 2px; font-size:26px; line-height:1.2; }}
  h2 {{ margin:0 0 10px; font-size:18px; }}
  h3 {{ margin:14px 0 6px; font-size:16px; }}
  h4 {{ margin:12px 0 4px; font-size:14px; color:#374151; }}
  p {{ margin:0 0 10px; line-height:1.5; }}
  ul {{ margin:0 0 10px; padding-left:20px; }}
  li {{ margin:0 0 5px; line-height:1.45; }}
  .muted {{ color:#6b7280; font-size:13px; }}
  .lead {{ border-top:1px solid #eee9df; padding:12px 0; }}
  .lead:first-child {{ border-top:0; }}
  .lead-top {{ display:flex; align-items:center; gap:10px; }}
  .rank {{ display:inline-flex; align-items:center; justify-content:center; width:22px; height:22px;
           border-radius:50%; background:#1e3a8a; color:#fff; font-size:12px; font-weight:700; }}
  .addr {{ flex:1; font-weight:700; font-size:15px; }}
  .addr a {{ color:#1f2937; text-decoration:none; }}
  .score {{ display:inline-block; min-width:34px; text-align:center; background:#fef3c7; color:#92400e;
            border-radius:999px; padding:3px 8px; font-weight:700; font-size:13px; }}
  .meta {{ color:#4b5563; font-size:13px; margin:5px 0 0 32px; }}
  .recipe {{ color:#1e3a8a; font-weight:600; }}
  .headline {{ margin:4px 0 0 32px; font-size:14px; }}
  .gci {{ margin:6px 0 0 32px; }}
  .tag {{ display:inline-block; border-radius:999px; padding:2px 8px; font-size:11px; font-weight:700; }}
  .tag-est {{ background:#eef2ff; color:#3730a3; }}
  .tag-sample {{ background:#fef3c7; color:#92400e; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  td {{ border-top:1px solid #eee9df; padding:7px 4px; }}
  td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  td.ok {{ color:#166534; font-weight:600; }}
  td.warn {{ color:#9a3412; font-weight:600; }}
  .newsletter {{ background:#f8f6f0; border:1px solid #e8e1d3; border-radius:10px; padding:12px 14px; margin:12px 0; }}
  .newsletter-label {{ color:#8a6d1f; font-size:11px; letter-spacing:.1em; text-transform:uppercase; font-weight:700; margin-bottom:6px; }}
  .disclosures {{ font-size:12px; color:#4b5563; }}
  .footer {{ text-align:center; font-size:12px; color:#6b7280; margin-top:18px; }}
  .footer a {{ color:#1e3a8a; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <div class="kicker">Monday executive digest</div>
    <h1>{esc(d['display_name'])}</h1>
    <p class="muted">Week of {esc(week['start'])} to {esc(week['end'])} · generated {esc(_fmt_when(d))}</p>
  </div>

  <div class="card">
    <h2>This week's brief</h2>
    {brief_html}
  </div>

  <div class="card">
    <h2>Top {len(d['leads']) or 5} active leads</h2>
    {''.join(lead_cards) or '<p class="muted">No scored leads yet.</p>'}
  </div>

  <div class="card">
    <h2>Territory signals</h2>
    <ul>{signal_items}</ul>
    {disclosures_html}
  </div>

  <div class="card">
    <h2>Source health</h2>
    <table>{health_rows}</table>
  </div>

  <div class="footer">
    <p><a href="{esc(d['dashboard_url'])}">{esc(d['dashboard_url'])}</a></p>
    <p>Internal team digest. Do not forward outside the {esc(d['display_name'])} team.</p>
  </div>
</div>
</body>
</html>
"""


def render_text(data: Mapping[str, Any]) -> str:
    d = data
    week = d["week"]
    lines = [
        f"{d['display_name']} — Monday Executive Digest",
        f"Week of {week['start']} to {week['end']}",
        f"Generated {_fmt_when(d)}",
        "",
        "THIS WEEK'S BRIEF",
        "-----------------",
    ]
    brief = d.get("brief")
    if brief:
        lines += [brief["title"], brief["intro"], ""]
        for sec in brief["sections"]:
            lines.append(sec.get("neighborhood", ""))
            lines += [f"  - {b}" for b in sec.get("bullets") or []]
            lines.append("")
        if brief["newsletter_paragraph"]:
            lines += ["Copy-ready newsletter:", brief["newsletter_paragraph"], ""]
        if brief["uses_sample"]:
            lines += ["[Sample data]", ""]
    else:
        lines += ["No weekly brief is available yet.", ""]

    lines += [f"TOP {len(d['leads']) or 5} ACTIVE LEADS", "---------------------"]
    if not d["leads"]:
        lines.append("No scored leads yet.")
    for l in d["leads"]:
        gci = f" | Est. {_fmt_money(l['gci'])} GCI" if l["gci"] is not None else ""
        sample = " | Sample data" if l["sample"] else ""
        lines += [
            f"{l['rank']}. {l['address']} ({l['neighborhood']}) — score {l['score']} — {l['recipe']}{gci}{sample}",
            f"   {l['headline']}",
            f"   {l['url']}",
        ]
    lines.append("")

    lines += ["TERRITORY SIGNALS", "-----------------"]
    lines += [f"- {x}" for x in _signal_lines(d["signals"])]
    lines.append("")
    if d["disclosures"]["sample"]:
        lines.append("Sample data: some owner values and owner-derived facts are labeled sample data until ATTOM is connected.")
    if d["disclosures"]["estimated"]:
        lines.append("Estimated: estimated GCI is 2.5% of the estimated property value; upzoning eligibility is an in-house screen.")
    if d["disclosures"]["sample"] or d["disclosures"]["estimated"]:
        lines.append("")

    lines += ["SOURCE HEALTH", "-------------"]
    if d["source_health"]:
        for h in d["source_health"]:
            lines.append(f"- {h['source_key']}: {h['status']} ({h['rows_fetched']} rows)")
    else:
        lines.append("- No source runs recorded yet.")
    lines += ["", f"Dashboard: {d['dashboard_url']}",
              f"Internal team digest. Do not forward outside the {d['display_name']} team."]
    return "\n".join(lines) + "\n"


def render_digest(data: Mapping[str, Any]) -> tuple[str, str]:
    return render_html(data), render_text(data)


# ---------------------------------------------------------------------------------------
# sending
# ---------------------------------------------------------------------------------------
def _recipients(env: Mapping[str, str], conn, client: ClientConfig) -> list[str]:
    raw = env.get("DIGEST_TO", "")
    recipients = [x.strip() for x in raw.split(",") if x.strip()]
    if not recipients:
        raise RuntimeError("DIGEST_TO is not set")
    bad_format = [r for r in recipients if "@" not in r]
    if bad_format:
        raise RuntimeError(f"DIGEST_TO has an invalid address: {bad_format[0]!r}")
    team = {str(r[0]).lower() for r in conn.execute("select email from team_members")}
    if not team:
        raise RuntimeError("refusing to send the digest: team_members is empty, so no recipient can be verified")
    outsiders = sorted(r for r in recipients if r.lower() not in team)
    if outsiders:
        raise RuntimeError(
            "refusing to send the digest outside the internal team: "
            + ", ".join(outsiders)
            + " (add them to team_members first)"
        )
    return recipients


def send_digest(html_body: str, text_body: str, subject: str, *, conn, client: ClientConfig,
                env: Mapping[str, str] | None = None, smtp_factory=None) -> list[str]:
    """Send the digest to internal team members only. Requires SMTP_HOST, SMTP_PORT, DIGEST_FROM and DIGEST_TO;
    SMTP_USER/SMTP_PASS are used when present. Raises before connecting if a recipient is not on the team."""
    env = dict(os.environ if env is None else env)
    recipients = _recipients(env, conn, client)
    missing = [k for k in ("SMTP_HOST", "SMTP_PORT", "DIGEST_FROM", "DIGEST_TO") if not env.get(k)]
    if missing:
        raise RuntimeError("missing SMTP settings: " + ", ".join(missing))
    host, port = env["SMTP_HOST"], int(env["SMTP_PORT"])
    user, password = env.get("SMTP_USER"), env.get("SMTP_PASS")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = env["DIGEST_FROM"]
    msg["To"] = ", ".join(recipients)
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    factory = smtp_factory or (smtplib.SMTP_SSL if port == 465 else smtplib.SMTP)
    with factory(host, port, timeout=30) as smtp:
        if port != 465:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
        if user and password:
            smtp.login(user, password)
        smtp.send_message(msg)
    return recipients
