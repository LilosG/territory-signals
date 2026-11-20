# Phase 5F: complete

All sections of the 5F prompt are done on branch `phase-5f-intelligence`, tagged `phase-5f-intelligence-v1`. Not merged, no `db push`, no deploy, nothing run against the cloud DB.

- Models: permit_intent `openai/gpt-oss-20b`; lead_brief and weekly_brief `deepseek/deepseek-v4.1-flash` (see `docs/reports/model-selection.md`).
- permit_intent scope (config `llm.tasks.permit_intent.scope`): issued in the last 36 months OR on a parcel scoring >= 40.
- Reports: `docs/reports/model-selection.md`, `permit-intent-agreement.md`, `5f-samples.md`; screenshots in `docs/screenshots/5f/`.
- Tests: 470 Python, 31 Playwright; `npm run build:prod` builds.
- Open items are in BACKLOG.md ("Added during Phase 5F").
