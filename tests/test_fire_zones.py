import geopandas as gpd
from shapely.geometry import box

from helpers import add_parcel, add_territory, run


def test_empty_folder_records_a_failed_run_and_nothing_else(db, tmp_path):
    add_territory(db)
    add_parcel(db, "9000000001", -117.25, 32.85)
    folder = tmp_path / "fhsz"
    folder.mkdir()
    out = run("fire_zones", manual_dir=folder, report_dir=tmp_path)
    assert out.status == "failed" and out.error == "awaiting manual download"
    row = db.execute("select status, error_message from source_runs where source_key='fire_zones'").fetchone()
    assert row == ("failed", "awaiting manual download")
    assert db.execute("select count(*) from raw_records").fetchone()[0] == 0
    assert db.execute("select count(*) from signals").fetchone()[0] == 0
    assert not list(tmp_path.glob("fire_zones_match_report.md"))


def test_missing_folder_is_also_awaiting(db, tmp_path):
    add_territory(db)
    assert run("fire_zones", manual_dir=tmp_path / "nope", report_dir=tmp_path).error == "awaiting manual download"


def test_loads_a_hand_downloaded_file(db, tmp_path):
    add_territory(db)
    add_parcel(db, "9000000001", -117.250, 32.850)      # inside the zone
    add_parcel(db, "9000000002", -117.300, 32.850)      # outside
    folder = tmp_path / "fhsz"
    folder.mkdir()
    gpd.GeoDataFrame({"HAZ_CLASS": ["Very High"]}, geometry=[box(-117.26, 32.84, -117.24, 32.86)],
                     crs=4326).to_file(folder / "fhsz_test.geojson", driver="GeoJSON")
    out = run("fire_zones", manual_dir=folder, report_dir=tmp_path)
    assert out.status == "success", out.error
    rows = db.execute("select apn, signal_type, match_method, details->>'hazard_class' from signals").fetchall()
    assert rows == [("9000000001", "fire_hazard_zone", "spatial", "Very High")]
