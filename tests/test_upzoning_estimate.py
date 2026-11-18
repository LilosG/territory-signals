import json

import geopandas as gpd
from pyproj import Transformer
from shapely.geometry import Point, box

import territory.sources.upzoning_estimate as up
from helpers import add_parcel, add_territory, run

TO_LONLAT = Transformer.from_crs(2230, 4326, always_xy=True)
X0, Y0 = 6_270_000.0, 1_960_000.0       # an arbitrary spot in State Plane zone 6 (feet)


def lonlat(dx, dy):
    return TO_LONLAT.transform(X0 + dx, Y0 + dy)


def square(dx, dy, side_ft=60.0):
    """Parcel polygon (WGS84) whose nearest edge is dx feet east of the station."""
    pts = [lonlat(dx + a, dy + b) for a, b in ((0, 0), (side_ft, 0), (side_ft, side_ft), (0, side_ft))]
    return box(min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))


def write_transit(tmp_path):
    stn = lonlat(0, 0)
    stops = gpd.GeoDataFrame(
        {"stop_UID": ["R1", "B1", "X1"], "stop_name": ["Test Station", "Test Rapid Stop", "Plain Bus Stop"],
         "location_type": [1, 0, 0]},
        geometry=[Point(stn), Point(lonlat(0, 4000)), Point(lonlat(0, 8000))], crs=4326)
    from shapely.geometry import LineString
    routes = gpd.GeoDataFrame(
        {"route_id": ["510", "215", "30"], "route_type": [0, 3, 3],
         "route_color": ["0000FF", "CC0000", "000099"],
         "route_long_name": ["Blue", "Mid-City Rapid", "Local"]},
        geometry=[LineString([lonlat(-500, 0), lonlat(500, 0)]),
                  LineString([lonlat(-500, 4000), lonlat(500, 4000)]),
                  LineString([lonlat(-500, 8000), lonlat(500, 8000)])], crs=4326)
    sp, rp = tmp_path / "stops.geojson", tmp_path / "routes.geojson"
    stops.to_file(sp, driver="GeoJSON")
    routes.to_file(rp, driver="GeoJSON")
    return {"transit_stops": sp, "transit_routes": rp}


def test_module_says_these_are_in_house_screens():
    doc = up.__doc__
    assert "IN-HOUSE SCREENS" in doc and "NOT OFFICIAL DETERMINATIONS" in doc
    assert "RS-1-7" in up.SB9_ZONES and "LJSPD-SF" not in up.SB9_ZONES


def test_sb9_and_sb79_signals_are_estimates_with_bands(db, tmp_path):
    add_territory(db)
    # SB 9: zone and lot size rules (all far from transit, dy = 20000 ft)
    add_parcel(db, "9000000001", 0, 0, zoning="RS-1-7", lot=6000, geom=square(0, 20000))
    add_parcel(db, "9000000002", 0, 0, zoning="RS-1-7", lot=2399, geom=square(100, 20000))
    add_parcel(db, "9000000003", 0, 0, zoning="RM-1-1", lot=9000, geom=square(200, 20000))
    add_parcel(db, "9000000004", 0, 0, zoning="LJSPD-SF", lot=9000, geom=square(300, 20000))
    add_parcel(db, "9000000005", 0, 0, zoning="RS-1-2", lot=None, geom=square(400, 20000))
    # SB 79: distance bands from the rail station (edge distance 150 ft, 1000 ft, 2000 ft, 3000 ft)
    add_parcel(db, "9000000011", 0, 0, geom=square(150, 0))
    add_parcel(db, "9000000012", 0, 0, geom=square(1000, 0))
    add_parcel(db, "9000000013", 0, 0, geom=square(2000, 0))
    add_parcel(db, "9000000014", 0, 0, geom=square(3000, 0))
    add_parcel(db, "9000000015", 0, 0, geom=square(150, 4000))     # next to the BRT-proxy stop
    add_parcel(db, "9000000016", 0, 0, geom=square(150, 8000))     # next to a plain local stop only
    out = run("upzoning_estimate", local_files=write_transit(tmp_path), report_dir=tmp_path)
    assert out.status == "success", out.error

    sb9 = {r[0] for r in db.execute("select apn from signals where signal_type='sb9_lot_split_estimate'")}
    assert sb9 == {"9000000001"}
    bands = dict(db.execute("select apn, details->>'distance_band' from signals "
                            "where signal_type='sb79_transit_estimate'").fetchall())
    assert bands == {"9000000011": "within_200ft", "9000000012": "within_quarter_mile",
                     "9000000013": "within_half_mile", "9000000015": "within_200ft"}
    modes = dict(db.execute("select apn, details->>'nearest_mode' from signals "
                            "where signal_type='sb79_transit_estimate'").fetchall())
    assert modes["9000000011"] == "rail_station" and modes["9000000015"] == "brt_stop_proxy"

    flags = db.execute("select distinct is_estimate, signal_group, source_key from signals").fetchall()
    assert flags == [(True, "upzoning", "upzoning_estimate")]
    labels = [d["label"] for (d,) in db.execute("select details from signals")]
    assert all("estimated eligibility" in l for l in labels)


def test_rerun_does_not_duplicate(db, tmp_path):
    add_territory(db)
    add_parcel(db, "9000000001", 0, 0, zoning="RS-1-7", lot=6000, geom=square(0, 20000))
    files = write_transit(tmp_path)
    run("upzoning_estimate", local_files=files, report_dir=tmp_path)
    assert run("upzoning_estimate", local_files=files, report_dir=tmp_path).signals_written == 0
