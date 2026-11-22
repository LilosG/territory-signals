# SOURCES.md — Territory Signals data-source recon (Kaiser Team)

Recon date: 2026-11-18. Scope: La Jolla 92037, Pacific Beach / Mission Beach 92109.
Nothing here is a pipeline; every claim below was observed in this session or is marked **UNCONFIRMED**.
Probe scripts: `recon/scripts/` (one per source, plus `_http.py` which sets the User-Agent and per-host throttling). Samples: `recon/samples/` (<=200 rows). Raw downloads: `recon/raw/` (git-ignored).

**Access conduct.** Scripts used UA `territory-signals-recon (mike@lilosgrowth.com)`, >=2 s between requests per host (60 s for hosts whose robots.txt sets `Crawl-delay: 60`). No logins, CAPTCHAs, or paid services. Hosts that returned 403 to automated requests (`webmaps.sandiego.gov`, `osfm.fire.ca.gov`, `courtindex.sdcourt.ca.gov`) were not worked around. Documentation/terms pages (not data) were read with single page fetches through a fetch tool, so the clause quotes below come from those reads and should be re-checked on the live page before anything legal rests on them.

## Summary table

| # | Source | Verdict | APN present | 92037 count | 92109 count | Update frequency | Access method |
|---|---|---|---|---|---|---|---|
| 1 | City STRO licenses | USABLE-WITH-LIMITS | No (lat/lon + address only) | 823 active (T1 11 / T2 184 / T3 628) | 2,553 active (T1 40 / T2 426 / T3 990 / T4 1,097) | Portal page says updated 2026-11-17; cadence not stated | Direct CSV download (seshat.datasd.org) |
| 2 | City development permit approvals | USABLE-WITH-LIMITS | Yes (`GIS_APN`, 8.9% blank) | 2,614 issued approvals (767 projects) | 2,034 issued approvals (483 projects) | Daily (portal) | Direct CSV download |
| 3 | SD Superior Court probate | BLOCKED (terms) | n/a | n/a | n/a | n/a | Web search UI only; terms bar bots |
| 4 | Published legal notices (probate / trustee sale) | BLOCKED (capublicnotice) / UNCONFIRMED (papers) | No | UNCONFIRMED | UNCONFIRMED | Daily (publisher) | Web UI; `/search/` disallowed in robots.txt |
| 5 | County Treasurer-Tax Collector lists | USABLE-WITH-LIMITS | Yes | 15 (2026 Impending Power to Sell list) | 24 (same list) | Annual list (June) + 1–2 auctions/yr | PDF download, text-parsable |
| 6 | CAL FIRE Fire Hazard Severity Zones | UNCONFIRMED | n/a | UNCONFIRMED | UNCONFIRMED | Statewide maps dated 2025-03-24 (recommended LRA) | No authoritative download reached |
| 7 | SanGIS parcels | USABLE | Yes (`APN`) | 18,619 | 15,425 | UNCONFIRMED | Direct CSV (geo.sandag.org), 432 MB |
| 8a | Base zoning (SB 9 inputs) | USABLE-WITH-LIMITS | No (spatial join) | n/a | n/a | Weekly (catalog) | GeoJSON download |
| 8b | Transit stops / SB 79 | USABLE-WITH-LIMITS / UNCONFIRMED (official SB 79 layer) | No | n/a | n/a | Weekly (catalog) | GeoJSON; SB 79 map is viewer-only |
| 9 | Community planning areas | USABLE | No | n/a | n/a | Weekly (catalog) | GeoJSON download |
| 10 | Obituaries | BLOCKED (terms) | n/a | n/a | n/a | n/a | Not accessed |
| 11 | City code enforcement violations | USABLE-WITH-LIMITS | Yes (`apn`, 10-digit) | n/a (historical extract) | n/a (historical extract) | Historical extract; last updated Jan 19, 2018 | Direct CSV download (seshat.datasd.org) |

---

## 1. City of San Diego STRO licenses — USABLE-WITH-LIMITS
- **Page:** https://data.sandiego.gov/datasets/stro-licenses/ (City Treasurer; "Updated Nov 17, 2026").
- **Download:** https://seshat.datasd.org/stro_licenses/stro_licenses_datasd.csv (2.04 MB, CSV). Dictionary: `.../stro_licenses_dictionary_datasd.csv`; tier definitions: `.../stro_licenses_tier_definitions_datasd.csv`.
- **Rows / fields:** 8,432 rows, 23 fields: `license_id, address, street_number, street_number_fraction, street_direction, street_name, street_type, unit_type, unit_number, city, state, zip, tier, community_planning_area, date_expiration, rtax_no, tot_no, longitude, latitude, local_contact_contact_name, local_contact_phone, host_contact_name, council_district`.
- **Tier:** `tier` = "Tier 1–4". Tiers per the City's definitions file: T1 <=20 rental days/yr; T2 >20 days, host resides onsite 275+ days; T3 90+ days, all areas except Mission Beach; T4 90+ days, Mission Beach Precise Plan area only.
- **Host name:** `host_contact_name` (a person's name) plus `local_contact_contact_name` and `local_contact_phone`. No host mailing address.
- **Dates:** only `date_expiration` (2026-11-17 to 2029-01-14). **There is no license issue/start date**, so license age cannot be computed from this file.
- **APN:** none. Join to parcels by lat/lon or address.
- **Counts (file contains active licenses only):** 92037 = 823, 92109 = 2,553 (tiers in summary table). Planning-area labels are inconsistently cased (`LA JOLLA`/`La Jolla`, `MISSION BEACH`/`Mission Beach`, etc.); normalize. 3 rows have no ZIP. In these two ZIPs no host name appears on more than one license (consistent with the one-license-per-host rule), so multi-property host rollups are not possible from this file.
- **Terms:** City Open Data Terms of Use (https://data.sandiego.gov/help/guides/terms/) are accepted by downloading; no automated-access restriction found; robots.txt only disallows `/preview/`. Data carries a no-warranty clause. **Privacy flag:** host names and phone numbers are personal data; recommend not storing the phone column.
- **Sample:** `recon/samples/stro_licenses_92037_92109_sample.csv` (phone column removed). Script: `recon/scripts/03_stro_permits.py`.

## 2. City of San Diego development permit approvals — USABLE-WITH-LIMITS
- **Page:** https://data.sandiego.gov/datasets/development-permits/ (Development Services; "Updated Nov 17, 2026", Daily).
- **Files (CSV, all under https://seshat.datasd.org/development_permits/):** `approvals_{active,issued,closed,created}_datasd.csv` plus per-year `_2024/_2025/_2026` variants (issued 2025 = 24.9 MB, issued 2026 = 22.3 MB; full issued = 555 MB; active = 256 MB). Set 2 dictionary: https://seshat.datasd.org/development_permits_set2/permits_set2_datasd_dict.csv.
- **Fields (54):** `DEVELOPMENT_ID, PROJECT_ID, PROJECT_TYPE, PROJECT_STATUS, PROJECT_PROCESSING_CODE, PROJECT_CREATE_DATE, PROJECT_DEEMEDCOMPLETE_DATE, PROJECT_TRUST_ACCOUNT_NO, PROJECT_TITLE, PROJECT_SCOPE, JOB_ID, JOB_DRAWING_NUMBER, GIS_ADDRESS, GIS_APN, JOB_BC_CODE, JOB_BC_CODE_DESCRIPTION, GIS_LATITUDE, GIS_LONGITUDE, APPROVAL_ID, APPROVAL_CATEGORY_CODE, APPROVAL_PROCESSING_CODE, APPROVAL_TYPE, APPROVAL_STATUS, APPROVAL_SCOPE, APPROVAL_CREATE_DATE, APPROVAL_ISSUE_DATE, APPROVAL_CLOSE_DATE, APPROVAL_EXPIRE_DATE, APPROVAL_VALUATION, APPROVAL_DU_NET_CHANGE, APPROVAL_STORIES, APPROVAL_FLOOR_AREA`, DU/ADU/JADU affordability and total columns, `APPROVAL_PERMIT_HOLDER`.
- **APN:** `GIS_APN` (10-digit, no dashes); blank on 8.9% of 2025–26 issued rows. **ZIP:** no ZIP field; `GIS_ADDRESS` embeds ZIP only for ~54% of rows, so ZIP filtering by address string undercounts badly. I assigned ZIP by joining `GIS_APN` to the parcel file's `SITUS_ZIP` (matched 86% of rows; unmatched rows are mostly the blank-APN ones, so counts below are a floor).
- **Dates:** issue 2025-01-01 to 2026-11-17 in the two files read. Rows are approvals (one project has many approvals).
- **Last-12-month counts (issued 2025-11-18 to 2026-11-17, APN-join ZIP):**

  | PROJECT_TYPE | 92037 | 92109 |
  |---|---|---|
  | (blank) | 1,515 | 1,286 |
  | Building Construction | 696 | 500 |
  | Grading, ROW, Mapping - Standalone | 203 | 99 |
  | Plan - Mechanical/Electrical/Plumbing Standalone | 55 | 31 |
  | Discretionary Project | 42 | 20 |
  | Sign | 25 | 12 |
  | Demolition | 22 | 22 |
  | Fire | 21 | 13 |
  | Others | 16 | 21 |
  | Right of Way - Dry Utilities | 11 | 16 |
  | Right of Way - Minor - Rapid Review | 8 | 6 |
  | Building Construction - CIP or Public Project | 0 | 7 |
  | Project - Residential - Photovoltaic | 0 | 1 |
  | **Total approvals** | **2,614** | **2,034** |

- **Limit that matters:** **63.5% of 2025–26 issued rows have a blank `PROJECT_TYPE`** (legacy-system rows with numeric `PROJECT_ID` instead of `PRJ-…`; mostly traffic-control, no-plan MEP, solar). Use `APPROVAL_TYPE` / `JOB_BC_CODE_DESCRIPTION` for classification. Building/demolition-style approvals (by `APPROVAL_TYPE` match) = 1,002 (92037) and 665 (92109); approvals with ADU total > 0 = 53 and 77. `APPROVAL_DU_NET_CHANGE` is empty/zero in these rows, so new-unit counts are not reliable here.
- **Terms:** same City Open Data Terms; no automated-access restriction found. `APPROVAL_PERMIT_HOLDER` contains personal/business names.
- **Sample:** `recon/samples/dev_permits_issued_92037_92109_sample.csv`. Scripts: `04_dev_permits.py`, `25_permits_recount.py`.

## 3. San Diego Superior Court probate — BLOCKED (terms)
- **Pages read:** https://sdcourt.ca.gov/sdcourt/generalinformation/courtrecords2/onlinecasesearch ; Court Index https://courtindex.sdcourt.ca.gov/CISPublic/enter ; Register of Actions (civil/probate) https://odyroa.sdcourt.ca.gov ; "Lists of New Case Filings" https://www.sdcourt.ca.gov/sdcourt/onlineservices/newfilings (found under the court's Court Records links).
- **Search by date without party name?** The Online Case Search page lists only three ways to find a case: party name, case number, DA case number. Filing-date or new-filing listing is **not offered there**. Fields shown in results: case title, case number, location, case type, date filed, parties.
- **New Case Filings page:** the fetch returned only the title, breadcrumb and navigation; **what the lists contain (case types, format, frequency) is UNCONFIRMED.** Mike should open it manually.
- **Terms:** https://www.sdcourt.ca.gov/sdcourt/termsofuse prohibits "unauthorized data mining, web mining, web harvesting, use of 'bots,' or similar data gathering and extraction methods" (section "Restrictions on Access and Use"). robots.txt allows generic crawling (`Content-Signal: search=yes, ai-train=no`) but the Terms control. The Court Index returned 403 to a scripted request; not worked around.
- **Verdict:** BLOCKED-BY-TERMS for any automated access. No sample saved. A third-party aggregator (Trellis) lists San Diego probate filings by date; its terms and licensing were **not** checked.

## 4. Published legal notices — capublicnotice BLOCKED; newspaper coverage UNCONFIRMED
- **capublicnotice.com** (CNPA / iPublish; operator "CSI" in its user agreement): search by keyword, date, notice type (includes "Probate Notice", "Notice of Trustee Sale"), county, city, source (newspaper). Pagination is a JavaScript "Load More"; notice PDFs at `/image/notices/<refcode>/<file>.pdf`; refcode like `#0011818985-01`. Fields visible in listings: newspaper, title/excerpt, county, post date, refcode; many show "Pending Categorization". Decedent name, property address, petitioner and case number would be in the notice body/PDF (not verified).
- **Terms / robots:** robots.txt: `Disallow: /search/`, `Disallow: /basket/`, `Crawl-Delay: 20`. User Agreement (`/page/privacy.html`): "No part of this Website or any content on it may be used without the prior written authorization of CSI." **BLOCKED** for automated search/collection; the homepage sample I saw listed LA/Solano/Yolo papers, and whether San Diego papers are on it is **UNCONFIRMED**.
- **Adjudicated San Diego newspapers** (court form ADM-335, Rev. 10/26, https://www.sdcourt.ca.gov/sites/default/files/sdcourt/generalinformation/forms/adminforms/adm335.pdf) include: **La Jolla Light, La Jolla Today, Beach and Bay Press, The Peninsula Beacon, The Daily Transcript, The San Diego Union-Tribune, San Diego Business Journal, San Diego Reader, Village News, The Coast News, Carmel Valley News, Del Mar Times, Rancho Santa Fe Review, The Star News, East County Californian,** and others (40-odd). Court disclaimer: it does not verify the list's accuracy.
- **Online publication:** search hits show The Business Journal (thebusinessjournal.com "public notices" daily pages), East County Californian, The Star News and The Coast News post legals as web pages or PDFs; Times of San Diego sells notice placement. For La Jolla Light / Daily Transcript / Union-Tribune, **no public searchable legal-notice page was confirmed (UNCONFIRMED)**. The Union-Tribune/La Jolla Light robots.txt states content is for personal, non-commercial use and prohibits "caching or archiving the Content" and text/data mining (see source 10).
- **Verdict:** capublicnotice = BLOCKED; per-paper pages = UNCONFIRMED (each paper's terms need reading before any collection).

## 5. County Treasurer-Tax Collector lists — USABLE-WITH-LIMITS
- **Current list:** "Notice of Impending Power to Sell Tax-Defaulted Property" (published June 5/12/19, 2026): https://www.sdttc.com/content/dam/ttc/docs/taxcollection/Notice-of-Impending-Power-to-Sell-Tax-Defaulted-Property-June-5-12-19-2026.pdf (6 pages, text-extractable; index page https://www.sdttc.com/content/ttc/en/tax-collection/property-tax-sales/legal-ads.html, back to 2013). Parcels became subject to power to sell July 1, 2026 (5+ years tax-defaulted, or 3+ with nuisance lien etc.).
- **Fields:** Assessor's Parcel No. (dashed), assessee's name, property street address (partial: street number + street name, **no ZIP**), total amount to redeem. **1,034 parcels**; 100% matched to the parcel file by APN. By parcel-file ZIP: **92037 = 15, 92109 = 24.** Names include trusts and "EST OF" (estate) holders, a possible signal.
- **Auction notices:** latest sale 7102 (Mar 13–18, 2026; https://www.sdttc.com/content/dam/ttc/docs/taxcollection/Notice-of-Public-Online-Auction-7102.pdf): 715 parcels, columns item no., APN, last assessee, minimum bid, **no situs address**; 10 in the two ZIPs. Next auction "To Be Announced 2027". Bids on sdttc.mytaxsale.com (not accessed). Past results: PDF "Final Reports of Sale" 2012–2026.
- **No CSV/XLSX or defaulted-property data feed was found.** Frequency: annual list in late May/June; auctions typically March and May.
- **Terms:** robots.txt `Allow: /`; no site-specific terms read (UNCONFIRMED). Lists are public legal notices.
- **Sample:** `recon/samples/sdttc_impending_power_to_sell_92037_92109.csv` (39 rows). Scripts: `07_sdttc.py`, `23_ttc_join2.py`, `24_ttc_sample.py`.

## 6. CAL FIRE Fire Hazard Severity Zones — UNCONFIRMED
- **What exists:** OSFM published 2025 recommended LRA maps dated March 24, 2025; CNRA hub lists statewide FHSZ data (SRA effective 2024 with LRA 2007–11 as an interim set). The authoritative OSFM site (`osfm.fire.ca.gov`) returned 403 to scripted requests; the CNRA hub item I found (`31219c83…`) did not resolve to a service; SANDAG's `Fire_Hazard_Severity_Zones` FeatureServer requires a token (not used). The state MapServer I reached (`services.gis.ca.gov/.../Fire_Severity_Zones/MapServer`) is the **old 2007/2011 vintage**.
- **Whether 92037 / 92109 fall in a zone: UNCONFIRMED.** A third-party San Diego mirror (SDSU-hosted "FIRE_HAZARD_SEVERITY_ZONES_SD", 84 polygons, all "Very High") contained one 206 sq mi polygon covering La Jolla and Pacific Beach and returned thousands of parcel hits; that is implausible, so no counts are reported and no sample saved. The City's SB 79 page links a "very-high-fire-hazard-severity-zones.pdf" map (https://www.sandiego.gov/sites/default/files/2026-08/very-high-fire-hazard-severity-zones.pdf) and says Very High zones are phased in for SB 79 after the Transit Village Plan is adopted, which implies Very High zones exist in San Diego; whether they touch these ZIPs was not read.
- **Next step:** download the OSFM/CNRA statewide LRA layer in a browser and test parcels, or use the City's layer.

## 7. SanGIS parcels — USABLE
- **Access:** the hub page https://gis-sangis1.hub.arcgis.com/pages/download-data is JavaScript-rendered and its robots.txt sets `Crawl-Delay: 60`. The same data is a direct download: https://geo.sandag.org/server/rest/directories/downloads/Parcels.csv (432 MB; also `_shapefile.zip`, 439 MB; geo.sandag.org has no robots.txt). Downloaded once to `recon/raw/`.
- **Fields (56):** `OID_, APN, APN_8, PARCELID, FRACTINT, SITUS_JURIS, SITUS_STREET, SITUS_SUFFIX, SITUS_POST_DIR, SITUS_PRE_DIR, SITUS_ADDRESS, SITUS_FRACTION, SITUS_BUILDING, SITUS_SUITE, LEGLDESC, ASR_LAND, ASR_IMPR, ASR_TOTAL, DOCTYPE, DOCNMBR, DOCDATE, ACREAGE, TAXSTAT, OWNEROCC, TRANUM, ASR_ZONE, ASR_LANDUSE, UNITQTY, SUBMAP, SUBNAME, NUCLEUS_ZONE_CD, NUCLEUS_USE_CD, SITUS_COMMUNITY, YEAR_EFFECTIVE, TOTAL_LVG_AREA, BEDROOMS, BATHS, ADDITION_AREA, GARAGE_CONVERSION, GARAGE_STALLS, CARPORT_STALLS, POOL, PAR_VIEW, USABLE_SQ_FEET, QUAL_CLASS_SHAPE, NUCLEUS_SITUS_FROM_NBR, NUCLEUS_SITUS_THRU_NBR, NUCLEUS_SITUS_THRU_FRACTN, SITUS_ZIP, X_COORD, Y_COORD, OVERLAY_JURIS, SUB_TYPE, MULTI, Shape_Length, Shape_Area`. 1,088,570 rows countywide.
- **Owner names: confirmed NOT present** (no owner-name column; only `OWNEROCC`, a Y/blank flag: Y on 12,787 of the 34,044 parcels in the two ZIPs; blank is not proof of absentee).
- **Counts by `SITUS_ZIP`:** **92037 = 18,619; 92109 = 15,425** (stacked condo/unit parcels included; a handful of rows have coordinates outside the area; APN unique except 1).
- **Field notes:** situs address is split (`SITUS_ADDRESS` is the number, plus street/suffix/direction/suite); `SITUS_ZIP` is ZIP+4. Lot size: `USABLE_SQ_FEET` is filled for ~64% with placeholder values (`00000`, `99999`); `ACREAGE` is filled for only ~4%; `Shape_Area` is projected-polygon area. **Year built:** only `YEAR_EFFECTIVE` (two-digit effective year, blank 1.5%). **Last transfer:** `DOCDATE` is a recorded-document date in **MMDDYY (two-digit year)**, parsed range 1969–2068 under naive parsing, so century must be pivoted; `DOCTYPE` codes (1, 2, 3, 6…) have no dictionary found, **meaning UNCONFIRMED** (not necessarily a sale). Land-use/zone codes (`ASR_LANDUSE`, `ASR_ZONE`) are coded, **code meanings UNCONFIRMED**; use the zoning layer for zoning. `X_COORD/Y_COORD` are California State Plane zone 6 feet (EPSG:2230).
- **Update frequency / data dictionary: UNCONFIRMED.** Sample: `recon/samples/parcels_92037_92109_sample.csv` (200 random rows, no owner info). Scripts: `10_parcels_probe.py`, `11_download_sandag.py`, `12_parcels.py`.
- **Terms:** SanGIS hub terms not read (UNCONFIRMED); search results note some SanGIS parcel services are for JPA members only and that non-restricted parcel data excludes owner names.

## 8. Zoning and transit (upzoning eligibility)
**8a. Base zoning (for SB 9):** https://geo.sandag.org/server/rest/directories/downloads/Zoning_Base_SD.geojson (19.6 MB; EPSG:4326; 3,706 polygons; catalog "weekly", modified 2026-07-10). Fields: `OBJECTID, ZONE_NAME, IMP_DATE, ORDNUM, Shape_Length, Shape_Area`. No APN; spatial join of parcel points (State Plane to WGS84) gives: 92037 RS-family 7,377 parcels (RS-1-2/1-4/1-5/1-7, plus `LJSPD-SF` 2,329, a La Jolla Shores planned district single-family zone), RM-family 5,793, `LJPD` 2,401; 92109 RS 3,631, RM 7,233, CC/CV (commercial) ~1,800, Mission Beach planned district `MBPD-*` ~2,000. 92037 RS-zoned with land-use code 11: 5,842; 92109: 3,436. **SB 9 eligibility is not an official map layer** I could find (this recon did not search exhaustively); it needs parcel size, historic status, fire zone and other tests layered on zoning, and planned-district zones (`LJSPD-SF`, `MBPD-*`, `LJPD`) need rule-by-rule treatment. Sample: `parcel_zoning_join_sample.csv`.

**8b. Transit / SB 79:**
- **Stops:** https://geo.sandag.org/server/rest/directories/downloads/Transit_Stops_GTFS.geojson (2.6 MB; 6,101 stops: MTS 4,372, NCTD 1,729; weekly). Fields: `stop_UID, stop_agency, stop_id, stop_name, stop_lat, stop_lon, stop_code, location_type, parent_station, wheelchair_boarding, intersection_code, stop_place`. **No route or service-frequency fields**, so SB 79 Tier 1/Tier 2 cannot be derived from this file alone. Routes lines: `Transit_Routes_GTFS.geojson` (same directory; not downloaded). Frequency would need GTFS `stop_times` (not retrieved).
- **Official SB 79 info:** SANDAG published a **draft** SB 79 TOD map (June 18, 2026, "informational purposes") at https://www.sandag.org/draftsb79todmap ; viewer https://experience.arcgis.com/experience/0da0d1e879094c9cbc3724fea371c758 ; methodology page `.../draft-sb-79-transit-oriented-development-map/sb-79-tod-methodology`. **No data download or REST endpoint was linked.** City of San Diego page https://www.sandiego.gov/planning/work/senate-bill-79 : 74 qualifying stops (54 City + 20 SANDAG), PDF maps (e.g. `.../2026-08/qualifying-trolley-and-bus-stops.pdf`, `.../areas-that-will-take-effect-under-sb-79-on-july-1-2026.pdf`), interactive map, ordinance O-22099 (May 21, 2026); SB 79 in effect July 1, 2026 for ~24% of City area. The page both calls SANDAG's map a draft and says final stops are included, **so status is internally inconsistent**. A search hit shows a City service `webmaps.sandiego.gov/.../Hosted/SB79_TOD_Buffers_Draft/FeatureServer`, but that host returned 403 to scripts, so fields and coverage are **UNCONFIRMED**. Mission Beach / Pacific Beach / La Jolla stop eligibility was not determined. The statewide HCD page https://www.hcd.ca.gov/planning-and-research/sb79-tod exists (not read); no official statewide eligibility map was found.
- I do not report "stops within half a mile" numbers: my first attempt used a parcel hull contaminated by outlier points and was discarded.

## 9. Official community planning areas — USABLE
- **Download:** https://geo.sandag.org/server/rest/directories/downloads/Community_Plan_SD.geojson (4.0 MB, EPSG:4326, 61 areas; catalog "weekly", modified 2026-02-27); also `.csv`, `_shapefile.zip`, `_filegdb.zip`.
- **Fields:** `OBJECTID, CPCODE, CPNAME, ACREAGE, Website, Shape_Length, Shape_Area`.
- **Official areas:** La Jolla (`CPCODE` 10, 5,718.7 ac), Pacific Beach (27, 2,609.0 ac), Mission Beach (18, 220.0 ac). Extract saved: `recon/samples/official_community_planning_areas_LJ_PB_MB.geojson`. Bird Rock and La Jolla Shores stay inside La Jolla for now (per Mike: no custom boundaries drawn).
- **ZIP is not the same as planning area (finding, not a boundary proposal).** By parcel point: 92037 = La Jolla CPA 14,944 + **University CPA 3,660** + a few others; 92109 = Pacific Beach CPA 12,935 + Mission Beach CPA 2,359 + a few others. STRO rows also carry `community_planning_area`, which matches.
- **Terms:** City Open Data Terms; no restriction found. Script: `13_layers.py`, `20_spatial.py`.

## 10. Obituaries — BLOCKED (terms)
- **San Diego Union-Tribune / La Jolla Light** (La Jolla Light is on the Union-Tribune platform, same site): robots.txt header says content is for personal, non-commercial use under MediaNews Group terms, and prohibits "text and data mining", "caching or archiving the Content", AI use, and lists AI and many other crawlers as disallowed; La Jolla Light pages carry `noarchive` and `tdm-reservation` meta tags. Obituary paths on those hosts were not tested.
- **Legacy.com** (obituary host for many papers): robots.txt `Disallow: /newspaper/obituaries/`, `/obituaries/name2/`, `/obituaries/*/api/`, and others. Terms of Use section 2(a): no "robot, spider, web crawler, extraction software" or other automated process to "scrape, copy, or monitor", no incorporation in "any database", personal non-commercial use only; 2(b)(v) no commercial activities.
- **Fields:** not verified (nothing was accessed). **Verdict:** BLOCKED-BY-TERMS; no sample.

## 11. City of San Diego code enforcement violations — USABLE-WITH-LIMITS
- **Page:** https://data.sandiego.gov/datasets/code-enforcement-violations/ (Development Services; page dated Jan 19, 2018).
- **Download:** https://seshat.datasd.org/code_enforcement_violations/code_enf_past_3_yr_datasd.csv (17,708 rows observed 2026-11-21), dictionary at `.../code_enforcement_dictionary_datasd.csv`, remedies at `.../code_enf_remedies_datasd.csv`.
- **Fields:** `case_id, apn, address_street, case_source, description, date_open, date_closed, close_reason, close_note, lat, lng, nad83_northing, nad83_easting, workgroup, investigator_name, investigator_phone_number, investigator_email_address, investigator_active, last_action, date_last_action_due, remedy_msg`.
- **Coverage:** the public extract is historical (cases reported before January 2018 and closed between 2015 and 2018); it is not a current enforcement feed. In the two-ZIP bounding box (92037/92109) about 13,946 rows fall inside the La Jolla / Pacific Beach / Mission Beach coordinates. The adapter filters to territory parcels by APN, then by point-in-polygon.
- **Privacy:** `investigator_name`, `investigator_phone_number` and `investigator_email_address` are personal data and are dropped on read. `description` and `close_note` can contain owner names; the adapter stores only the violation category (text before the source's `[Addr: ... Owner: ...]` bracket) and drops reassignment notes. No phone number or email is stored.
- **Endpoint status (2026-11-21):** the direct CSV was reachable. Because the published extract is historical, the adapter keeps a trimmed, non-personal cache at `data/raw/code_enforcement/<date>/` (and a small packaged fallback at `pipelines/territory/sources/fixtures/code_enforcement_fallback.csv`) and falls back to it cleanly when the endpoint is unreachable or blocked in a local/offline run; with neither the source reports `awaiting manual download` and the weekly batch continues.
- **Next step:** confirm a current City code enforcement feed (the Open Data page has no current extract) or use the City's Get It Done / 311 case data under its own terms. Tracked in BACKLOG.md.

---

## Decisions for Mike
1. **Probate signal (sources 3, 4, 10) is blocked for automation.** The court's Terms bar bots; capublicnotice's user agreement bars use without written authorization and its robots disallow `/search/`; Legacy and the Union-Tribune/La Jolla Light prohibit scraping and database use. Options: (a) manual or assistant-reviewed weekly check of the court's "Lists of New Case Filings" page and newspaper legal pages, (b) email the court about a bulk/index data arrangement, (c) paid licensed data vendor, (d) ask the papers or CNPA for written permission or an API. Which do you want?
2. **Tax-default list is thin:** only 39 parcels in the two ZIPs (15 + 24) on the 2026 Impending Power to Sell list, refreshed once a year. Worth ingesting as a low-volume signal, or skip?
3. **STRO has no APN or issue date and carries host names and phone numbers.** OK to match by lat/lon to parcels, and should we avoid storing the phone column and host names (recommended)?
4. **Permit data quality:** ~64% of approvals have a blank project type, so classification will rely on approval type and scope text; ZIP must come from the parcel join. Confirm which permit types count as seller signals (e.g. demolition, ADU, large remodels, solar-only excluded).
5. **Territory definition:** 92037 includes ~3,660 University-CPA parcels (UCSD / La Jolla Village area) beyond the La Jolla CPA, and 92109 includes Mission Beach as a separate CPA. Define the territory by ZIP, by official planning area, or both? (This is about which parcels are in scope, not about drawing Bird Rock / La Jolla Shores.)
6. **Fire zones (source 6) are unresolved.** Authoritative OSFM/CNRA data did not download programmatically. Someone needs to download the statewide LRA layer by hand, or confirm the City's layer, before we say anything about 92037/92109.
7. **SB 79 / SB 9 eligibility:** the SANDAG map is draft and viewer-only, and the City's own layer was not reachable. Accept an approximate in-house screen (zoning + stops) clearly labeled unofficial, or request the City's/SANDAG's data (planning@sandiego.gov is listed by the City)?
8. **Parcel `DOCDATE`/`DOCTYPE` meaning is unconfirmed.** Before "recent transfer" or "long-term owner" signals are built, confirm the codes with SanGIS/Assessor documentation.
