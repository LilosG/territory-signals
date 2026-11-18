from datetime import date

import geopandas as gpd
import shapely
from shapely.geometry import box

from helpers import FIXTURES, RUN_DATE, run
from territory.layers.parcels import lot_sqft_for, parse_docdate

TODAY = date(2026, 11, 18)


def test_docdate_is_parsed_as_mmddyy_with_a_century_pivot():
    assert parse_docdate("061905", TODAY) == (date(2005, 6, 19), "parsed")
    assert parse_docdate("052279", TODAY) == (date(1979, 5, 22), "parsed")
    assert parse_docdate("110315", TODAY) == (date(2015, 11, 3), "parsed")
    assert parse_docdate("010126", TODAY) == (date(2026, 1, 1), "parsed")
    assert parse_docdate("010127", TODAY) == (date(1927, 1, 1), "parsed")


def test_unparseable_docdates_become_null_and_are_counted_by_kind():
    assert parse_docdate("000000", TODAY) == (None, "invalid")
    assert parse_docdate("133115", TODAY) == (None, "invalid")      # month 13
    assert parse_docdate("023015", TODAY) == (None, "invalid")      # Feb 30
    assert parse_docdate("12ab15", TODAY) == (None, "invalid")
    assert parse_docdate("1215", TODAY) == (None, "invalid")
    assert parse_docdate("", TODAY) == (None, "blank")
    assert parse_docdate(None, TODAY) == (None, "blank")
    assert parse_docdate("122526", TODAY) == (None, "future")       # after the run date


def test_lot_sqft_rules():
    assert lot_sqft_for("04200", 5000, False) == (4200.0, "usable_sq_feet")
    assert lot_sqft_for("99999", 5000.04, False) == (5000.0, "polygon_area")
    assert lot_sqft_for("00000", 5000, False) == (5000.0, "polygon_area")
    assert lot_sqft_for(None, 5000, True) == (None, "none")          # stacked condo polygon


def test_planning_areas_load_as_official_neighborhoods(db, tmp_path):
    out = run("planning_areas", local_files={"planning_areas": FIXTURES / "planning_areas_fixture.geojson"})
    assert out.status == "success", out.error
    rows = db.execute("select name, planning_area, is_official from neighborhoods order by name").fetchall()
    assert rows == [("La Jolla", "La Jolla", True), ("Mission Beach", "Mission Beach", True),
                    ("Pacific Beach", "Pacific Beach", True)]
    # idempotent
    run("planning_areas", local_files={"planning_areas": FIXTURES / "planning_areas_fixture.geojson"})
    assert db.execute("select count(*) from neighborhoods").fetchone()[0] == 3


def _parcel_gdf(db):
    pts = dict(db.execute("select name, ST_AsBinary(ST_PointOnSurface(geom)) from neighborhoods").fetchall())
    rows = []
    for i, (name, wkb) in enumerate(sorted(pts.items())):
        p = shapely.from_wkb(bytes(wkb))
        rows.append((f"30000000{i}0", name, p.x, p.y))
    gdf = gpd.GeoDataFrame(
        {"APN": [r[0] for r in rows], "SITUS_ADDR": ["0123"] * 3, "SITUS_STRE": ["TEST"] * 3,
         "SITUS_SUFF": ["ST"] * 3, "SITUS_ZIP": ["92037-1234"] * 3, "DOCDATE": ["061905", "000000", "110315"],
         "USABLE_SQ_": ["04200", "99999", None], "ASR_LANDUS": ["11"] * 3},
        geometry=[box(r[2] - 0.0001, r[3] - 0.0001, r[2] + 0.0001, r[3] + 0.0001) for r in rows], crs=4326)
    outside = gpd.GeoDataFrame(
        {"APN": ["3999999990"], "SITUS_ADDR": ["1"], "SITUS_STRE": ["ELSEWHERE"], "SITUS_SUFF": ["ST"],
         "SITUS_ZIP": ["92122"], "DOCDATE": ["010199"], "USABLE_SQ_": ["01000"], "ASR_LANDUS": ["11"]},
        geometry=[box(-117.230, 32.870, -117.229, 32.871)], crs=4326)       # University area
    return pd_concat(gdf, outside)


def pd_concat(a, b):
    import pandas as pd
    return gpd.GeoDataFrame(pd.concat([a, b], ignore_index=True), crs=4326)


def test_parcels_inside_the_planning_areas_only_and_zoning_largest_overlap(db, tmp_path):
    run("planning_areas", local_files={"planning_areas": FIXTURES / "planning_areas_fixture.geojson"})
    gdf = _parcel_gdf(db)
    path = tmp_path / "parcels.gpkg"
    gdf.to_crs(2230).to_file(path, driver="GPKG")
    out = run("parcels", local_files={"parcels": path}, report_dir=tmp_path)
    assert out.status == "success", out.error
    assert out.rows_matched == 3 and out.rows_unmatched == 1          # University parcel excluded
    rows = db.execute("select apn, planning_area, neighborhood, zip, situs_address, last_recorded_doc_date, "
                      "lot_sqft, land_use from parcels order by apn").fetchall()
    assert [r[1] for r in rows] == ["La Jolla", "Mission Beach", "Pacific Beach"]
    assert all(r[1] == r[2] and r[3] == "92037" and r[4] == "123 TEST ST" for r in rows)
    assert [r[5] for r in rows] == [date(2005, 6, 19), None, date(2015, 11, 3)]   # 000000 -> null
    assert float(rows[0][6]) == 4200.0 and rows[0][7] == "11"
    assert float(rows[1][6]) > 0                                      # 99999 placeholder -> polygon area
    assert out.extra["docdate"] == {"parsed": 2, "invalid": 1}
    assert "Parcels per planning area" in (tmp_path / "parcels_load_report.md").read_text()

    # zoning: the zone covering most of the parcel wins
    apn, (x0, y0, x1, y1) = rows[0][0], gdf.iloc[0].geometry.bounds
    xm = x0 + (x1 - x0) * 0.7
    zones = gpd.GeoDataFrame({"ZONE_NAME": ["RS-1-7", "RM-1-1"]},
                             geometry=[box(x0 - 1e-6, y0 - 1e-6, xm, y1 + 1e-6), box(xm, y0 - 1e-6, x1 + 1e-6, y1 + 1e-6)], crs=4326)
    zp = tmp_path / "zones.geojson"
    zones.to_file(zp, driver="GeoJSON")
    z = run("zoning", local_files={"zoning": zp})
    assert z.status == "success", z.error
    got = dict(db.execute("select apn, zoning from parcels").fetchall())
    assert got[apn] == "RS-1-7"
    assert z.rows_matched == 1 and z.rows_unmatched == 2              # the other two parcels are not covered
