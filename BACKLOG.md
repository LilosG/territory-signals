# Backlog

Open items carried over from SOURCES.md.

- [ ] **Fire hazard zones (D6):** Mike downloads the OSFM/CNRA statewide LRA layer by hand; ingest in Phase 2. Whether 92037/92109 intersect a zone is unconfirmed (SOURCES.md #6).
- [ ] **Official SB 79 data:** request the City's or SANDAG's SB 79 layer (City lists planning@sandiego.gov). The SANDAG map is draft and viewer-only; the City layer (`webmaps.sandiego.gov`) returned 403 to scripts (SOURCES.md #8b, D7).
- [ ] **DOCTYPE code dictionary:** confirm `DOCTYPE` (and `DOCDATE` meaning) with SanGIS/Assessor documentation. Also unconfirmed: `ASR_LANDUSE`/`ASR_ZONE` code meanings (SOURCES.md #7, D8).
- [ ] **capublicnotice permission request:** Mike sends a written permission request to capublicnotice/CNPA (D1, SOURCES.md #4).

Added during Phase 1:

- [ ] **Dependencies not in requirements.txt:** Phase 1 installed `pytest`, `pydantic`, `psycopg[binary]` and `pyyaml` into `.venv`; `requirements.txt` was outside the allowed paths, so it was not updated. Pin them there next phase.
- [ ] **Append-only enforcement:** `raw_records`, `signals` and `owners` are append-only by convention only; no DB trigger blocks UPDATE/DELETE yet. Decide whether to add one.
- [ ] **Outreach modes:** `config.py` accepts only `outreach.mode: preview`; extend in Phase 5.
- [ ] **`team_members` config shape:** typed as free-form dicts until Phase 5 defines it.
