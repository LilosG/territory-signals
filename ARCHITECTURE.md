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
- **outreach**: id, apn -> parcels, channel (mail|email|call_task), status (draft|awaiting_approval|approved|sent|suppressed), content, source_facts jsonb, approved_by, sent_at
- **outcomes**: id, apn -> parcels, team_member_email, status (contacted|conversation|appointment|listing|not_interested|bad_data), noted_at, note
- **team_members**: id, email (unique), name, role (owner|agent|assistant)

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
