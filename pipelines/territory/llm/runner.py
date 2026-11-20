"""Run the AI tasks for a client, in order: permit_intent, lead_brief, weekly_brief. Skips cleanly when AI is off."""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from territory.config import ClientConfig
from territory.llm import store
from territory.llm.factory import get_provider

TASKS = ["permit_intent", "lead_brief", "weekly_brief"]


def run_ai(conn, client: ClientConfig, tasks: list[str] | None = None, provider=None, limits: dict | None = None,
           today=None, env=None, out=sys.stdout) -> list[store.TaskStats]:
    """Never raises because of configuration: a disabled client or a missing key returns skipped rows."""
    from territory.llm.tasks import lead_brief, permit_intent, weekly_brief
    mods = {"permit_intent": permit_intent, "lead_brief": lead_brief, "weekly_brief": weekly_brief}
    tasks = tasks or TASKS
    limits = limits or {}
    reason = None
    if provider is None:
        provider, reason = get_provider(client, env)
    results: list[store.TaskStats] = []
    for t in tasks:
        started = datetime.now(timezone.utc)
        s = store.TaskStats(t)
        if provider is None:
            s.status, s.skip_reason = "skipped", reason
            print(f"AI {t}: skipped ({reason})", file=out)
        else:
            try:
                kw = {"limit": limits.get(t)} if t != "weekly_brief" else {"today": today}
                mods[t].run(conn, client, provider, s, **kw)
            except Exception as exc:  # noqa: BLE001 - one task failing must not stop the pipeline
                s.status = "failed"
                s.warnings.append(f"{t}: {type(exc).__name__}: {exc}")
            if s.cost_unknown:
                s.warnings.append(f"{t}: cost unknown for this model (no price in config/llm_pricing.yaml)")
            print(f"AI {t}: {s.status} calls={s.calls} cached={s.cached} valid={s.valid} invalid={s.invalid} "
                  f"rejected={s.rejected} tokens={s.input_tokens + s.output_tokens} cost=${s.cost_usd:.4f}", file=out)
        store.record_task_run(conn, client.client_id, s, started)
        results.append(s)
    return results
