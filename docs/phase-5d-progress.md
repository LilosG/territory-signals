# Phase 5D progress

Branch: `phase-5d-product-polish`. Last commit: "Phase 5D: WIP data layer" (the dashboard does not typecheck yet).

## 1. What is done

- **Migration** `supabase/migrations/20261120000000_dashboard_5d.sql`, applied to the LOCAL database only (not pushed to the cloud). Adds the materialized `private.scored_parcels` (refreshed by `private.refresh_dashboard_aggregates()`), views `scored_parcels`, `outreach_queue`, `share_links_active`, `source_latest`, and functions `nav_counts`, `leads_list`, `recipe_summary`, `recipe_top_leads`, `off_market_inventory`, `search_leads`, `today_stats`, `recent_signals`, `funnel_by`, `coverage_weekly`. Functions deliberately have no `SET search_path` (it blocks inlining; `search_leads` was 6x slower). Hand-timed as a team member: all under about 125 ms. No Python test for it yet.
- **Data layer** (`dashboard/src/`): `lib/data/types.ts`, `provider.ts`, `index.ts`, `supabase.ts` (full rewrite, territory-aware, uses the new functions), `fixtures.ts` (new methods added, not yet typechecked), `catalog.ts` (source catalog, event/sensitive/trait signal types), `shared.ts` (permit chart excludes "other" with an optional series; designed empty states for all-sample or empty charts), `config.ts` (`requires_data`), `middleware.ts` + `env.d.ts` + `lib/territory.ts` (cookie `ts_territory` -> `locals.territory`).
- **Helpers**: `data/landUse.ts` (land use labels, unknown -> "Residential (code N)"), `lib/present.ts` (reason-text sample/estimate parts, distress phrase stripping, lead headline and chips, same-day permit collapsing, "Ownership transfer" label), `lib/ring.ts` (ScoreRing SVG), `lib/nav.ts` (sidebar groups and count badges).
- **Known loose ends**: nothing else is wired up. Pages, components, API routes and actions still use the old data-layer methods (`getTodayFeed` shape, `getSources`, `LeadSummary.signal_count`, `LeadDetail.signals`, etc.) and will fail `astro check` until Chunk 1 and 2 are done. "New this week" is defined as a selling-relevant event dated within 7 days (permits outside "other", STR removals); note this in BACKLOG.md.

## Chunk 1: data layer completion plus visual system (astro check must pass)

Finish: `fixtures.ts` typecheck, middleware territory cookie (done in code, needs the `/actions/territory` POST that sets it), API routes and actions (`/api/search`, territory-aware `/api/leads` and `/api/map`, bulk approve, bulk share-link create), and the visual system below. Allowed paths: dashboard/, supabase/migrations/ (new files only), tests/ (new tests), BACKLOG.md, DEPLOY.md, ARCHITECTURE.md (dashboard section).

Requirements copied from the original prompt:

> Global: territory switcher at the top of the sidebar (All, La Jolla, Pacific Beach, Mission Beach) that filters every page via a cookie; global search (Cmd+K and a search field) for address or APN, opening the lead brief; signed-in user and sign out at the sidebar bottom. Add the database views/functions these pages need in a new migration with RLS-respecting security_invoker views; keep every query fast on the free tier (index anything you filter on, test timings, target under 500 ms).
>
> Sidebar groups with icons and live count badges:
> - Work: Today; Leads (existing /leads, upgraded with sorting, filters, saved views "Hot", "New this week", "Builder bait"); Outreach (new: tabs Drafts, Awaiting approval, Approved, Call tasks, each with counts; bulk review; blocked drafts explain what's missing); Pipeline.
> - Opportunities: Map; Recipes (new /recipes: one card per enabled recipe with plain description, parcel count, new this week, top 5 leads, link to filtered leads; idle recipes show why they're idle); Off-market (new /off-market: builder-bait and tired-landlord inventory with property facts only, select properties and create a share link for investor or builder clients using the existing share functions).
> - Market: Trends; Reports (new /reports: the newsletter export plus a printable neighborhood market report per neighborhood, both built from the trend views, sample sections clearly marked).
> - Results: Performance (new /performance: funnel by agent and recipe, backtest panel with its Phase 6 empty state, coverage over time: parcels monitored, sources live, signals per week).
> - Admin: Data sources (moved out of settings, friendly), Team (team members and roles from the database, read-only), Settings.

> C. VISUAL SYSTEM (update tokens and components first, then pages; no one-off page styles)
> - Sidebar: deep navy background, white/80% text, grouped section labels in small caps, active item with a soft highlight, count badges, brand block at top with team name and territory switcher.
> - Type: Inter with tighter, consistent scale (display 30/600, h1 24/600, h2 18/600, body 15/400, meta 13/500), tabular numbers everywhere, no heavy 800 weights.
> - Color: keep navy as primary, add one refined accent (muted gold) used sparingly for highlights and "new" markers; semantic good/warning/critical; warm neutral background; cards white with 1px hairline borders, 12px radius, very subtle shadow only on hover.
> - Score: replace the boxed number with a ScoreRing component (circular progress in band color with the number centered), used on cards, lists, map drawer and brief.
> - Polish: skeleton loading states, hover/focus states on every interactive element, consistent icon set and sizes, 8px spacing grid, no clipped or wrapping labels at 1440 and 390 widths.

> A. DATA PRESENTATION RULES (component-level parts of this chunk)
> 2. Lead cards and lists never show life-event or distress chips (ownership transfer, tax default, financial pressure). Those appear only inside the lead brief, in a clearly labeled section.
> 3. Sample labeling: one sample indicator per card or panel (small badge), never "(sample data)" repeated inside sentences. Reason text on cards and briefs strips the inline sample/estimate suffixes and instead marks sample-derived facts with a subtle dotted underline and tooltip; estimates keep a small "est." tag.
> 4. Plain labels for every code: land use codes get labels (add a mapping file in dashboard/src/data/ from the confirmed codes in BACKLOG/land_use_profile; unknown codes show "Residential (code 13)"), empty fields are hidden rather than shown as "—", transfer doc types show "Ownership transfer" (no death wording on screen), prices that don't exist are omitted.
> 5. Charts: any chart whose data is entirely sample or empty shows a designed empty state ("Connects when owner sale history is added in Phase 6" / "Appears after the second weekly license snapshot") instead of a misleading chart. The permit chart excludes the "other" group by default, with a toggle to include it.
> 7. Map: default filter shows parcels scoring 30+ (toggle "Show all parcels"), clusters colored by the highest score inside them and sized by count, individual points sized and colored by score band. The list and map stay in sync with filters and the territory switcher.

## Chunk 2: all pages (Today, Leads, Outreach, Recipes, Off-market, Reports, Performance, Data sources, Team, and reworked Pipeline, Settings and lead brief)

> A. DATA PRESENTATION RULES
> 1. Signal timeline: never show the "other" permit group. Collapse same-day permits on a parcel into one event ("6 permits approved Nov 10, 2026") that expands to the list. Show only events from signal groups that matter for selling.
> 6. Settings / data sources: hide internal steps (permit re-derivation, base layers), show friendly source names, show "Not connected yet" in neutral styling for sources awaiting setup (fire zones), never red unless a configured source actually failed its last run. No developer words (source_runs, RPC, view names) anywhere in the UI.

> C. (page-level parts)
> - Today page: header with greeting and territory; four stat tiles with week-over-week delta and a small sparkline; a "This week by recipe" strip of compact recipe tiles; compact lead cards (score ring, address and neighborhood, one-line headline from the top component, up to 3 key fact chips, status pill, chevron) with the full reason in an expandable line; right rail with Approvals, Call tasks and New signals each limited to 5 with "View all".
> - Lead brief: hero with address, neighborhood, score ring, primary recipe and the one-line headline; key facts row; then tabs Overview, Signals, Owner and property, Outreach, Activity, so the page isn't one long scroll.

Plus every page listed under section B (Information architecture) above: Leads (sorting, filters, saved views), Outreach (tabs with counts, bulk review, blocked drafts explain what's missing), Recipes, Off-market (select properties, create share links with the existing share functions), Reports (newsletter export plus printable neighborhood report per neighborhood, sample sections clearly marked), Performance, Data sources, Team, Settings.

## Chunk 3: verification, docs, deploy

> D. VERIFICATION
> Playwright e2e for the new pages (Outreach approve flow, Recipes links, Off-market share link with no owner data, territory switcher filtering, Cmd+K search). Query timing test for every new view as a team member against the local database (each under 500 ms). astro check zero errors, build:prod succeeds, screenshot script for every page at 1440x900 and 390x844 with no console errors or overflow. Deploy to production with the documented deploy command, then list the pages for Mike to review.
>
> FINISH
> Commit "Phase 5D: product depth and visual refinement", push the branch (no merge, no tag). Print the new navigation, the list of new pages, query timings, test results, the screenshot folder path and the production URL. Then stop.

Also in this chunk: update the existing e2e spec for the new design (Today heading, article count, brief assertions), add a Python timing test under `tests/` (the matview must be refreshed after seeding test data; e2e global-setup needs a builder_bait parcel and a `private.refresh_dashboard_aggregates()` call via psql), update BACKLOG.md, DEPLOY.md and the dashboard section of ARCHITECTURE.md, then `supabase db push --remote --yes` before the production deploy (`cd dashboard && npm run deploy`).
