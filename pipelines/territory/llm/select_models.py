"""Model selection from the OpenRouter catalog (Phase 5F section 2).

    python -m territory.llm.select_models [--run-eval] [--report docs/reports/model-selection.md]

Filter -> rank by (input + 3 x output) price -> 4 cheapest + 1 mid-priced reference -> eval each -> report.
`candidates()` is pure and unit-tested; the eval needs LLM_API_KEY."""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

MODELS_URL = "https://openrouter.ai/api/v1/models"
LABS = {"openai", "google", "deepseek", "qwen", "mistralai", "meta-llama", "x-ai", "anthropic", "moonshotai", "z-ai"}
MIN_CONTEXT = 64_000
VARIANT = re.compile(r":free|\bfree\b|beta|preview|contributor|experimental|\bexp\b|-exp\b|:extended|:nitro|:batch|:thinking", re.I)
SPECIALTY = re.compile(r"code|codex|coder|devstral|image|audio|-vl\b|\bvl\b|omni|legal|safeguard|multi-agent|guard|embed|-build", re.I)
RETENTION = re.compile(r"(retain|retention|stored|logged|logs? (prompts|inputs)|used (for|to) (model )?(training|improv)|"
                       r"train(ing)? (on|data)|may be (used|collected))", re.I)
MIN_REPORT = Path(__file__).resolve().parents[3] / "docs" / "reports" / "model-selection.md"


def fetch_models(url: str = MODELS_URL) -> list[dict]:
    with urllib.request.urlopen(url, timeout=60) as r:                      # no key needed for the catalog
        return json.load(r)["data"]


def price(m: dict) -> tuple[float, float]:
    """(input, output) USD per million tokens."""
    p = m.get("pricing") or {}
    return float(p.get("prompt") or 0) * 1e6, float(p.get("completion") or 0) * 1e6


def rank_key(m: dict) -> float:
    i, o = price(m)
    return i + 3 * o


def exclusion(m: dict) -> str | None:
    """Why a model is out, or None if it is a candidate."""
    sp = set(m.get("supported_parameters") or [])
    if not ({"structured_outputs", "response_format"} & sp):
        return "no structured output"
    if (m.get("context_length") or 0) < MIN_CONTEXT:
        return "context under 64k"
    ident = f"{m['id']} {m.get('name', '')} {m.get('canonical_slug', '')}"
    if VARIANT.search(ident) or m.get("expiration_date"):
        return "free, beta, preview or contributor variant"
    i, o = price(m)
    if i <= 0 or o <= 0:
        return "no paid price"
    if SPECIALTY.search(ident):
        return "specialty model (code, image, audio, vision, safety)"
    if RETENTION.search(m.get("description") or ""):
        return "description mentions retention or training"
    if m["id"].split("/")[0] not in LABS:
        return "not an established lab"
    if "text" not in (m.get("architecture") or {}).get("output_modalities", ["text"]):
        return "no text output"
    return None


def candidates(models: list[dict]) -> list[dict]:
    return sorted((m for m in models if exclusion(m) is None), key=rank_key)


def pick(models: list[dict], n_cheap: int = 4) -> list[dict]:
    """The n_cheap cheapest plus one mid-priced reference (the median of the remaining candidates)."""
    c = candidates(models)
    cheap = c[:n_cheap]
    rest = c[n_cheap:]
    ref = rest[len(rest) // 2] if rest else None
    return cheap + ([ref] if ref else [])


def choose(evals: dict[str, dict], models_by_id: dict[str, dict]) -> dict[str, str | None]:
    """Cheapest model scoring >= 90% per task; lead_brief and weekly_brief share the cheaper of the two winners' models
    only if one model passes both (they may differ, so each is chosen on its own)."""
    out: dict[str, str | None] = {}
    for task in ("permit_intent", "lead_brief", "weekly_brief"):
        ok = [mid for mid, r in evals.items() if r["tasks"][task]["rate"] >= 0.90]
        out[task] = min(ok, key=lambda mid: rank_key(models_by_id[mid])) if ok else None
    return out


def write_report(path: Path, rows: list[dict], chosen: dict[str, str | None], excluded_counts: dict[str, int],
                 total_models: int) -> None:
    lines = ["# Model selection (Phase 5F)", "",
             f"Source: OpenRouter `/api/v1/models` ({total_models} models). Eval: `tests/llm_eval/` "
             f"(31 permit_intent, 10 lead_brief, 3 weekly_brief cases), `python -m territory.llm.eval`. "
             "Every request sends `provider.data_collection = deny` and `require_parameters = true`.", "",
             "Filters: supports structured outputs or response_format; context >= 64k; not a free, beta, preview or contributor "
             "variant; description does not mention retention or training; established lab (OpenAI, Google, DeepSeek, Qwen, "
             "Mistral, Meta, xAI, Anthropic, Moonshot, Z.ai). Ranked by input + 3 x output price. The catalog's descriptions "
             "are short, so `data_collection: deny` on every request is the real retention control, not the description filter.", "",
             "| Model | $/M in | $/M out | permit_intent | lead_brief | weekly_brief | Eval cost | Chosen |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        t = r["eval"]["tasks"]
        used = [k for k, v in chosen.items() if v == r["id"]]
        cost = "unknown" if r["eval"]["cost_unknown"] and not r["eval"]["total_cost_usd"] else f"${r['eval']['total_cost_usd']:.4f}"
        lines.append(f"| `{r['id']}`{' (reference)' if r.get('reference') else ''} | {r['in']:.3f} | {r['out']:.3f} | "
                     + " | ".join(f"{t[k]['pass']}/{t[k]['n']} ({t[k]['rate']:.0%})" for k in ("permit_intent", "lead_brief", "weekly_brief"))
                     + f" | {cost} | {'yes: ' + ', '.join(used) if used else 'no'} |")
    lines += ["", "## Chosen", ""]
    for k, v in chosen.items():
        lines.append(f"- `{k}`: " + (f"`{v}`" if v else "no model scored 90% (AI task stays off until one does)"))
    lines += ["", "## Exclusions (how many catalog models each filter removed first)", ""]
    lines += [f"- {k}: {v}" for k, v in sorted(excluded_counts.items(), key=lambda kv: -kv[1])]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="territory.llm.select_models")
    ap.add_argument("--run-eval", action="store_true")
    ap.add_argument("--report", default=str(MIN_REPORT))
    ap.add_argument("--json", help="save the raw eval results here")
    a = ap.parse_args(argv)
    models = fetch_models()
    by_id = {m["id"]: m for m in models}
    reasons: dict[str, int] = {}
    for m in models:
        r = exclusion(m)
        if r:
            reasons[r] = reasons.get(r, 0) + 1
    picks = pick(models)
    for i, m in enumerate(picks):
        i_, o_ = price(m)
        print(f"{'ref ' if i == 4 else '    '}{m['id']:50s} in ${i_:8.3f}  out ${o_:8.3f}  ctx {m['context_length']}")
    if not a.run_eval:
        return 0
    from territory.llm.eval import make_provider, run_eval
    rows, evals = [], {}
    for i, m in enumerate(picks):
        print(f"eval {m['id']} ...", flush=True)
        res = run_eval(make_provider("openai_compatible", m["id"], MODELS_URL.rsplit("/models", 1)[0]), m["id"])
        evals[m["id"]] = res
        i_, o_ = price(m)
        rows.append({"id": m["id"], "in": i_, "out": o_, "eval": res, "reference": i == 4})
        print("   ", {k: f"{v['pass']}/{v['n']}" for k, v in res["tasks"].items()}, res["total_cost_usd"], flush=True)
    chosen = choose(evals, by_id)
    write_report(Path(a.report), rows, chosen, reasons, len(models))
    if a.json:
        Path(a.json).write_text(json.dumps({"rows": rows, "chosen": chosen}, indent=1))
    print("chosen:", chosen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
