"""Helpers shared by the base layers."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import geopandas as gpd
import shapely
from shapely.geometry import MultiPolygon

from territory.net import download

SANDAG = "https://geo.sandag.org/server/rest/directories/downloads/"


def source_file(local_files: dict | None, key: str, source_key: str, url: str,
                run_date: date) -> Path:
    if local_files and key in local_files:
        return Path(local_files[key])
    return download(source_key, url, run_date=run_date)


def as_multipolygon(geom):
    geom = shapely.force_2d(geom)
    if geom.geom_type == "Polygon":
        return MultiPolygon([geom])
    if geom.geom_type == "MultiPolygon":
        return geom
    polys = [g for g in getattr(geom, "geoms", []) if g.geom_type in ("Polygon", "MultiPolygon")]
    parts = []
    for g in polys:
        parts.extend(g.geoms if g.geom_type == "MultiPolygon" else [g])
    return MultiPolygon(parts)


def planning_area_polygons(conn, crs: int) -> gpd.GeoDataFrame:
    """Official territory planning areas from the neighborhoods table."""
    rows = conn.execute(
        "select name, ST_AsBinary(geom) from neighborhoods where is_official and geom is not null"
    ).fetchall()
    gdf = gpd.GeoDataFrame({"name": [r[0] for r in rows]},
                           geometry=[shapely.from_wkb(bytes(r[1])) for r in rows], crs=4326)
    return gdf.to_crs(crs)
