# Deploying the Kaiser Team dashboard

| Piece | Where | Name |
|---|---|---|
| Dashboard | Cloudflare Workers | `kaiser-team-signals` → https://kaiser-team-signals.mike-1d7.workers.dev |
| Database + Auth | Supabase cloud (West US, North California; free plan) | project `territory-signals-kaiser`, ref `ukpfksabatofcczdrphm` |
| Pipelines | Mike's laptop for now (Hetzner VPS later, see `BACKLOG.md`) | `pipelines/` |

The Worker holds only public values (Supabase URL and anon key) and `DATA_PROVIDER=supabase`. It has no service-role key. Every read runs as the signed-in user under RLS.

## Where each secret lives

| Secret | Location | Notes |
|---|---|---|
| Cloud database password | macOS Keychain, service `territory-signals-kaiser-db`, account `mike` | `security find-generic-password -a mike -s territory-signals-kaiser-db -w` |
| Gmail app password (`SMTP_PASS`) | macOS Keychain, exported into the shell environment by the shell profile | Used only when pushing Auth config. Supabase stores its own copy for sending (write-only; the API never shows it). |
| Supabase access token | Supabase CLI login (`supabase login`) | |
| Cloudflare login | Wrangler OAuth (`npx wrangler login`) | |
| Supabase URL + anon key | `dashboard/deploy-env/.env` (gitignored) | Public by design (RLS protects the data), but kept out of git. Copy from the Supabase dashboard → Project Settings → API. |
| Service-role key | Nowhere in this setup | Not used by the Worker or by `seed_team`. |

Never commit, print or log any of these.

## Redeploy the dashboard

```bash
cd dashboard
npm run build:prod      # builds with the cloud values from deploy-env/.env baked in
npx wrangler deploy
```

Or `npm run deploy`, which does both. Do not use plain `npm run build` for a deploy: it bakes in the local `.env` (localhost URLs).
`build:prod` temporarily moves `dashboard/.env` aside and always restores it.

Client config (`config/clients/<id>.yaml`) is bundled at build time, so a config change also needs a redeploy.

The build copies MapLibre's web worker to `public/maplibre/` (`scripts/copy-maplibre-worker.mjs`, run by `build`, `build:prod` and `dev`). Without it the map stays blank (the worker 404s). It is git-ignored; do not delete the script.

Local checks before deploying: `npm run build`, then `npx wrangler dev --ip 127.0.0.1 --port 3000` (uses the local Supabase), then `npm run e2e`.

### Phase 5D release steps (database first, then the Worker)

```bash
supabase db push --remote --yes          # applies 20261120000000_dashboard_5d.sql to the cloud project (without --remote it targets the LOCAL stack)
psql "$CLOUD_DB_URL" -c "select private.refresh_dashboard_aggregates();"   # fills the scored_parcels materialized view the lists read
cd dashboard && npm run deploy
```

The migration only adds objects (a materialized view, views, functions, indexes); it changes no existing table. The materialized view `private.scored_parcels` must be refreshed after every pipeline load that changes scores (`select private.refresh_dashboard_aggregates();`); the lists, search and navigation counts read it. Pages new in 5D: Outreach, Recipes, Off-market, Reports, Performance, Data sources, Team.

Local checks for 5D: `npm run check`, `npm run e2e` (seeds two synthetic parcels and removes them again), `npm run screenshots` (every page at 1440x900 and 390x844, fails on console errors or horizontal overflow), and `pytest tests/test_dashboard_timing.py` (each new view under 500 ms as a team member).

## Refresh the cloud data from the local database

Pipelines run against the local Supabase. To publish the result to the cloud:

1. Run the pipelines locally as usual.
2. Dump the local public data, and restore it into the cloud. Existing rows and the append-only triggers mean a plain restore over a populated database fails on duplicate keys. For a first load or a full refresh, restore into an emptied schema (ask before truncating: raw records and signals are append-only by design). For incremental updates, run the pipelines directly against the cloud database instead:

```bash
export SUPABASE_DB_URL="postgresql://postgres:$(security find-generic-password -a mike -s territory-signals-kaiser-db -w)@db.ukpfksabatofcczdrphm.supabase.co:5432/postgres?sslmode=require"
cd pipelines && ../.venv/bin/python -m territory.<pipeline module> ...
```

Initial load (already done, 2026-11-18):

```bash
pg_dump "postgresql://postgres:postgres@127.0.0.1:54322/postgres" --data-only --schema=public --no-owner --no-privileges -f public_data.sql
PGPASSWORD=$(security find-generic-password -a mike -s territory-signals-kaiser-db -w) \
  psql "host=db.ukpfksabatofcczdrphm.supabase.co port=5432 user=postgres dbname=postgres sslmode=require" \
  -v ON_ERROR_STOP=1 --single-transaction -f public_data.sql
```

The `auth` schema is never copied. After any load, compare row counts per table between local and cloud.

**Trend tables refresh automatically.** The pipeline runner (`territory.run`, `permit_rederive`), `territory.score` and `territory.owner_data.load` call `private.refresh_dashboard_aggregates()` after each successful load, against whichever database `SUPABASE_DB_URL` points at. A failed refresh only prints a warning (the load is already committed). If you load data some other way (for example a `pg_dump` restore), refresh by hand:

```bash
PGPASSWORD=$(security find-generic-password -a mike -s territory-signals-kaiser-db -w) \
  psql "host=db.ukpfksabatofcczdrphm.supabase.co port=5432 user=postgres dbname=postgres sslmode=require" \
  -c "select private.refresh_dashboard_aggregates();"
```

Database size: the free plan allows 500 MB; the data is about 350 MB.

## Schema changes

Add a migration in `supabase/migrations/`, test it locally, then:

```bash
supabase db push --remote --yes     # without --remote it targets the LOCAL stack
```

## Add a team member

Only emails in `team_members` can sign in (enforced in the database).

```bash
cd pipelines
export SUPABASE_DB_URL="postgresql://postgres:$(security find-generic-password -a mike -s territory-signals-kaiser-db -w)@db.ukpfksabatofcczdrphm.supabase.co:5432/postgres?sslmode=require"
ADMIN_EMAIL=their.email@example.com ../.venv/bin/python -m territory.seed_team --client kaiser-team
```

`ADMIN_EMAIL` is added as an **owner**. To add someone with a different role (agent, etc.), list them under `team_members:` in `config/clients/kaiser-team.yaml` (name, email, role) and run `seed_team` without `ADMIN_EMAIL`. Then redeploy if the dashboard should show their name or phone. `seed_team` never deletes anyone, and it re-applies the config team on every run.

Then ask the person to open the dashboard URL, enter their email and click the link in the email. Magic links are single use and expire after 1 hour. They must open the link in the same browser they requested it from.

## Rotate the SMTP password

1. Google account for the sender → https://myaccount.google.com/apppasswords → create a new app password, then delete the old one.
2. Replace the value in macOS Keychain (the item that feeds `SMTP_PASS`).
3. Open a new shell so `SMTP_PASS` is the new value, then push it. Auth config is pushed from a scratch workdir so the local-stack `supabase/config.toml` is untouched:

```toml
# <scratch>/supabase/config.toml
project_id = "territory-signals-kaiser"

[auth]
site_url = "https://kaiser-team-signals.mike-1d7.workers.dev"
additional_redirect_urls = ["https://kaiser-team-signals.mike-1d7.workers.dev/auth/callback", "https://kaiser-team-signals.mike-1d7.workers.dev/**"]

[auth.rate_limit]
email_sent = 30

[auth.email]
otp_expiry = 3600

[auth.email.smtp]
enabled = true
host = "smtp.gmail.com"
port = 587
user = "mike@lilosgrowth.com"
pass = "env(SMTP_PASS)"
admin_email = "mike@lilosgrowth.com"
sender_name = "The Kaiser Team"
```

```bash
supabase link --project-ref ukpfksabatofcczdrphm --workdir <scratch> --yes
supabase config push --workdir <scratch> --yes
```

`config push` only changes the properties declared in the file. The password is read from the environment and is never written to a file.

4. Test: request a sign-in link on the production login page. If it fails, read the Auth logs: `supabase logs --remote=ukpfksabatofcczdrphm --service auth --since 15m --output-format json` and look at the `/otp` entries. `535 BadCredentials` means Gmail rejected the app password.

## Auth settings (cloud)

- Magic link expiry: 1 hour.
- Site URL and redirect URLs: the workers.dev URL above. **When a custom domain is added, update both** (and `additional_redirect_urls`), or sign-in links will point at the wrong host.
- Sender: "The Kaiser Team" via smtp.gmail.com:587 as mike@lilosgrowth.com.
- Gmail limits sending to about 500 messages a day; see `BACKLOG.md`.

## AI layer: set a provider for a client (Phase 5F, D13)

The AI provider is chosen **per client**, because that client's data (parcel facts, permit text, weekly counts) is sent to it. It lives in the client's `llm:` block in `config/clients/<id>.yaml`. The API key is never in the file: `api_key_env` names an environment variable.

**A new provider or model must score >= 90% on the eval before a client config switches to it.**

```bash
cd pipelines && source ../.venv/bin/activate
LLM_API_KEY=... python -m territory.llm.eval --provider openai_compatible --model <model> --base-url <url> -v
# prints the pass rate per task (permit_intent, lead_brief, weekly_brief) and the total cost
```

Config examples (only the `llm:` block changes):

```yaml
# OpenRouter (Kaiser Team). Every request sends provider.data_collection = deny.
llm: {provider: openai_compatible, base_url: https://openrouter.ai/api/v1, api_key_env: LLM_API_KEY,
      model: <model id>, tasks: {permit_intent: {model: <model id>}, lead_brief: {}, weekly_brief: {}},
      monthly_budget_usd: 20, enabled: true}

# Anthropic (official SDK). Add the model's prices to config/llm_pricing.yaml first, or its cost is recorded as unknown.
llm: {provider: anthropic, api_key_env: ANTHROPIC_API_KEY, model: <claude model id>,
      tasks: {permit_intent: {}, lead_brief: {}, weekly_brief: {}}, monthly_budget_usd: 20, enabled: true}

# xAI
llm: {provider: openai_compatible, base_url: https://api.x.ai/v1, api_key_env: XAI_API_KEY, model: <grok model id>,
      tasks: {}, monthly_budget_usd: 20, enabled: true}

# Ollama on this machine (no cost is reported, so spend shows as unknown; any non-empty key works)
llm: {provider: openai_compatible, base_url: http://localhost:11434/v1, api_key_env: OLLAMA_KEY, model: llama3.1,
      tasks: {}, monthly_budget_usd: 20, enabled: true}
```

- **Off switch.** `enabled: false`, or the key variable not set, makes every AI task skip cleanly (a "skipped" row is recorded) and the dashboard shows nothing AI-related. The dashboard reads `enabled` from the config baked into the build, so redeploy it after changing the flag.
- **Run.** `python -m territory.run --client kaiser-team --only-ai` runs permit_intent, lead_brief and weekly_brief in that order (`--skip-ai` leaves them out of a full `--source all` run). Results are cached by input and prompt version, so a rerun costs nothing unless facts changed.
- **Permit scope.** `llm.tasks.permit_intent.scope: {months: 36, min_lead_score: 40}` limits permit_intent to permits issued in that window or on parcels scoring at least that; omit it to classify every permit.
- **Budget.** `monthly_budget_usd` caps the month's total. A task stops before the call that would pass it and a warning shows on the Pipeline page.
- **Run against the cloud database** (key from the macOS Keychain, service `territory-signals-llm`):

```bash
cd ~/territory-signals && source .venv/bin/activate \
  && export SUPABASE_DB_URL="postgresql://postgres:$(security find-generic-password -a mike -s territory-signals-kaiser-db -w)@db.ukpfksabatofcczdrphm.supabase.co:5432/postgres?sslmode=require" \
  && export LLM_API_KEY="$(security find-generic-password -a mike -s territory-signals-llm -w)" \
  && cd pipelines && python -m territory.run --client kaiser-team --only-ai --cloud
```

**Cloud guard (Phase 5H).** Every pipeline command (`run`, `score`, `permit_rederive`, `outreach`, `owner_data.load`, the AI tasks) refuses to connect to any database host other than 127.0.0.1/localhost unless `--cloud` is passed, and exits naming the host. A shell that still has `SUPABASE_DB_URL` exported will therefore never write to the cloud by accident; for local work run `env -u SUPABASE_DB_URL ...`.

## Runtime notes

- No `nodejs_compat` flag is needed. No Node-only modules or filesystem access at runtime.
- Astro sessions are off (`session: false`), so no KV binding is required. The image service is `passthrough`.
- `/api/map` is built in SQL (`map_geojson`) and streamed through the Worker without parsing, to stay inside the Workers CPU limit. The score band is added in the browser.
- Street addresses are stored in ALL CAPS (county data) and title-cased for display in `src/lib/format.ts` (`titleAddress`).
- If the database or auth service errors, pages answer 503 "One moment" (and stay signed in) rather than redirecting to /login.
- The `authenticated` database role has an 8 s statement timeout. Page queries are well under it (see `BACKLOG.md`); a timeout shows as `canceling statement due to statement timeout` in `wrangler tail`.
- Workers Free allows 10 ms of CPU per request. If a page fails with a CPU time limit error (Cloudflare error 1102), upgrade the account to Workers Paid. See the smoke-test results below.

## Smoke test results (2026-11-18)

Production: https://kaiser-team-signals.mike-1d7.workers.dev, signed in as a team member (magic link and 6-digit code both tested).

| Page | Result |
|---|---|
| `/login` (link, code, invalid link redirect) | Pass |
| `/` | Pass (after the middleware 503 fix and the `latest_scores` migration) |
| `/leads` | Pass |
| One lead brief | Pass, address in title case |
| `/map` | Pass (after copying MapLibre's worker to `/maplibre/`) |
| `/trends` | Pass (after pre-computing the trend views) |
| `/trends/newsletter` | Pass |
| `/pipeline` | Pass |
| `/settings` | Pass |

Findings fixed on the way: `/leads` and `/` timed out (`latest_scores`, 12 to 14 s, now about 0.4 s); `/trends` timed out (four aggregates, now about 18 ms each); `/map` was blank (worker 404); a transient auth/database error used to sign the user out (now a 503 page). No `exceededCpu` outcome appeared in `wrangler tail` for any page on the Workers Free plan.
