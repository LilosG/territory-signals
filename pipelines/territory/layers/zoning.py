"""Base zoning -> parcels.zoning using the largest-overlap rule."""
from __future__ import annotations

import geopandas as gpd
import shapely

from territory.layers.common import SANDAG, source_file
from territory.runner import WorkResult

URL = SANDAG + "Zoning_Base_SD.geojson"


def load_zoning(conn, run_id, client, run_date, local_files=None, **_) -> WorkResult:
    path = source_file(local_files, "zoning", "zoning", URL, run_date)
    rows = conn.execute("select apn, ST_AsBinary(geom) from parcels where geom is not null").fetchall()
    if not rows:
        raise RuntimeError("no parcels loaded; run parcels first")
    parcels = gpd.GeoDataFrame({"apn": [r[0] for r in rows]},
                               geometry=[shapely.from_wkb(bytes(r[1])) for r in rows],
                               crs=4326).to_crs(2230)
    parcels["geometry"] = parcels.geometry.make_valid()
    zones = gpd.read_file(path)[["ZONE_NAME", "geometry"]].to_crs(2230)
    zones["geometry"] = zones.geometry.make_valid()
    zones = zones[zones["ZONE_NAME"].notna()]
    inter = gpd.overlay(parcels, zones, how="intersection", keep_geom_type=False)
    inter["area"] = inter.geometry.area
    inter = inter[inter["area"] > 0]
    # largest overlap wins; ties broken by zone name so reruns are stable
    inter = inter.sort_values(["apn", "area", "ZONE_NAME"], ascending=[True, False, True])
    best = inter.drop_duplicates("apn")[["apn", "ZONE_NAME"]]
    with conn.cursor() as cur:
        cur.executemany("update parcels set zoning=%s, updated_at=now() where apn=%s",
                        [(z, a) for a, z in zip(best["apn"], best["ZONE_NAME"])])
    conn.execute("update parcels set zoning=null, updated_at=now() where apn <> all(%s) "
                 "and zoning is not null", (list(best["apn"]),))
    return WorkResult(rows_fetched=len(parcels), rows_matched=len(best),
                      rows_unmatched=len(parcels) - len(best),
                      extra={"distinct_zones": int(best["ZONE_NAME"].nunique())})
