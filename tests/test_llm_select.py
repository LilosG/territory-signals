"""Model selection filters and ranking (pure functions; the catalog is a hand-made list, no network)."""
from territory.llm import select_models as sm


def model(id_, p_in, p_out, ctx=131_072, params=("structured_outputs",), desc="A general model.", name=None, **extra):
    return {"id": id_, "name": name or id_, "canonical_slug": id_, "context_length": ctx, "supported_parameters": list(params),
            "pricing": {"prompt": str(p_in / 1e6), "completion": str(p_out / 1e6)}, "description": desc,
            "architecture": {"output_modalities": ["text"]}, **extra}


CATALOG = [
    model("openai/a", 0.1, 0.4), model("google/b", 0.2, 0.2), model("deepseek/c", 0.05, 0.9),
    model("qwen/d", 1, 3), model("mistralai/e", 2, 6), model("meta-llama/f", 3, 9), model("x-ai/g", 5, 15),
    model("openai/h-free", 0, 0), model("openai/i:free", 0.1, 0.1), model("google/j-preview", 0.1, 0.1),
    model("google/k-beta", 0.1, 0.1), model("openai/l", 0.1, 0.1, params=("tools",)), model("openai/m", 0.1, 0.1, ctx=32_000),
    model("openai/n", 0.1, 0.1, desc="Prompts and outputs may be retained and used for training."),
    model("randomlab/o", 0.01, 0.01), model("openai/gpt-code-x", 0.01, 0.01), model("google/p", 0.1, 0.1, params=("response_format",)),
    model("openai/q", 0.1, 0.1, expiration_date="2027-01-01"), model("openai/r:batch", 0.1, 0.1),
]


def test_each_filter_excludes_what_it_should():
    why = {m["id"]: sm.exclusion(m) for m in CATALOG}
    assert why["openai/a"] is None and why["google/p"] is None                       # response_format alone is enough
    assert why["openai/l"] == "no structured output" and why["openai/m"] == "context under 64k"
    assert "variant" in why["openai/i:free"] and "variant" in why["google/j-preview"] and "variant" in why["google/k-beta"]
    assert "variant" in why["openai/q"] and "variant" in why["openai/r:batch"]
    assert why["openai/h-free"] and why["openai/n"] == "description mentions retention or training"
    assert why["randomlab/o"] == "not an established lab" and "specialty" in why["openai/gpt-code-x"]


def test_pick_is_four_cheapest_by_input_plus_3x_output_plus_one_mid_priced_reference():
    picks = [m["id"] for m in sm.pick(CATALOG)]
    ranked = [m["id"] for m in sm.candidates(CATALOG)]
    assert picks[:4] == ranked[:4] and len(picks) == 5 and picks[4] not in picks[:4]
    cost = lambda i: next(sm.rank_key(m) for m in CATALOG if m["id"] == i)
    assert cost(picks[4]) >= cost(picks[3])
    assert sm.rank_key(model("x/y", 1, 2)) == 7


def test_choose_takes_the_cheapest_model_at_90_percent_per_task():
    by_id = {m["id"]: m for m in CATALOG}
    ev = lambda p, l, w: {"tasks": {"permit_intent": {"rate": p}, "lead_brief": {"rate": l}, "weekly_brief": {"rate": w}}}
    evals = {"openai/a": ev(0.95, 0.5, 0.0), "google/b": ev(0.5, 1.0, 0.5), "qwen/d": ev(1, 1, 1), "mistralai/e": ev(1, 1, 1)}
    assert sm.choose(evals, by_id) == {"permit_intent": "openai/a", "lead_brief": "google/b", "weekly_brief": "qwen/d"}
    assert sm.choose({"openai/a": ev(0.8, 0.8, 0.8)}, by_id) == {"permit_intent": None, "lead_brief": None, "weekly_brief": None}


def test_report_table(tmp_path):
    res = lambda p: {"tasks": {k: {"pass": int(p * 10), "n": 10, "rate": p} for k in ("permit_intent", "lead_brief", "weekly_brief")},
                     "total_cost_usd": 0.0123, "cost_unknown": False}
    rows = [{"id": "openai/a", "in": 0.1, "out": 0.4, "eval": res(0.9)}, {"id": "qwen/d", "in": 1.0, "out": 3.0, "eval": res(0.5), "reference": True}]
    path = tmp_path / "r.md"
    sm.write_report(path, rows, {"permit_intent": "openai/a", "lead_brief": "openai/a", "weekly_brief": None}, {"no structured output": 3}, 100)
    t = path.read_text()
    assert "| `openai/a` | 0.100 | 0.400 | 9/10 (90%) | 9/10 (90%) | 9/10 (90%) | $0.0123 | yes: permit_intent, lead_brief |" in t
    assert "(reference)" in t and "weekly_brief`: no model scored 90%" in t and "no structured output: 3" in t
