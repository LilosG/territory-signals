# CLAUDE.md

## Purpose
Territory intelligence platform for real estate teams. One codebase, a separate deployment per client, and a per-client config in `config/clients/`.

## Phase discipline
- Work only on the current phase. Touch only the paths that phase's prompt allows.
- Every phase ends with tests passing, a commit, and a git tag `phase-N-<name>`.
- Anything out of scope goes into `BACKLOG.md`, never patched on the spot.

## Data rules
- Every signal stores its `source_key`, `source_record_id`, `confidence` and `match_method`.
- Raw records and signals are append-only (never overwritten).
- Sample data always has `is_sample = true` and is never shown unlabeled.
- Estimates (e.g. upzoning eligibility) have `is_estimate = true` and are labeled "estimated" in the UI.

## AI rules
- AI is used only for: extracting fields from unstructured text, resolving ambiguous matches, drafting outreach, and writing trend summaries.
- Scores, counts, dates, equity and eligibility are computed with deterministic code.
- AI output may only use facts present in the database and must cite the source records it used. It never invents facts.

## Privacy and compliance
- Never store STRO host names or phone numbers.
- No automated texts or calls to homeowners.
- Respect each source's terms. Court, capublicnotice and obituary sites are not scraped.

## Stack
- Python 3 pipelines in `pipelines/` (local `.venv`).
- Supabase Postgres with PostGIS (migrations in `supabase/migrations/`).
- Astro + Tailwind dashboard in `dashboard/` (Phase 4).
- Deployed later to Mike's Hetzner server (pipelines) and Vercel (dashboard).
