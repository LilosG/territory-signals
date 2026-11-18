"""IN-HOUSE SCREENS, NOT OFFICIAL DETERMINATIONS.

Everything in this module is an estimate (is_estimate = true on every signal) and
must be shown as "estimated eligibility" (CLAUDE.md, D7). It is not an
SB 9 or SB 79 determination by the City, SANDAG or HCD. Official data has been
requested (BACKLOG.md).

sb9_lot_split_estimate
    Parcel whose base zone is one of SB9_ZONES (the single-family RS zones, exact
    codes from the SANDAG base-zoning layer) and lot_sqft >= 2400 (two lots of at
    least 1,200 sq ft after a 40/60 split). Not checked: historic status, fire
    zone, hillside/coastal limits, existing units, ownership history.
    Planned-district single-family zones (LJSPD-SF) are NOT included: SOURCES.md
    says planned districts need rule-by-rule treatment (see BACKLOG.md).

sb79_transit_estimate
    Parcel within 200 ft, 1/4 mile or 1/2 mile (distance from the parcel polygon
    edge, EPSG:2230 feet) of a rail station or a bus-rapid-transit stop. Rail
    stations = GTFS parent stations (location_type 1) lying on a MTS/NCTD rail or
    trolley line. BRT stops = stops lying within 100 ft of an MTS "Rapid" route
    shape (route colour CC0000 or "Rapid" in the name; Super Loop excluded). The
    GTFS stop file has no service frequency or dedicated-lane data, so the BRT
    identification is a proxy and SB 79's frequency and lane tests are not applied.
The distance band is stored in details.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable

import geopandas as gpd
import shapely

from territory.net import download
from territory.sources.base import (
    NO_MATCH, Match, RawRecord, SignalCandidate, SourceAdapter,
)

SANDAG = "https://geo.sandag.org/server/rest/directories/downloads/"
STOPS_URL = SANDAG + "Transit_Stops_GTFS.geojson"
ROUTES_URL = SANDAG + "Transit_Routes_GTFS.geojson"

# Exact base-zone codes (SANDAG Zoning_Base_SD.geojson) used for the SB 9 screen.
SB9_ZONES = ("RS-1-1", "RS-1-2", "RS-1-3", "RS-1-4", "RS-1-5", "RS-1-6", "RS-1-7",
             "RS-1-8", "RS-1-9", "RS-1-10", "RS-1-11", "RS-1-12", "RS-1-13", "RS-1-14")
SB9_MIN_LOT_SQFT = 2400
BANDS = (("within_200ft", 200.0, 0.6), ("within_quarter_mile", 1320.0, 0.5),
         ("within_half_mile", 2640.0, 0.4))
SB9_CONFIDENCE = 0.5
ROUTE_PROXIMITY_FT = 100.0
NOT_CHECKED_SB9 = ["historic status", "fire hazard zone", "hillside/coastal limits",
                   "existing units", "owner occupancy/ownership history"]


def band_for(distance_ft: float):
    for name, limit, conf in BANDS:
        if distance_ft <= limit:
            return name, conf
    return None, None


def transit_points(stops: gpd.GeoDataFrame, routes: gpd.GeoDataFrame):
    """Return (rail_station_points, brt_stop_points) as GeoDataFrames in EPSG:2230."""
    stops, routes = stops.to_crs(2230), routes.to_crs(2230)
    rail = routes[routes["route_type"].isin([0, 2]) & (routes["route_id"].astype(str) != "540")]
    long = routes["route_long_name"].fillna("")
    brt = routes[(routes["route_type"] == 3) & (
        ((routes["route_color"] == "CC0000") & ~long.str.contains("Super Loop")) |
        long.str.contains("Rapid"))]
    rail_zone = rail.geometry.union_all().buffer(ROUTE_PROXIMITY_FT)
    brt_zone = brt.geometry.union_all().buffer(ROUTE_PROXIMITY_FT)
    st = stops[stops.geometry.notna()]
    rail_pts = st[(st["location_type"].astype(str) == "1") & st.intersects(rail_zone)]
    brt_pts = st[(st["location_type"].astype(str) == "0") & st.intersects(brt_zone)]
    return rail_pts, brt_pts


def nearest(parcels: gpd.GeoDataFrame, pts: gpd.GeoDataFrame, max_ft: float) -> dict[str, dict]:
    if pts.empty:
        return {}
    j = gpd.sjoin_nearest(parcels[["apn", "geometry"]], pts[["stop_UID", "stop_name", "geometry"]],
                          how="inner", max_distance=max_ft, distance_col="dist_ft")
    j = j.sort_values(["apn", "dist_ft", "stop_UID"]).drop_duplicates("apn")
    return {r.apn: {"stop_uid": r.stop_UID, "stop_name": r.stop_name, "distance_ft": round(float(r.dist_ft), 1)}
            for r in j.itertuples()}


class UpzoningEstimateAdapter(SourceAdapter):
    source_key = "upzoning_estimate"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._match: dict[str, Match] = {}

    def _file(self, key: str, url: str):
        p = self.ctx.local_files.get(key)
        return p if p else download(self.source_key, url, run_date=self.ctx.run_date)

    def fetch(self, run_id: str) -> Iterable[RawRecord]:
        rows = self.ctx.conn.execute(
            "select apn, zoning, lot_sqft, ST_AsBinary(ST_Transform(geom, 2230)) from parcels "
            "where geom is not null order by apn").fetchall()
        parcels = gpd.GeoDataFrame(
            {"apn": [r[0] for r in rows], "zoning": [r[1] for r in rows],
             "lot_sqft": [float(r[2]) if r[2] is not None else float("nan") for r in rows]},
            geometry=[shapely.from_wkb(bytes(r[3])) for r in rows], crs=2230)
        stops = gpd.read_file(self._file("transit_stops", STOPS_URL))
        routes = gpd.read_file(self._file("transit_routes", ROUTES_URL))
        rail_pts, brt_pts = transit_points(stops, routes)
        max_ft = BANDS[-1][1]
        rail = nearest(parcels, rail_pts, max_ft)
        brt = nearest(parcels, brt_pts, max_ft)
        self.notes["rail stations used"] = len(rail_pts)
        self.notes["BRT-proxy stops used"] = len(brt_pts)
        sb9_n = sb79_n = no_lot = 0
        for p in parcels.itertuples():
            sb9 = None
            zoning = p.zoning if isinstance(p.zoning, str) else None
            lot = None if p.lot_sqft != p.lot_sqft else p.lot_sqft      # NaN -> None
            if zoning in SB9_ZONES:
                if lot is None:
                    no_lot += 1
                elif lot >= SB9_MIN_LOT_SQFT:
                    sb9 = {"zoning": zoning, "lot_sqft": lot}
                    sb9_n += 1
            sb79 = None
            r, b = rail.get(p.apn), brt.get(p.apn)
            if r or b:
                best = min((x for x in (("rail_station", r), ("brt_stop_proxy", b)) if x[1]),
                           key=lambda x: x[1]["distance_ft"])
                band, conf = band_for(best[1]["distance_ft"])
                sb79 = {"distance_band": band, "confidence": conf, "nearest_mode": best[0],
                        "nearest_stop": best[1], "nearest_rail_station": r,
                        "nearest_brt_stop_proxy": b}
                sb79_n += 1
            if sb9 or sb79:
                payload = {"apn": p.apn, "zoning": zoning, "lot_sqft": lot,
                           "sb9": sb9, "sb79": sb79}
                self._match[p.apn] = Match(p.apn, "apn", 1.0)
                yield RawRecord(self.source_key, p.apn, payload)
        self.notes["SB9: RS-zone parcels with no lot_sqft (skipped)"] = no_lot
        self.notes["parcels flagged SB 9"] = sb9_n
        self.notes["parcels flagged SB 79"] = sb79_n

    def match(self, raw: RawRecord) -> Match:
        return self._match.get(raw.source_record_id, NO_MATCH)

    def safe_view(self, raw: RawRecord) -> dict:
        return {"apn": raw.source_record_id}

    def normalize(self, raw: RawRecord) -> Iterable[SignalCandidate]:
        p = raw.payload
        today = self.ctx.run_date
        label = "estimated eligibility (in-house screen, not an official determination)"
        if p.get("sb9"):
            yield SignalCandidate(
                "sb9_lot_split_estimate", "upzoning", self.source_key, raw.source_record_id,
                SB9_CONFIDENCE, "apn", p["apn"], today, is_estimate=True,
                details={"label": label, "zoning": p["sb9"]["zoning"],
                         "lot_sqft": p["sb9"]["lot_sqft"], "min_lot_sqft": SB9_MIN_LOT_SQFT,
                         "not_checked": NOT_CHECKED_SB9})
        if p.get("sb79"):
            s = p["sb79"]
            yield SignalCandidate(
                "sb79_transit_estimate", "upzoning", self.source_key, raw.source_record_id,
                s["confidence"], "spatial", p["apn"], today, is_estimate=True,
                details={"label": label, "distance_band": s["distance_band"],
                         "nearest_mode": s["nearest_mode"], "nearest_stop": s["nearest_stop"],
                         "nearest_rail_station": s["nearest_rail_station"],
                         "nearest_brt_stop_proxy": s["nearest_brt_stop_proxy"],
                         "not_checked": ["service frequency", "dedicated-lane test",
                                         "SB 79 qualifying-stop list", "fire hazard exclusions"]})
