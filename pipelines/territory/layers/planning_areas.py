"""Official City community planning areas -> neighborhoods (is_official = true)."""
from __future__ import annotations

import geopandas as gpd

from territory.layers.common import SANDAG, as_multipolygon, source_file
from territory.runner import WorkResult

URL = SANDAG + "Community_Plan_SD.geojson"


def load_planning_areas(conn, run_id, client, run_date, local_files=None, **_) -> WorkResult:
    path = source_file(local_files, "planning_areas", "planning_areas", URL, run_date)
    gdf = gpd.read_file(path)
    wanted = {n.upper(): n for n in client.territory.planning_areas}
    sel = gdf[gdf["CPNAME"].str.strip().str.upper().isin(wanted)]
    found = {n.strip().upper() for n in sel["CPNAME"]}
    missing = sorted(set(wanted) - found)
    if missing:
        raise RuntimeError(f"planning areas missing from {path.name}: {missing}")
    for _, row in sel.iterrows():
        name = wanted[row["CPNAME"].strip().upper()]
        geom = as_multipolygon(row.geometry)
        existing = conn.execute(
            "select id from neighborhoods where is_official and name=%s", (name,)).fetchone()
        if existing:
            conn.execute(
                "update neighborhoods set planning_area=%s, "
                "geom=ST_SetSRID(ST_GeomFromWKB(%s),4326) where id=%s",
                (name, geom.wkb, existing[0]))
        else:
            conn.execute(
                "insert into neighborhoods (name, planning_area, geom, is_official) "
                "values (%s,%s,ST_SetSRID(ST_GeomFromWKB(%s),4326),true)",
                (name, name, geom.wkb))
    return WorkResult(rows_fetched=len(gdf), rows_matched=len(sel),
                      rows_unmatched=len(gdf) - len(sel),
                      extra={"planning_areas_loaded": sorted(wanted.values())})
