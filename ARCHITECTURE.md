# Architecture

## Layers
| Layer | Purpose | Folder | Tables |
|---|---|---|---|
| Collect | Pull raw data from sources and owner providers | `pipelines/territory/sources/`, `owner_data/` | `source_runs`, `raw_records` |
| Connect | Match records to parcels and normalize into signals | `pipelines/` | `parcels`, `neighborhoods`, `signals`, `owners`, `sales_history` |
| Score | Deterministic scoring and recipe matching | `pipelines/` | `scores`, `suppressions` |
| Act | Draft outreach for human approval; record outcomes | `pipelines/` | `outreach`, `outcomes`, `team_members` |
| Show | Dashboard (Astro + Tailwind) | `dashboard/` (Phase 4) | reads all via RLS |

## Data flow
Source adapter `fetch` -> `raw_records` (append-only, tied to a `source_runs` row) -> `normalize` -> `SignalCandidate` -> match to a parcel (apn, spatial, address or name) -> `signals` (append-only) -> scoring reads `signals` + `owners` + `sales_history` -> `scores` -> outreach drafts in `outreach` (status flow draft -> awaiting_approval -> approved -> sent) -> `outcomes` recorded by team members. Per-client settings come from `config/clients/<client_id>.yaml`.

## Table reference
All tables are in `public`, have a `created_at timestamptz default now()`, have RLS enabled (authenticated users select; writes only via the service role). Primary keys are uuid unless noted.

- **neighborhoods**: id, name, planning_area, geom MultiPolygon(4326), is_official
- **parcels**: apn (text PK), situs_address, zip, planning_area, neighborhood, geom MultiPolygon(4326), centroid Point(4326), lot_sqft, land_use, zoning, year_built, last_recorded_doc_date, source_key, updated_at
- **source_runs**: id, source_key, started_at, finished_at, status (running|success|failed), rows_fetched, rows_matched, rows_unmatched, error_message
- **raw_records**: id, source_key, source_record_id, run_id -> source_runs, payload jsonb, fetched_at; unique(source_key, source_record_id, fetched_at)
- **signals**: id, apn -> parcels, signal_type, signal_group, signal_date, detected_at, source_key, source_record_id, run_id -> source_runs, confidence (0..1), match_method (apn|spatial|address|name), is_estimate, is_sample, details jsonb
- **owners**: id, apn -> parcels, owner_name, mailing_address, owner_occupied, absentee, out_of_state, last_sale_date, last_sale_price, mortgage_open, est_value, est_equity, provider (attom|sample), is_sample, as_of; a new row per as_of, never updated in place
- **sales_history**: id, apn -> parcels, sale_date, sale_price, doc_type, provider, is_sample
- **scores**: id, apn -> parcels, score (0..100), components jsonb, reason_text, recipe_matches text[], model_version, scored_at
- **suppressions**: id, apn -> parcels, reason, until_date
- **outreach**: id, apn -> parcels, channel (mail|email|call_task), status (draft|awaiting_approval|approved|sent|suppressed), content, source_facts jsonb, approved_by, sent_at; Phase 5A adds recipe, assigned_to, due_date, mailing_address, salutation, template_key, model_version, blocked_reason, uses_sample_data. A check constraint stops a row with a `blocked_reason` from becoming approved or sent (D11)
- **outcomes**: id, apn -> parcels, team_member_email, status (contacted|conversation|appointment|listing|not_interested|bad_data), noted_at, note
- **team_members**: id, email (unique), name, role (owner|agent|assistant)
- **stage_events** (Phase 5A, append-only): id, apn -> parcels, stage (signal|contacted|conversation|appointment|listing|not_interested|bad_data), team_member_email, occurred_at, note, source (dashboard|system)
- **Views** (security_invoker): `latest_scores`; `funnel_by_recipe` and `funnel_by_agent` count distinct parcels per stage from `stage_events` joined to `latest_scores` (a parcel counts toward every recipe it matches; events with no agent show as `unassigned`)

Indexes: GIST on `neighborhoods.geom`, `parcels.geom`, `parcels.centroid`; btree on `signals(apn, signal_type, signal_date)`, `scores(scored_at)`, `outreach(status)`.

## Adapter interfaces
- `SourceAdapter` (`sources/base.py`): `source_key`; `fetch(run_id) -> Iterable[RawRecord]`; `normalize(raw) -> Iterable[SignalCandidate]`.
- `OwnerDataProvider` (`owner_data/base.py`): `get_owner(apn)`, `get_sales_history(apn)`, `bulk_owners(apns)`. Implementations: `SampleOwnerProvider` (deterministic, `is_sample=True`, owner_name "Sample Owner <last 4 of APN>") and `AttomOwnerProvider` (skeleton; raises `NotConfiguredError` without `ATTOM_API_KEY`).

## Phases
1. Foundation
2. Pipelines
3. Matching and scoring
4. Design system and dashboard on sample data
5. Live data and outreach preview
6. ATTOM owner data and backtest

## Scoring (Phase 3)
Deterministic only: no AI, no randomness (CLAUDE.md AI rules). Config: `config/scoring.yaml` (`model_version` v0.3-handset). Code: `territory/scoring_engine.py` (pure functions), `territory/score.py` (database + CLI), `territory/permit_rules.py` and `territory/permit_rederive.py` (permit groups and the stalled rule), `territory/owner_data/load.py` (owner layer).

Steps, in order: `python -m territory.run ...` (collect) -> `python -m territory.permit_rederive --client <id>` -> `python -m territory.owner_data.load --client <id>` -> `python -m territory.score --client <id>`. Run from `pipelines/`.

- **Residential filter.** Only parcels whose `land_use` is listed under `residential_land_use` in scoring.yaml are scored. The distinct codes are profiled in `pipelines/territory/sources/reports/land_use_profile.csv` (`--profile-land-use`).
- **Suppression.** No score for a parcel with a `sales_history` sale in the last 24 months, or an active `suppressions` row (`until_date` null or not yet passed).
- **Live signals.** A signal is live when `superseded_by is null`. `superseded_by` (new in Phase 3) holds the id of the `permit_rederive` run that superseded the row; replacement rows carry that run id. Signals stay append-only: the only UPDATE the database allows is `superseded_by` going from null to a run id.
- **Components.** One component per signal key (signal type; permits also by group): the most recent live instance. `contribution = weight x 0.5 ** (age_days / half_life_days) x confidence` (the signal's match confidence, recorded as `confidence_multiplier`); static signals do not decay. `tax_default` decays from the date of the notice/list the parcel appears on (`signal_date`); the original default date stays in details and the reason text. Snapshot signals (`stro_license_active`, `sb9_lot_split_estimate`, `sb79_transit_estimate`, `fire_hazard_zone`) count only if the parcel has a row dated on the latest snapshot date for that type, so repeated daily rows never stack. Owner modifiers come from the latest `owners` row (years owned, out of state otherwise absentee, no open mortgage, est. equity at or above the territory 75th percentile). Out of state (+12) and absentee (+10) are not additive, and the total owner-modifier contribution is capped at 30 (over the cap every owner component is scaled by the same `cap_multiplier`).
- **Score.** `min(100, round_half_up(sum(contributions) x stacking))`, stacking = 1 + 10% per signal family beyond the first (financial, rental, permits, upzoning, fire, owner), capped at +30%. A family counts when one of its components has a positive contribution. 
- **scores row.** One row per scored parcel per run (`scored_at` is shared by a run; the table is append-only). `components` is a JSON list; each item has `key`, `family`, `signal_id` or `owner_field`, `raw_weight`, `decay_factor`, `contribution`, `is_sample`, `is_estimate`, source fields (`source_key`, `source_record_id`, `confidence`, `match_method`) and the `facts` the reason text may use. `uses_sample_data` is true when any component is sample-derived. Readers use the `latest_scores` view (most recent row per parcel, `security_invoker` so RLS on `scores` applies).
- **Recipes.** Declarative conditions over the parcel's effective signals and owner fields (`all`/`any`/`not`, signal presence with optional group, `within_days` and detail filters, owner comparisons). `builder_bait` needs an upzoning estimate, `lot_sqft` at least 1.5x the median residential `lot_sqft` of the parcel's planning area (medians are written to `sources/reports/scoring_report.md`) and 20+ years owned. `insurance_squeeze` is active only when fire-zone signals exist; `quiet_inheritance` is `active: false` (requires ATTOM recorder data, Phase 6).
- **reason_text.** Built from the top components only (max 4, by contribution), using only the component `facts`. Permits are shown by the plain-English label in `config/permit_labels.yaml`, never the raw type (a type with no label fails scoring). Sample-derived facts end with "(sample data)", estimates with "(estimated)".
- **Permit groups.** `config/permit_signal_map.yaml` (status reviewed) maps `APPROVAL_TYPE` to group; `APPROVAL_ADU_TOTAL > 0` regroups a permit as `adu`. The discretionary types under `residential_remodel_types` (coastal, site development, use permits, variances, ...) become remodel_addition when the record is residential (parcel land use, or the record's own PROJECT_TYPE/APPROVAL_TYPE). `permit_stalled` counts only for remodel_addition, adu and demolition_lot_split, and only when the permit expired more than 90 days and at most 36 months ago with no close date. The signal natural key includes `signal_group` and `superseded_by`, so a regrouped signal is a new row and a group an approval once had can be live again.


## Phase 5A: data rules, catalog, outreach drafts
Run from `pipelines/`: `python -m territory.export_catalog` (names), `python -m territory.score --client <id>` (re-score), `python -m territory.outreach --client <id> [--channels mail,email,call_task] [--drafts N] [--dry-run]`.

- **Single source of truth for names.** `territory.export_catalog` writes `dashboard/src/data/catalog.generated.json` from `config/scoring.yaml` (recipe labels, short descriptions, score bands), `config/permit_labels.yaml`, `config/signal_labels.yaml` (signal types, groups, score components, families, stages) and the client's recipe toggles (`enabled`). Sentence case, acronyms kept. A test fails if the committed file is stale or a score component has no label. The dashboard reads only this file (Phase 5B).
- **Ownership rule.** `config/transfer_types.yaml` lists the doc types that are a transfer by death, trust or inheritance. If the latest `sales_history` record is one (and the `owners` row shows no later sale), `resolve_tenure` makes the transfer date the current owner's tenure start. The earlier tenure is stored as `prior_owner_years` on a zero-point `owner:ownership_transfer` component and never printed as the current owner's tenure. `SampleOwnerProvider` ends about one parcel in ten with such a transfer and always sets `last_sale_date` to it. The owner loader now appends a corrected `owners` row when the content for the same `as_of` changed (identical rows are still skipped); readers take the newest.
- **reason_text (v0.3).** A phrase is never repeated; same-day permits of one kind merge ("2 building permits ... approved Nov 16, 2026"); a tier prints once ("Tier 3 short-term rental license"); a fact that is both sample and estimated reads "(sample data, estimated)"; years are whole numbers.
- **Outreach drafts (D10, D11).** `territory/outreach.py` takes the top `drafts_per_run` parcels from the latest scoring run that match an enabled recipe, are not suppressed (active `suppressions` row or a sale inside the suppression window) and have no outreach row inside `cooldown_days`. The primary recipe is the enabled matched recipe whose referenced components contribute the most points (ties: config order). Templates: `config/outreach_templates/<recipe>/{letter,email,call_script}.md` (front matter `facts:` names the component keys a text relies on; `general/` is the fallback), rendered by `territory/outreach_render.py`. Salutations come from `territory/salutation.py` (LAST FIRST names, trusts, couples, trustees; anything unreadable, an organization, an estate or a sample name becomes "To the owners of <situs address>,"). Rows are `draft`, or `awaiting_approval` for `approval_required_recipes`; `source_facts` holds exactly the component facts the template relies on plus the owner name when the greeting uses it; `blocked_reason` is "missing agent name or DRE license" (D11) and, for email, "missing office address". Drafts built on sample data start with a visible banner and set `uses_sample_data`. Agents are assigned round-robin over `team_members` with role `agent` (sorted by email; null when there are none). Mode `preview` only writes rows: no sending, no network, no AI.
