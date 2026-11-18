# territory-signals

Territory intelligence platform for real estate teams: one codebase, a separate deployment per client, configured in `config/clients/`. Current client: The Kaiser Team (La Jolla, Pacific Beach, Mission Beach).

## Local database
Requires Docker Desktop running and the Supabase CLI.

    supabase start       # starts local Postgres/PostGIS on port 54322
    supabase db reset    # rebuilds the database from supabase/migrations/

## Tests

    source .venv/bin/activate
    pip install -r requirements.txt pytest pydantic "psycopg[binary]" pyyaml
    pytest

The database tests run `supabase db reset`, so the local stack must be started first.

## Docs
- `CLAUDE.md`: project rules
- `ARCHITECTURE.md`: layers, tables, adapter interfaces, phases
- `DECISIONS.md`: approved decisions
- `BACKLOG.md`: open items
- `SOURCES.md`: data-source recon
