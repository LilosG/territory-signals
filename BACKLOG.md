# Backlog

Open items carried over from SOURCES.md.

- [ ] **Fire hazard zones (D6):** Mike downloads the OSFM/CNRA statewide LRA layer by hand; ingest in Phase 2. Whether 92037/92109 intersect a zone is unconfirmed (SOURCES.md #6).
- [ ] **Official SB 79 data:** request the City's or SANDAG's SB 79 layer (City lists planning@sandiego.gov). The SANDAG map is draft and viewer-only; the City layer (`webmaps.sandiego.gov`) returned 403 to scripts (SOURCES.md #8b, D7).
- [ ] **DOCTYPE code dictionary:** confirm `DOCTYPE` (and `DOCDATE` meaning) with SanGIS/Assessor documentation. Also unconfirmed: `ASR_LANDUSE`/`ASR_ZONE` code meanings (SOURCES.md #7, D8).
- [ ] **capublicnotice permission request:** Mike sends a written permission request to capublicnotice/CNPA (D1, SOURCES.md #4).

Added during Phase 1:

- [x] **Dependencies not in requirements.txt** (done in Phase 2, every package pinned): Phase 1 installed `pytest`, `pydantic`, `psycopg[binary]` and `pyyaml` into `.venv`; `requirements.txt` was outside the allowed paths, so it was not updated. Pin them there next phase.
- [x] **Append-only enforcement** (done in Phase 2: triggers on raw_records, signals, owners, sales_history; unique key on signals): `raw_records`, `signals` and `owners` are append-only by convention only; no DB trigger blocks UPDATE/DELETE yet. Decide whether to add one.
- [ ] **Outreach modes:** `config.py` accepts only `outreach.mode: preview`; extend in Phase 5.
- [x] **`team_members` config shape** (done in Phase 5A: name, email, role, dre_license, phone; list may be empty).

Added during Phase 2:

- [ ] **STRO first run is a baseline:** the first `stro_licenses` run produces no `stro_license_removed` signals (nothing to compare with). Removals start with the second run. The City file has no issue date, so license age is still unknown.
- [x] **Permit type map needs Mike's review** (finalized in Phase 3 from the Phase 3 rules, status `reviewed`; changes in `permit_map_changes.md`; see the Phase 3 items below for what Mike should still check): `config/permit_signal_map.yaml` is `status: proposed`. Every one of the 147 territory `APPROVAL_TYPE` strings is mapped (81 to `other`). No approval type is ADU: ADU work appears as Building / Combination Building permits with `APPROVAL_ADU_TOTAL > 0`, so the `adu` group is empty until Phase 3 splits it using `adu_total`, which is kept in signal details.
- [x] **`permit_stalled` is noisy** (done in Phase 3: only remodel_addition/adu/demolition_lot_split, expired more than 90 days, no close date; existing rows superseded): the data has `APPROVAL_EXPIRE_DATE` and `APPROVAL_CLOSE_DATE`, so the signal is built (expired, never closed, status not terminal). Many short-lived permit types (traffic control, right-of-way, no-plan trades) expire without ever being closed, so Phase 3 should weight or restrict by `signal_group`.
- [ ] **Permit scope:** ingested the full `active` file plus the 2025 and 2026 files of `issued`, `closed` and `created` (the full issued/closed/created history files, 400-680 MB each, are not ingested). Older closed permits are therefore absent. `APPROVAL_PERMIT_HOLDER` (a person/business name) is dropped on read.
- [ ] **Permits that cannot be placed:** approvals with a blank/unknown APN, no coordinates and no address match cannot be assigned to the territory; they are counted in `dev_permits_match_report.md` and not stored.
- [ ] **Parcel fields not loaded:** `year_built` stays null (SanGIS only has the two-digit `YEAR_EFFECTIVE`, which is not a year built). `lot_sqft` is `USABLE_SQ_FEET` when real, else the polygon area, else null for stacked condo footprints shared by several APNs (counts in `parcels_load_report.md`). `DOCDATE` values that are not a valid MMDDYY date (including `000000`) are stored as null and counted in that report.
- [ ] **Parcels come from the SanGIS shapefile download**, not the CSV: the CSV has no geometry, and the shapefile carries the same attribute columns.
- [ ] **SB 9 screen excludes planned districts:** only the `RS-*` base zones are screened. `LJSPD-SF` (La Jolla Shores single-family) and the other planned-district zones (`LJPD-*`, `MBPD-*`) need rule-by-rule treatment per SOURCES.md; decide whether `LJSPD-SF` counts as single-family for SB 9. Parcels in RS zones with no `lot_sqft` are skipped.
- [ ] **SB 79 screen is a proxy:** the GTFS stop file has no frequency or dedicated-lane data. Rail = GTFS parent stations on a rail/trolley line; BRT = stops within 100 ft of an MTS Rapid route shape (Super Loop excluded), so local stops on shared corridors are included. Replace with the official City/SANDAG layer when received (D7).
- [x] **Snapshot signals repeat by run date** (done in Phase 3: scoring counts only the latest snapshot per signal type): `stro_license_active`, `sb9_lot_split_estimate`, `sb79_transit_estimate` and `fire_hazard_zone` use the run date as `signal_date`, so a rerun on a new day adds a new row per parcel. Phase 3 scoring must read the latest per (apn, signal_type).
- [ ] **Raw records grow each run:** `raw_records` is append-only and every run stores its in-scope rows again (about 54,000 permit rows per run). Revisit (store only changed payloads) before scheduled daily runs.
- [ ] **Tax-default list is annual:** the URL is pinned to the June 2026 notice; update `URL` in `tax_default.py` each June. The parser splits each page at the middle (the notice prints two columns); re-check if the layout changes. Auction notices (7102: 10 parcels in the two ZIPs) are not ingested.
- [ ] **Base layers do not write `raw_records`:** planning areas, parcels and zoning are loaded straight into their tables (idempotent upserts); the dated files in `data/raw/` are the raw copy.
- [ ] **Polite-access identity:** downloads use the generic User-Agent `territory-signals-pipeline/2.0` with no contact address. Add a contact email if a host asks for one.
- [ ] **Fire hazard zones:** `fire_zones` is built and tested but waits for Mike's manual download into `data/manual/fhsz/` (D6); the run is recorded as failed with "awaiting manual download" until then.
- [ ] **Run location:** `python -m territory.run` must be run from `pipelines/` (or with `PYTHONPATH=pipelines`); README.md is outside Phase 2's allowed paths, so it was not updated.

Added during Phase 3:

- [ ] **Review the permit map judgment calls** (checkpoint: the discretionary types now move to remodel_addition on residential records, listed in `permit_map_changes.md`; grading and the rest of this item still stand): under the Phase 3 rules, discretionary land-use approvals (Coastal Development, Site Development, Conditional/Neighborhood Use, Variance, Planned District, historic nominations) and every grading type moved from `remodel_addition` to `other` (they do not name a dwelling remodel or addition), and Certificate of Compliance / Zone History Letter moved from `pre_sale_prep` to `other`. In La Jolla, Pacific Beach and Mission Beach many remodels need a Coastal Development Permit, so Mike may want those back in `remodel_addition`. `Electrical`, `Plumbing` and `Mechanical` permit types do not say residential or commercial and stay in `pre_sale_prep` (only residential parcels are scored). Full list: `permit_map_changes.md`.
- [ ] **Land-use codes are inferred, not confirmed:** the residential codes in scoring.yaml (11 single-family, 17 condo, 12 duplex, 13 triplex/fourplex, 14 small multifamily) were chosen from the unit counts in `land_use_profile.csv`, because the `ASR_LANDUSE` dictionary is still unconfirmed (SOURCES.md #7). Not scored and worth checking: 10 (0 units, probably vacant residential, 436 parcels), 86 and 88 (389 parcels, mostly La Jolla RS zones, meaning unclear), 15 (median 21 units, large multifamily).
- [ ] **All owner-based points are sample data:** until ATTOM (Phase 6) every owner modifier (years owned, absentee, out of state, no mortgage, equity) and every sale-based suppression comes from `SampleOwnerProvider`, so `uses_sample_data` is true for almost every score and the ranking is not meaningful for outreach yet. The 325 parcels suppressed for a "sale within 24 months" are suppressed by sample sales.
- [ ] **Recipe and weight definitions need Mike's review:** the weights and half-lives are from the prompt; the recipe conditions (for example tired_landlord = absentee + 15 years + a distress signal, builder_bait = upzoning estimate + 20 years or absentee, pre_list_prep = pre-sale permit in the last 180 days + 10 years, downsizer = owner-occupied, 20 years, no mortgage) are my reading of the names and are explicit in `config/scoring.yaml`.
- [ ] **`str_exit` matches nothing yet:** `stro_license_removed` needs a second `stro_licenses` run (the first run is a baseline), so the recipe and the 25-point signal are idle until then.
- [ ] **Fire class strings are unverified:** scoring matches `hazard_class` as "very high", "high" or "moderate" (case-insensitive, underscores as spaces). Confirm against the real column values when Mike's file is loaded; an unrecognized class scores 0 and does not trigger `insurance_squeeze`.
- [x] **Re-derivation edge case** (fixed in the Phase 3 checkpoint: the natural key now includes `superseded_by`, so a group an approval once had gets a fresh live row; tested): a group change is a new row (the natural key includes `signal_group`). If the map later changes a type back to a group it once had, the insert hits the old superseded row and does nothing, leaving no live row for that approval. Handle with a "reinstate" path if the map changes again.
- [x] **Scores history has several runs in the working database** (the `latest_scores` view, added in the Phase 3 checkpoint, returns the newest row per parcel): one run before the reason-text wording was finalized, one after. Readers (dashboard, outreach) must take the latest `scored_at` per parcel.
- [ ] **One component per signal key** (confidence is now a multiplier, checkpoint item 7): a parcel with several permits in the same group scores the most recent one once. `confidence` is recorded but not used as a multiplier. Revisit in the Phase 6 backtest.
- [x] **`tax_default` decay date** (checkpoint: decays from `signal_date`, the notice's power-to-sell date of 2026-07-01 from the June 2026 notice; the default date 2021-06-30 stays in details and the reason text. The source file has no separate notice-issue date): the signal date is the Notice of Impending Power to Sell date (June 2026 list), so the decay starts there, while the reason text shows the tax-default date. Confirm which date should drive recency.
- [ ] **Sale suppression uses `sales_history` only:** `owners.last_sale_date` is not checked separately (the two agree for sample data). Revisit with ATTOM.
- [ ] **Killed first repopulation run:** the first `--source all` attempt was stopped and restarted to get a clean "before" baseline on the proposed map; its `dev_permits` row in `source_runs` is marked failed ("interrupted: ...").

Added during the Phase 3 checkpoint:

- [ ] **Permit labels need an agent's read:** `config/permit_labels.yaml` has a short label for every one of the 147 types. Scoring stops with an error if a type has no label, so a new `APPROVAL_TYPE` in a future file needs a label before scoring runs.
- [ ] **Residential flag for permits:** a record counts as residential when its parcel has a residential land-use code or its own `PROJECT_TYPE` / `APPROVAL_TYPE` says residential. `PROJECT_TYPE` is only present on some records, so most moves rely on the parcel land use.
- [ ] **Stalled window:** stalled permits are now only those that expired in the last 36 months, so the count depends on the run date and falls as the data ages. Re-run `territory.permit_rederive` before each scoring run.
- [ ] **Owner modifier cap scales proportionally:** over 30 points, every owner component is scaled by the same factor, so the reason text shows the highest raw components first. Change to drop the smallest modifiers instead if preferred.


Added during Phase 5A:

- [ ] **Mike must supply real agent data before any draft can be approved (D11):** `team_members` (name, email, role, DRE license, phone), `team_profile.brokerage` and `team_profile.office_address` are empty in `kaiser-team.yaml`. Until then all 50 working-database drafts carry `blocked_reason` "missing agent name or DRE license" and have no `assigned_to`; emails also need the office address. Confirm with the broker whether solicitation material must also show the brokerage name or license (the templates print the brokerage when configured).
- [x] **Dashboard `catalog.ts` is stale** (done in Phase 5B: it reads `catalog.generated.json` only; original note:) `dashboard/src/lib/data/catalog.ts` still has its own signal names (`upzoning_sb9`, `long_tenure`, ...), recipe keys that do not exist in scoring.yaml (`long-tenure-equity`, ...) and hard-coded score bands (80/60/40). Phase 5B must replace it with `catalog.generated.json`. The band thresholds now live in `config/scoring.yaml` (`score_bands`) and are copied into the catalog; nothing in `dashboard/` outside the generated file was touched.
- [x] **Sample-data drafts are labeled, not blocked** (done in the 5A corrections: they now carry blocked_reason "sample data" and no label in the text; original note:) a draft built on sample owner data starts with "[SAMPLE DATA ... Do not send.]" and sets `uses_sample_data`, but the only things that block approval are the D11 and office-address rules. Its mailing address is a fake sample address. Decide whether sample drafts should also be unapprovable (a one-line `blocked_reason`).
- [ ] **Transfer doc types are placeholders:** `config/transfer_types.yaml` lists generic names ("trust transfer deed", "affidavit of death of joint tenant", ...). Replace with the real ATTOM/recorder document codes in Phase 6. `quiet_inheritance` stays off until then (D1).
- [x] **Transfers now trigger the 24-month sale suppression** (done in the 5A corrections: only arm's-length sales suppress; transfers are recorded as `ownership_transfer` signals for Phase 6; original note:) suppression reads every `sales_history` row, so a recent death/trust/inheritance transfer suppresses the parcel (399 suppressed instead of 325 after the sample change). Decide whether a transfer should suppress, or whether it should become a quiet_inheritance lead instead.
- [ ] **Channel policy:** the generator defaults to `mail` (the only channel with contact data: a mailing address). Email and call-task drafts have no recipient address or phone because no source supplies them; they are produced only with `--channels`. Decide the real channel rule once owner contact data exists.
- [ ] **Mailing address fallback assumes San Diego:** when no owner mailing address differs from the situs, the mailing line is `<situs>, San Diego, CA <zip>`. Make the city/state a client config field when a client outside San Diego is added.
- [ ] **Salutation coverage:** names that are not all upper case, have a first+middle name ("SMITH MARY ANN"), co-owners with different surnames, "ET AL"/"ET UX" or any organization fall back to "To the owners of <situs>,". Check the real ATTOM name formats in Phase 6 and extend the formatter from real examples. A trustee with no trust name prints "Dear Trustee John Smith," (no trust name is invented).
- [ ] **Neighbor wording has no config switch:** the brief allows "neighbor" only if config says so; no such key exists, so no template uses it. Add a team_profile flag if a client wants it.
- [ ] **`weekly_send_cap_per_agent` and `due_date` are unused:** nothing sends in preview, so the cap has no effect yet and the generator leaves `due_date` empty. They are for Phase 5B/6.
- [ ] **Funnel is empty until something writes `stage_events`:** neither the generator nor the dashboard writes them yet. `funnel_by_recipe` now counts each parcel once under its primary recipe (stored in `scores.primary_recipe`) and only uses the latest score row; parcels scored before the correction have no primary recipe until re-scored.
- [ ] **Recipe choice is a rule of thumb:** the primary recipe is the one whose referenced components add the most points; ties go to the order in scoring.yaml (for example a parcel with a removed STR license and an open mortgage ties str_exit and financial_pressure and gets str_exit). Revisit after the Phase 6 backtest.
- [ ] **source_facts leave out parcel fields:** the situs address and neighborhood used in the text come from `parcels` and are not listed in `source_facts` (the brief asks for component facts and owner fields only).
- [ ] **Awkward plural fallback:** a same-day count on a label that cannot be pluralized reads "2 permits for change to a building permit". Add plural forms to `permit_labels.yaml` if it shows up in real reason text.
- [ ] **Owner rows can now repeat per `as_of`:** the loader appends a corrected owner row for the same `as_of` when content changed (needed after the sample-data change). Readers already take the newest row; if this grows, add a `superseded` marker or a unique key.
- [x] **`.gitignore` hid the generated catalog** (fixed in the 5A corrections: the pattern is now `/data/`).

Added in the Phase 5A corrections:

- [ ] **Comparable-sale numbers (Phase 6):** the templates promise "what comparable homes nearby have sold for" and a value summary but carry no figures, and make no market claims, until sourced numbers exist in `source_facts`.
- [ ] **Tax wording needs the broker's or an adviser's sign-off:** the tired_landlord (1031 exchange) and downsizer (Prop 19, owners 55 and over) letters mention these only as things to confirm with a tax advisor. Have a licensee review the exact wording.
- [ ] **Templates assume the offer is deliverable:** every letter offers a value summary; nothing generates it yet.
- [ ] **`ownership_transfer` signals have no run id:** the owner loader writes them without a `source_runs` row (source_key `<provider>_sales_history`). Add a run record when ATTOM recorder data arrives.
- [ ] **Old drafts were deleted and regenerated:** the 50 working-database drafts from the first 5A pass were removed (they were unsent previews) so the new templates could replace them under the cooldown rule.


Added during Phase 5B:

- [ ] **Recipe-to-signal mapping is not in the catalog:** the old dashboard hid signal chips a recipe already implied. `catalog.generated.json` has no such mapping, so lead cards show recipe tags and signal chips side by side. Add `components` per recipe to `export_catalog` if the redundancy matters.
- [x] **npm audit (resolved in 5C):** the `path-to-regexp` override existed only for `@astrojs/vercel`; the adapter is now `@astrojs/cloudflare`. The override is still in `package.json`; remove it once `npm audit` is confirmed clean without it.
- [ ] **`typescript` stays on 5.9.3:** TypeScript 7 is released but `@astrojs/check` / Volar are not verified against it yet.
- [x] **Client config (resolved in 5C):** `config/clients/*.yaml` is now bundled into the Worker at build time (`import.meta.glob`), because Workers has no filesystem. Changing a client config therefore needs a rebuild and redeploy. `CLIENT_CONFIG_PATH` was removed.
- [ ] **Email rate limit locally:** the local Supabase auth allows only a few sign-in emails per hour; the e2e login test skips itself when limited. Production now uses Gmail SMTP (Phase 5C); see `DEPLOY.md`.
- [ ] **Share page has no address by design;** agent phone comes from `team_members[].phone` in the client config (empty until Mike supplies it).
- [ ] **No first-run funnel data:** the funnel stays empty until outcomes are recorded. `record_stage` writes a `signal` stage entry (source system) the first time a parcel gets an outcome.
- [ ] **"New since yesterday" is every signal on a first load:** all 75k signals were detected in the first pipeline run, so the feed shows the most recently dated ones. It becomes a true daily delta after the second run.
- [ ] **Map loads all scored parcels (about 26k points, ~3 MB JSON)** per filter change, as specified. If it feels slow on Cloudflare Workers, switch to vector tiles or bbox queries.
- [ ] **Pipeline "By recipe"** counts each parcel under its primary recipe only (the funnel view); parcels with no primary recipe are in the overall funnel but not in a recipe row.


Added during Phase 5C:

- [ ] **Move pipelines to the Hetzner VPS on a weekly schedule.** Today the pipelines run from Mike's laptop against the local database; refreshing the cloud data is a manual dump and restore (see `DEPLOY.md`). The VPS job should write straight to the cloud project with `SUPABASE_DB_URL`.
- [ ] **Custom domain on Cloudflare** instead of `kaiser-team-signals.mike-1d7.workers.dev`. When it changes, update the Supabase Auth site URL and redirect URLs too.
- [ ] **Workers Paid plan for production.** The free plan has a 10 ms CPU limit per request; heavy pages (map, trends) may exceed it. See the smoke-test findings in `DEPLOY.md`.
- [ ] **Supabase plan check.** The cloud project is on the free plan: free projects pause after about a week of inactivity, and the database limit is 500 MB (the data is about 350 MB, so there is little room for growth, raw records especially). Upgrade to Pro before real use.
- [ ] **Gmail SMTP is a stopgap.** Gmail caps sending (about 500 per day) and ties production auth email to one mailbox's app password. Move to a transactional provider (Resend, Postmark) with a verified domain.
- [ ] **`CLAUDE.md` still says "Vercel (dashboard)"** in its Stack section. It was outside Phase 5C's allowed paths; change it to Cloudflare Workers.
- [ ] **Production builds use `scripts/build-prod.mjs`.** The Cloudflare adapter reads `dashboard/.env` ahead of `.env.production`, so the script swaps the local `.env` out during the build. Revisit if the adapter's env loading changes.
- [ ] **Cloud copy of `team_members`** came across in the data copy (1 row); the production list is managed with `seed_team` (see `DEPLOY.md`).
- [ ] **Dashboard queries are heavy for a small instance.** Found in Phase 5C: `latest_scores` (a `DISTINCT ON` over all 131k score rows) made `leads_page` take 12-14 s on the cloud project, past the 8 s `authenticated` statement timeout (HTTP 500 on `/`). Fixed in migration `20261119000000_latest_scores_perf.sql` (index + one probe per parcel). Still the slowest on the cloud project (as the signed-in role): `leads_page` with the signal-group filter (~4 s), `trend_upzoning_by_hood` (~1.7 s), `trend_signals_monthly` (~1.6 s), `map_points` (~1.2 s). Consider a `latest_scores` table maintained by the scoring pipeline, and computing `total` separately from the page in `leads_page`.
- Refresh of the trend tables is automatic after pipeline loads (done). Still manual after a raw `pg_dump` restore.
- [ ] **`/api/map` payload is ~5 MB raw (about 26k features).** It is built in SQL and compressed by Cloudflare, but a score threshold, bounding-box queries or vector tiles would cut it. Also trim the `neighborhood` / `primary_recipe` properties the map does not use.

Added during Phase 5D:

- [ ] **"New this week" definition.** A lead is "new this week" when it has a selling-relevant event dated within the last 7 days (an approved permit outside the "other" group, or a removed short-term rental license). Tax default and ownership transfer never count. Revisit if the team wants "newly scored" instead.
- [ ] **Bulk actions are capped at 50 and run one database call per item** (`approve-bulk`, `share-bulk`). Fine for a team's queue; move to a set-based function if queues grow.
- [ ] **Map default of 30+** is applied in `/api/map` and `/api/leads` (query param `all=1` turns it off). The 5 MB payload item above shrinks a lot with it; re-measure on the cloud project.

## Phase 5D Chunk 2 notes
- Recipes page leaves out the distress recipes (financial_pressure, quiet_inheritance) on purpose; decide whether the team wants a labeled, permissioned view for them.
- Today stat tiles use the last 14 days of signals, drafts, outcomes and active leads; fixtures data is older than that so tiles read zero in demo mode.
- Outreach "Approve selected" runs one database check per draft (capped at 50); a single batch function would be faster if queues grow.
- Reports are print-to-PDF pages; no generated PDF files yet.

## Phase 5D Chunk 3 notes
- [ ] **Refresh `private.scored_parcels` after every scoring run.** It is a materialized view, so the lists, search and counts show old scores until `select private.refresh_dashboard_aggregates();` runs. Call it at the end of the scoring pipeline (and the weekly VPS job).
- [ ] **Search by APN matches digits only** (real APNs are numeric); a non-numeric APN is found by address only.
- [ ] **Cmd+K dialog** now closes on Escape through its own handler (the browser's built-in close needed a fresh user gesture in automated tests).
- [ ] **Playwright tests that page through Outreach and Off-market** walk up to 40 pages to find the seeded rows; add a search box to those pages if the lists keep growing.
- [ ] **Screenshots** are saved in `dashboard/screenshots/` (git-tracked); consider git-ignoring them if the repo grows.


Added during Phase 5F:
- [x] **(done in Phase 5G, D14: permits are now grouped by description; see `docs/reports/presale-reclass.md`)** **`pre_sale_prep` permit group vs AI intent:** only 1.3% of these permits (furnace, heat pump, water heater, panel work) read as "prep to sell" to the AI; 66% read as maintenance (`docs/reports/permit-intent-agreement.md`). Decide whether to re-weight or rename the group. Shadow data only; nothing changed.
- [ ] **permit_intent throughput:** gpt-oss-20b is a reasoning model; 8-permit batches and 32 workers run at about 400 permits a minute with a long tail of slow calls. Consider an explicit timeout of 120 s for it, or a non-reasoning model.
- [x] **(done in Phase 5G: retry with the reason, then a fallback model)** **lead_brief returns empty output for some parcels** (4 of the first 25 with deepseek-v4.1-flash: no claims). They are rejected and not shown; consider a retry on empty output.
- [ ] **config/llm_pricing.yaml is empty:** add Anthropic prices before switching a client to the anthropic provider, or its cost is recorded as unknown.
- [ ] **Weekly brief baseline:** with scoring runs only on 2026-11-18 locally, "top movers" compare the first and last run that day and mostly show scoring-model changes. It becomes meaningful once weekly scoring runs exist.

Added during Phase 5G:
- [ ] **Permits with no description default to `maintenance`.** About a third of the old `pre_sale_prep` group had no scope text of its own; unless the project title or scope supplies one, they now carry no weight. Real prep work filed without a description is under-counted. Revisit with ATTOM or a text field from the City if one appears.
- [ ] **Permit text rules are regexes** (`presale_rules` in `config/permit_signal_map.yaml`). They were tuned on about 400 reads; add a regression sample (counts per group) to the permit re-derivation report so drift is visible.
- [ ] **permit_intent still runs on the old text only** (scope, else job description); the pre-sale rules also read the project title and scope. Align them if permit_intent ever drives scores.
- [ ] **Lead-brief eval is small (15 cases):** one miss is 7 points, so the 90% bar is noisy; run it twice before switching models.
- [ ] **Weekly brief has no movers in the first week after a scoring-model change** (it compares only runs of the same `model_version`). It fills in from the next weekly run.
- [ ] **"First full week" on Today** uses the first pull of the sources feeding a tile (`today_stat_history`). If a source is re-pulled from scratch the tile will say it again for that week.

Added during Phase 5H:

- [ ] **Top-3 tie at the SQL boundary:** `leads_list` returns the three largest signal components ordered by contribution only. The dashboard breaks ties by most recent date, but a 4-way tie for the top contribution could still hide the newest one. Add `signal_date desc` as the second sort key in the next migration.
- [ ] **Lead briefs with changed facts after v0.4.1:** briefs whose packet changed are regenerated by the next `lead_brief` run (3 locally); until then a changed parcel (for example 1505 Felspar St) shows the older brief text.
- [ ] **Weekly brief newsletter minimum:** the 60-90 word newsletter check can push a model to filler when facts are thin; consider a lower minimum when `new_this_week` is empty.

Added during Phase 5I:

- [ ] **Few parcels reach 70+ under v0.5** (31 of 26,268) because owner data is sample data and few parcels carry three or four independent families. Re-check the band spread, and whether Hot (80+) is large enough, when ATTOM owner data (D9) replaces the sample.
- [ ] **Pipeline GCI uses one flat rate** (2.5% of the owner's estimated value, sample until ATTOM). Make the rate a client config value and use the sale-price estimate when ATTOM provides one.
- [ ] **Financial pressure cards show no line under each lead** (its qualifier, tax default, is sensitive and never shown on cards). Decide on a neutral phrase such as "Approval required" per row, or leave blank.
- [ ] **Trends takeaway does not change with the "Include routine & other permits" toggle** (the sentence is the default, actionable-only view). Make it follow the toggle if the chart is shared.
- [ ] **E2E lead-list tests depended on the old score compression** (the test parcel scored 55 and sat on page 1). The test now filters with `?q=E2E`; other tests that read page 1 of unfiltered Leads may need the same.
- [ ] **Map lens values in SQL** (Phase 5J): add est_equity, SB 9/SB 79 flags and an active-STR flag to `map_geojson` so `/api/map-lens` (about 50 paged REST calls, fine locally, heavy on a Worker) can go away. Needs a migration.
- [ ] **Today "top" counts use today's top-leads list only**: the Active strategies panel counts leads scoring 65+ among the top leads shown, not all parcels. Add a per-recipe high-score count to the recipe strip RPC.
- [ ] **Build warning**: the MapLibre bundle exceeds Vite's 500 kB chunk limit (present before Phase 5J). Set `build.chunkSizeWarningLimit` or split the chunk (astro.config.mjs).
- [ ] **Net-proceeds cost range is a flat 5-7%**: make it a client config value.
- [ ] **Lead page: mobile order.** The co-pilot sits below the whole left column on a phone; consider a sticky "Log outcome" bar.

Added during Phase 5K:

- [ ] **`fire_zones` has no automated source.** The weekly run reports it as `awaiting manual download` and continues; the digest shows the gap in source health. Automate the CalFire FHSZ download when a stable URL exists (D6).
- [ ] **Digest GCI uses the flat 2.5% rate** hard-coded in `digest.py` (matching the dashboard's `estGci`). Move it to the client config together with the pipeline GCI rate.
- [ ] **Digest lead links assume the production dashboard URL.** Make the base URL a client config value (or `DASHBOARD_BASE_URL`) so a second client's digest points at its own Worker.
- [ ] **Weekly digest AI briefs are shared with the dashboard.** The digest shows the latest valid `weekly_brief`; if the AI stage is skipped or over budget, the digest falls back to deterministic signal counts only. Consider a deterministic newsletter fallback.
- [ ] **No retry/alert on a failed weekly run.** A failed stage stops the run and systemd records the failure; nothing emails Mike. Add `OnFailure=` (a mail unit or a healthcheck ping).

Added during Phase 5L:

- [ ] **The public code enforcement extract is historical (2015-2018).** `data.sandiego.gov/datasets/code-enforcement-violations/` was last updated in January 2018; there is no current bulk feed on the portal. The adapter is correct for the same field set, but current open/closed cases will not appear until a live source is confirmed (City Get It Done/311 case data under its own terms, or a Development Services arrangement). Tracked with SOURCES.md #11.
- [ ] **Code enforcement endpoint fallback is a cache, not a subscription.** When the CSV is unreachable the adapter uses the newest file in `data/raw/code_enforcement/`, else the packaged `pipelines/territory/sources/fixtures/code_enforcement_fallback.csv`, and reports the fallback; refresh the cache by hand if the endpoint moves.
- [ ] **Portfolio clustering is exact-match only.** It groups an exact normalized mailing address or an exact normalized corporate/trust name; it does not fuzzy-match "SMITH JOHN" and "JOHN SMITH", "123 Main St" and "123 Main Street", or entities with slightly different names. ATTOM owner data in Phase 6 may need entity-name normalization and a review queue before portfolios drive outreach.
- [ ] **Portfolio totals depend on sample owner values until Phase 6.** `total_est_value` and `total_est_equity` sum the current `owners` rows, which are sample data today; the dashboard labels them "est." and "Sample", but the numbers are not decision-grade yet.
- [ ] **No portfolio-level dashboard view yet.** The badge is per parcel; a dedicated portfolio page (all parcels under one `portfolio_key`, combined value, outreach status) would make the moat usable by an agent.
- [ ] **Code violation categories are the source's raw abbreviations** ("GARAGE CONVERSN", "BOARDED STRUCTUR"). Add a plain-English category map if the details are shown in more places.
