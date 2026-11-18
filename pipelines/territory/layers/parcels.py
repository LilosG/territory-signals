"""SanGIS parcels inside the client's planning areas -> parcels.

The SanGIS Parcels.csv has no geometry, so this loader uses the SanGIS parcel
geometry download (Parcels_shapefile.zip, EPSG:2230), which carries the same
attribute columns (checked: DOCDATE identical on every row). Parcels whose
centroid is outside the territory planning areas are excluded (this removes the
University-area parcels in 92037).
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd

from territory.layers.common import SANDAG, as_multipolygon, planning_area_polygons, source_file
from territory.reports import REPORT_DIR
from territory.runner import WorkResult

URL = SANDAG + "Parcels_shapefile.zip"
SOURCE_KEY = "parcels"
USABLE_PLACEHOLDERS = {0, 99999}


def parse_docdate(value, today: date) -> tuple[date | None, str]:
    """Parse SanGIS DOCDATE (MMDDYY, two-digit year).

    Century pivot: YY <= today's two-digit year -> 20YY, otherwise 19YY (so 55 -> 1955,
    21 -> 2021). Returns (date or None, status) with status in
    parsed | blank | invalid | future. Unparseable values become None.
    """
    s = ("" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)).strip()
    if not s:
        return None, "blank"
    if len(s) != 6 or not s.isdigit():
        return None, "invalid"
    mm, dd, yy = int(s[:2]), int(s[2:4]), int(s[4:])
    year = 2000 + yy if yy <= today.year % 100 else 1900 + yy
    try:
        d = date(year, mm, dd)
    except ValueError:
        return None, "invalid"
    if d > today:
        return None, "future"
    return d, "parsed"


def build_situs(r) -> str | None:
    def g(k):
        v = r.get(k)
        return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()

    num = g("SITUS_ADDR").lstrip("0")
    street = g("SITUS_STRE")
    if not num or not street:
        return None
    parts = [num + (" " + g("SITUS_FRAC") if g("SITUS_FRAC") else ""), g("SITUS_PRE_"),
             street, g("SITUS_SUFF"), g("SITUS_POST")]
    addr = " ".join(p for p in parts if p)
    if g("SITUS_SUIT"):
        addr += " #" + g("SITUS_SUIT")
    return addr


def lot_sqft_for(usable, geom_area: float | None, shared: bool) -> tuple[float | None, str]:
    """USABLE_SQ_FEET when it is a real value (not 0 / 99999 placeholder), else the
    polygon area in sq ft when the polygon belongs to this APN alone, else None."""
    try:
        u = float(str(usable).strip())
    except (TypeError, ValueError):
        u = None
    if u is not None and u > 0 and int(u) not in USABLE_PLACEHOLDERS:
        return u, "usable_sq_feet"
    if geom_area and not shared:
        return round(float(geom_area), 1), "polygon_area"
    return None, "none"


def load_parcels(conn, run_id, client, run_date, local_files=None, report_dir=None, **_) -> WorkResult:
    path = source_file(local_files, "parcels", SOURCE_KEY, URL, run_date)
    areas = planning_area_polygons(conn, 2230)
    if areas.empty:
        raise RuntimeError("no official planning areas in neighborhoods; run planning_areas first")
    gdf = gpd.read_file(path, bbox=tuple(areas.total_bounds))
    rows_read = len(gdf)
    gdf = gdf[gdf["APN"].notna() & (gdf["APN"].str.strip() != "")].copy()
    gdf["APN"] = gdf["APN"].str.strip()
    gdf["geometry"] = gdf.geometry.force_2d().make_valid()
    gdf["_wkb"] = gdf.geometry.to_wkb()
    # a polygon shared by several APNs is a stacked condo/unit footprint
    shared_wkb = gdf.groupby("_wkb")["APN"].nunique()
    shared_wkb = set(shared_wkb[shared_wkb > 1].index)

    dissolved = gdf.dissolve(by="APN", as_index=False, aggfunc="first")
    dissolved["_shared"] = dissolved["_wkb"].isin(shared_wkb)
    dissolved["_area"] = dissolved.geometry.area
    cent = gpd.GeoDataFrame({"APN": dissolved["APN"]}, geometry=dissolved.geometry.centroid, crs=2230)
    joined = gpd.sjoin(cent, areas[["name", "geometry"]], how="left", predicate="within")
    joined = joined.drop_duplicates("APN")
    dissolved = dissolved.merge(joined[["APN", "name"]], on="APN", how="left")
    inside = dissolved[dissolved["name"].notna()].copy()
    excluded = len(dissolved) - len(inside)

    geo4326 = inside.set_geometry("geometry").to_crs(4326)
    cent4326 = gpd.GeoSeries(inside.geometry.centroid, crs=2230).to_crs(4326)
    stats: Counter = Counter()
    lot_methods: Counter = Counter()
    per_area: Counter = Counter()
    zip_by_area: Counter = Counter()
    payload = []
    for (_, r), geom, c in zip(inside.iterrows(), geo4326.geometry, cent4326):
        doc, status = parse_docdate(r.get("DOCDATE"), run_date)
        stats[status] += 1
        lot, method = lot_sqft_for(r.get("USABLE_SQ_"), r["_area"], bool(r["_shared"]))
        lot_methods[method] += 1
        zraw = str(r.get("SITUS_ZIP") or "").strip()
        zip5 = zraw[:5] if zraw[:5].isdigit() else None
        land = str(r.get("ASR_LANDUS") or "").strip() or None
        per_area[r["name"]] += 1
        zip_by_area[(r["name"], zip5)] += 1
        payload.append((r["APN"], build_situs(r), zip5, r["name"], r["name"],
                        as_multipolygon(geom).wkb, c.wkb, lot, land, doc, SOURCE_KEY))
    with conn.cursor() as cur:
        cur.executemany(
            "insert into parcels (apn, situs_address, zip, planning_area, neighborhood, geom, "
            "centroid, lot_sqft, land_use, last_recorded_doc_date, source_key) "
            "values (%s,%s,%s,%s,%s,ST_SetSRID(ST_GeomFromWKB(%s),4326),"
            "ST_SetSRID(ST_GeomFromWKB(%s),4326),%s,%s,%s,%s) "
            "on conflict (apn) do update set situs_address=excluded.situs_address, "
            "zip=excluded.zip, planning_area=excluded.planning_area, "
            "neighborhood=excluded.neighborhood, geom=excluded.geom, centroid=excluded.centroid, "
            "lot_sqft=excluded.lot_sqft, land_use=excluded.land_use, "
            "last_recorded_doc_date=excluded.last_recorded_doc_date, "
            "source_key=excluded.source_key, updated_at=now()", payload)

    extra = {"docdate": dict(stats), "lot_sqft_method": dict(lot_methods),
             "parcels_per_planning_area": dict(per_area), "excluded_outside_territory": excluded}
    lines = [
        "# Parcel load report", "",
        f"Source: SanGIS Parcels_shapefile.zip, run date {run_date}.", "",
        f"- Parcel polygons read inside the territory bounding box: {rows_read}",
        f"- Distinct APNs after dissolving duplicate APN rows: {len(dissolved)}",
        f"- Loaded (centroid inside a territory planning area): {len(inside)}",
        f"- Excluded (centroid outside the three planning areas, e.g. University area): {excluded}", "",
        "## Parcels per planning area", "", "| Planning area | Parcels |", "|---|---|",
        *[f"| {k} | {v} |" for k, v in sorted(per_area.items())], "",
        "## DOCDATE (MMDDYY, century pivot YY<=26 -> 20YY else 19YY)", "",
        *[f"- {k}: {stats.get(k, 0)}" for k in ("parsed", "blank", "invalid", "future")],
        "(blank, invalid and future values are stored as null; invalid includes the 000000 placeholder.)", "",
        "## lot_sqft source", "",
        *[f"- {k}: {v}" for k, v in sorted(lot_methods.items())], "",
        "## ZIP x planning area", "", "| Planning area | ZIP | Parcels |", "|---|---|---|",
        *[f"| {a} | {z} | {n} |" for (a, z), n in sorted(zip_by_area.items(), key=lambda x: (x[0][0], str(x[0][1])))],
    ]
    d = Path(report_dir) if report_dir else REPORT_DIR
    d.mkdir(parents=True, exist_ok=True)
    (d / "parcels_load_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return WorkResult(rows_fetched=len(dissolved), rows_matched=len(inside),
                      rows_unmatched=excluded, extra=extra)
