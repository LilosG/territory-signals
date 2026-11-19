# Dashboard (Astro 7 + Tailwind 4, server-rendered)

Reads the local Supabase database through the signed-in user's session (row level security applies).

## Run it locally

1. Docker running, then from the repo root: `supabase start` (migrations are in `supabase/migrations/`; use `supabase migration up`, not `db reset`, to keep loaded data).
2. Add yourself to the team (only emails in `team_members` can sign in; this is enforced in the database):
   `cd pipelines && ADMIN_EMAIL=mike@lilosgrowth.com python -m territory.seed_team --client kaiser-team`
3. `cd dashboard && cp .env.example .env && npm install && npm run dev`
4. Open **http://127.0.0.1:3000** (use `127.0.0.1`, not `localhost`: it is the auth site URL, so the cookie and the link match).
5. Enter your email on the sign-in page. Locally the email is not delivered; open the **mail viewer at http://127.0.0.1:54324**, open the newest message and click the sign-in link. You land on Today, signed in.

`DATA_PROVIDER=fixtures` runs the sample bundle with no database and no login (the design-system gallery at `/design-system` always uses it).

## Checks
- `npm run check` (astro check), `npm run build`
- `npm run e2e` Playwright against the local stack (seeds and removes a test team member and a synthetic test parcel)
- `npm run screenshots` every screen at 1440x900 and 390x844 against live data into `screenshots/`
- `npm run check:contrast` lightest map band vs white and basemap
- `npm run fixtures` regenerates `src/data/fixtures.json` (names come only from `src/data/catalog.generated.json`)
