"""Insert or update team_members from the client config plus ADMIN_EMAIL (role owner).

Only emails in team_members can sign in to the dashboard (enforced in the database).

Run from pipelines/:  ADMIN_EMAIL=you@example.com python -m territory.seed_team --client kaiser-team
Existing rows are updated by email (case-insensitive); nothing is ever deleted.
"""
from __future__ import annotations

import argparse
import os
import sys

from territory.config import load_client
from territory.db import connect

UPSERT = """
insert into team_members (email, name, role) values (%s, %s, %s)
on conflict (email) do update set name = coalesce(excluded.name, team_members.name), role = excluded.role
"""


def team_rows(client_id: str, admin_email: str | None) -> list[tuple[str, str | None, str]]:
    cfg = load_client(client_id)
    rows: dict[str, tuple[str, str | None, str]] = {}
    for m in cfg.team_members:
        rows[m.email.strip().lower()] = (m.email.strip().lower(), m.name, m.role)
    if admin_email:
        e = admin_email.strip().lower()
        # The admin is always an owner, even if the config lists them with another role.
        rows[e] = (e, rows[e][1] if e in rows else None, "owner")
    return list(rows.values())


def seed(client_id: str, admin_email: str | None, conn=None) -> int:
    rows = team_rows(client_id, admin_email)
    own = conn is None
    conn = conn or connect()
    try:
        for r in rows:
            conn.execute(UPSERT, r)
        conn.commit()
    finally:
        if own:
            conn.close()
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--client", default="kaiser-team")
    args = ap.parse_args()
    admin = os.environ.get("ADMIN_EMAIL")
    if not admin:
        print("warning: ADMIN_EMAIL is not set; seeding the config team only", file=sys.stderr)
    n = seed(args.client, admin)
    print(f"team_members: {n} row(s) inserted or updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
