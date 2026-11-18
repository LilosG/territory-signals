"""CAL FIRE Fire Hazard Severity Zones, loaded from a file Mike downloads by hand
into data/manual/fhsz/ (D6). This module never fetches anything itself.

If the folder holds no readable file the run is recorded as failed with
error_message "awaiting manual download" and nothing else happens.

Accepted files: .geojson / .json, .gpkg, .shp (with sidecars) or a .zip of a
shapefile / geodatabase. The hazard-class column is auto-detected
(HAZ_CLASS, HAZ_CODE, FHSZ, GRIDCODE, ...). Signal: fire_hazard_zone for each
parcel whose polygon intersects a zone polygon (largest overlap decides when a
parcel straddles two classes), with the class in details.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import geopandas as gpd
import shapely

from territory.net import DATA_DIR
from territory.sources.base import (
    AwaitingManualDownload, CONF_SPATIAL, NO_MATCH, Match, RawRecord, SignalCandidate,
    SourceAdapter,
)

MANUAL_DIR = DATA_DIR / "manual" / "fhsz"
EXTENSIONS = (".geojson", ".json", ".gpkg", ".shp", ".zip")
CLASS_COLUMNS = ("HAZ_CLASS", "HAZ_CODE", "HAZCLASS", "FHSZ", "FHSZ_DESCRIPTION", "FHSZ_DESC",
                 "HAZARD", "GRIDCODE", "Class", "CLASS")


def find_file(folder: Path) -> Path | None:
    if not folder.exists():
        return None
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS)
    return files[0] if files else None


class FireZonesAdapter(SourceAdapter):
    source_key = "fire_zones"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._match: dict[str, Match] = {}

    def fetch(self, run_id: str) -> Iterable[RawRecord]:
        folder = Path(self.ctx.manual_dir) if self.ctx.manual_dir else MANUAL_DIR
        path = find_file(folder)
        if path is None:
            raise AwaitingManualDownload(str(folder))
        zones = gpd.read_file(path)
        if zones.crs is None:
            raise ValueError(f"{path.name} has no CRS; cannot place it on parcels")
        col = next((c for c in CLASS_COLUMNS if c in zones.columns), None)
        if col is None:
            raise ValueError(f"no hazard-class column found in {path.name}; columns: {list(zones.columns)}")
        zones = zones.to_crs(2230)
        zones["geometry"] = zones.geometry.make_valid()
        rows = self.ctx.conn.execute(
            "select apn, ST_AsBinary(ST_Transform(geom, 2230)) from parcels where geom is not null "
            "order by apn").fetchall()
        parcels = gpd.GeoDataFrame({"apn": [r[0] for r in rows]},
                                   geometry=[shapely.from_wkb(bytes(r[1])) for r in rows], crs=2230)
        parcels["geometry"] = parcels.geometry.make_valid()
        inter = gpd.overlay(parcels, zones[[col, "geometry"]], how="intersection", keep_geom_type=False)
        inter["area"] = inter.geometry.area
        inter = inter[inter["area"] > 0].sort_values(["apn", "area"], ascending=[True, False])
        best = inter.drop_duplicates("apn")
        self.notes["source file"] = path.name
        self.notes["hazard class column"] = col
        self.notes["parcels in the territory"] = len(parcels)
        for r in best.itertuples():
            cls = str(getattr(r, col))
            self._match[r.apn] = Match(r.apn, "spatial", CONF_SPATIAL)
            yield RawRecord(self.source_key, r.apn, {"apn": r.apn, "hazard_class": cls,
                                                    "source_file": path.name})

    def match(self, raw: RawRecord) -> Match:
        return self._match.get(raw.source_record_id, NO_MATCH)

    def normalize(self, raw: RawRecord) -> Iterable[SignalCandidate]:
        m = self.match(raw)
        if not m.apn:
            return
        yield SignalCandidate(
            "fire_hazard_zone", "risk", self.source_key, raw.source_record_id, m.confidence,
            m.method, m.apn, self.ctx.run_date,
            details={"hazard_class": raw.payload["hazard_class"],
                     "source_file": raw.payload["source_file"]})
