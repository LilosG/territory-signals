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
- [ ] **`team_members` config shape:** typed as free-form dicts until Phase 5 defines it.

Added during Phase 2:

- [ ] **STRO first run is a baseline:** the first `stro_licenses` run produces no `stro_license_removed` signals (nothing to compare with). Removals start with the second run. The City file has no issue date, so license age is still unknown.
- [ ] **Permit type map needs Mike's review:** `config/permit_signal_map.yaml` is `status: proposed`. Every one of the 147 territory `APPROVAL_TYPE` strings is mapped (81 to `other`). No approval type is ADU: ADU work appears as Building / Combination Building permits with `APPROVAL_ADU_TOTAL > 0`, so the `adu` group is empty until Phase 3 splits it using `adu_total`, which is kept in signal details.
- [ ] **`permit_stalled` is noisy:** the data has `APPROVAL_EXPIRE_DATE` and `APPROVAL_CLOSE_DATE`, so the signal is built (expired, never closed, status not terminal). Many short-lived permit types (traffic control, right-of-way, no-plan trades) expire without ever being closed, so Phase 3 should weight or restrict by `signal_group`.
- [ ] **Permit scope:** ingested the full `active` file plus the 2025 and 2026 files of `issued`, `closed` and `created` (the full issued/closed/created history files, 400-680 MB each, are not ingested). Older closed permits are therefore absent. `APPROVAL_PERMIT_HOLDER` (a person/business name) is dropped on read.
- [ ] **Permits that cannot be placed:** approvals with a blank/unknown APN, no coordinates and no address match cannot be assigned to the territory; they are counted in `dev_permits_match_report.md` and not stored.
- [ ] **Parcel fields not loaded:** `year_built` stays null (SanGIS only has the two-digit `YEAR_EFFECTIVE`, which is not a year built). `lot_sqft` is `USABLE_SQ_FEET` when real, else the polygon area, else null for stacked condo footprints shared by several APNs (counts in `parcels_load_report.md`). `DOCDATE` values that are not a valid MMDDYY date (including `000000`) are stored as null and counted in that report.
- [ ] **Parcels come from the SanGIS shapefile download**, not the CSV: the CSV has no geometry, and the shapefile carries the same attribute columns.
- [ ] **SB 9 screen excludes planned districts:** only the `RS-*` base zones are screened. `LJSPD-SF` (La Jolla Shores single-family) and the other planned-district zones (`LJPD-*`, `MBPD-*`) need rule-by-rule treatment per SOURCES.md; decide whether `LJSPD-SF` counts as single-family for SB 9. Parcels in RS zones with no `lot_sqft` are skipped.
- [ ] **SB 79 screen is a proxy:** the GTFS stop file has no frequency or dedicated-lane data. Rail = GTFS parent stations on a rail/trolley line; BRT = stops within 100 ft of an MTS Rapid route shape (Super Loop excluded), so local stops on shared corridors are included. Replace with the official City/SANDAG layer when received (D7).
- [ ] **Snapshot signals repeat by run date:** `stro_license_active`, `sb9_lot_split_estimate`, `sb79_transit_estimate` and `fire_hazard_zone` use the run date as `signal_date`, so a rerun on a new day adds a new row per parcel. Phase 3 scoring must read the latest per (apn, signal_type).
- [ ] **Raw records grow each run:** `raw_records` is append-only and every run stores its in-scope rows again (about 54,000 permit rows per run). Revisit (store only changed payloads) before scheduled daily runs.
- [ ] **Tax-default list is annual:** the URL is pinned to the June 2026 notice; update `URL` in `tax_default.py` each June. The parser splits each page at the middle (the notice prints two columns); re-check if the layout changes. Auction notices (7102: 10 parcels in the two ZIPs) are not ingested.
- [ ] **Base layers do not write `raw_records`:** planning areas, parcels and zoning are loaded straight into their tables (idempotent upserts); the dated files in `data/raw/` are the raw copy.
- [ ] **Polite-access identity:** downloads use the generic User-Agent `territory-signals-pipeline/2.0` with no contact address. Add a contact email if a host asks for one.
- [ ] **Fire hazard zones:** `fire_zones` is built and tested but waits for Mike's manual download into `data/manual/fhsz/` (D6); the run is recorded as failed with "awaiting manual download" until then.
- [ ] **Run location:** `python -m territory.run` must be run from `pipelines/` (or with `PYTHONPATH=pipelines`); README.md is outside Phase 2's allowed paths, so it was not updated.
