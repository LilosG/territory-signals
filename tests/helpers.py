"""Shared test helpers: tiny territories, parcels, and pipeline runs."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from shapely.geometry import MultiPolygon, box

from territory.config import load_client
from territory.run import run_one

FIXTURES = Path(__file__).resolve().parent / "fixtures"
RUN_DATE = date(2026, 11, 18)
HALF = 0.00012  # ~13 m half-width: a small square parcel


def client():
    return load_client("kaiser-team")


def add_territory(conn, minx=-117.40, miny=32.60, maxx=-117.00, maxy=33.00, name="La Jolla"):
    poly = MultiPolygon([box(minx, miny, maxx, maxy)])
    conn.execute(
        "insert into neighborhoods (name, planning_area, geom, is_official) "
        "values (%s, %s, ST_SetSRID(ST_GeomFromWKB(%s), 4326), true)", (name, name, poly.wkb))


def add_parcel(conn, apn, lon, lat, half=HALF, situs=None, zoning=None, lot=None,
               zip_="92037", planning_area="La Jolla", geom=None):
    poly = geom if geom is not None else box(lon - half, lat - half, lon + half, lat + half)
    if poly.geom_type == "Polygon":
        poly = MultiPolygon([poly])
    centroid = poly.centroid
    conn.execute(
        "insert into parcels (apn, situs_address, zip, planning_area, neighborhood, geom, centroid, "
        "lot_sqft, zoning, source_key) values (%s,%s,%s,%s,%s,ST_SetSRID(ST_GeomFromWKB(%s),4326),"
        "ST_SetSRID(ST_GeomFromWKB(%s),4326),%s,%s,'test')",
        (apn, situs, zip_, planning_area, planning_area, poly.wkb, centroid.wkb, lot, zoning))


def run(key, run_date=RUN_DATE, **kwargs):
    return run_one(client(), key, run_date=run_date, **kwargs)


def all_text(conn, sql):
    """Everything a query returns, flattened to one searchable string."""
    return json.dumps(conn.execute(sql).fetchall(), default=str)
