# Phase 5F progress (WIP commit on branch `phase-5f-intelligence`)

Not merged, not tagged, no `db push`, no deploy, nothing run against the cloud DB.

## Done (numbers are the sections of the 5F prompt)
- **0 Fix first.** The cooldown test was wrong, not the code. `run_outreach(now=NOW)` uses a fixed clock, but inserted rows get the database's real `created_at`; once the real date passed the test's NOW, the +91-day check fell inside their cooldown. The test now pins `created_at` to NOW. BACKLOG item removed.
- **1 Provider layer** `pipelines/territory/llm/`: `base.py` (interface, pydantic + one retry), `openai_compatible.py` (OpenRouter fields and headers, cost from usage), `anthropic_provider.py` (cost from `config/llm_pricing.yaml`, empty file, so cost is "unknown" until prices are added), `fake.py`, `factory.py` (skips cleanly when disabled or key missing). `llm:` block added to `config/clients/kaiser-team.yaml`.
- **3 Storage** migration `20261121000000_ai_outputs.sql` (applied to the local working DB): `ai_outputs`, `latest_ai_outputs`, `ai_task_runs`, `ai_month_spend`; prompts in `config/prompts/<task>/v1.md`.
- **4/5/6 Tasks written** (`llm/tasks/`): `permit_intent`, `lead_brief`, `weekly_brief`, with validators (`validators.py`, `homeowner_text.py`), cache, budget guard and `runner.py`. `llm/agreement.py` writes the permit-intent agreement report. Facts packets leave out sensitive records (tax default, ownership transfer, distress recipes).
- **7 Pipeline** `run.py` has `--only-ai` / `--skip-ai`; AI runs after the sources on `--source all`. Pipeline page has the per-task AI table.
- **8 Eval set** `tests/llm_eval/` (31 permit_intent, 10 lead_brief, 3 weekly_brief cases) and `python -m territory.llm.eval`.
- **9 Docs** D13, ARCHITECTURE AI layer, DEPLOY AI section (provider examples, cloud run command).
- **Dashboard** AI summary card on the lead brief, headline on Leads, "This week" card on Today, Briefings archive (`/reports/briefings`), newsletter paragraph, Pipeline AI table. Nothing AI-related renders when `llm.enabled` is false or there are no rows.
- **10 Tests so far:** Python 468 passed (adapters with mocked HTTP via `httpx2.MockTransport`, validators, cache, budget, skip, tasks, selection). The 5 new Playwright tests pass. Only those 5 were run; the full e2e suite has not been rerun.

## In progress: section 2 model selection
Eval results so far (`python -m territory.llm.select_models --run-eval`; pass counts permit_intent / lead_brief / weekly_brief):

| Model | $/M in/out | Result | Eval cost |
|---|---|---|---|
| mistralai/mistral-nemo | 0.029 / 0.030 | 16/31, 5/10, 0/3 | $0.0019 |
| meta-llama/llama-3.1-8b-instruct | 0.020 / 0.040 | 21/31, 10/10, 1/3 | $0.0050 |
| openai/gpt-oss-20b | 0.018 / 0.090 | 29/31, 7/10, 3/3 | $0.0072 |
| google/gemma-3-4b-it | 0.050 / 0.100 | 23/31, 10/10, 0/3 | $0.0009 |
| qwen/qwen3.6-27b (reference) | 0.320 / 3.200 | still running (reasoning model, slow; batches may exceed the 60 s timeout) | - |

A background process was still running the qwen eval when I stopped (its log was in the session scratchpad and may be gone). **Exact next step:** from `pipelines/` run `python -u -m territory.llm.select_models --run-eval --json /tmp/selection.json` again (about $0.02 total; the first four are cheap to repeat), or just run the eval for the reference alone: `python -m territory.llm.eval --provider openai_compatible --model qwen/qwen3.6-27b -v`. Then:
1. Choose per task the cheapest model at >= 90% (so far permit_intent -> gpt-oss-20b; lead_brief -> llama-3.1-8b-instruct or gemma; weekly_brief -> gpt-oss-20b unless qwen is cheaper-and-passing, which it is not). Evals are stochastic and 10 cases is coarse; consider rerunning once before fixing the choice.
2. Replace both `MODEL_TBD` values in `config/clients/kaiser-team.yaml` (`llm.model` and `tasks.permit_intent.model`; add `weekly_brief: {model: ...}` if it differs from `llm.model`).
3. Write `docs/reports/model-selection.md` (the script does this when it finishes).
Note for the big run: reasoning models are slow per batch; if gpt-oss-20b is chosen, raise `workers` or lower `BATCH` in `permit_intent.py` if the run is too slow.

## Not started
- Real local runs: `python -m territory.run --client kaiser-team --only-ai` for permit_intent on all permits, lead_brief on the top 25 only (use `run_ai(..., limits={"lead_brief": 25})` or a small script, since the CLI has no limit flag), one weekly_brief. Then record the real cost.
- `python -m territory.llm.agreement --client kaiser-team` -> `docs/reports/permit-intent-agreement.md`.
- `docs/reports/5f-samples.md` (3 lead briefs and the weekly brief, from `latest_ai_outputs`).
- Screenshots: `cd dashboard && npx tsx scripts/screenshots-5f.ts` (script written, not run) to `docs/screenshots/5f/` at 1440 and 390; open them and fix layout issues.
- Full Playwright run (`npm run e2e`) and `npm run build:prod` check.
- Section 11: tag `phase-5f-intelligence-v1`, print the two commands (cloud push + refresh + deploy; cloud AI run, already drafted in DEPLOY.md), and the 10-line final report (cooldown answer above; chosen models and prices; eval table; agreement rate; invalid/rejected counts; real cost; projected monthly cost).

## AI-task run state
No AI task has run against the database: `ai_outputs` and `ai_task_runs` are empty locally. Money spent so far is eval calls only (about $0.015, plus the qwen eval and a few test calls under $0.01). The cloud DB was not touched.
