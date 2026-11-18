"""In-memory spatial and address index over the parcels table."""
from __future__ import annotations

import re
from collections import defaultdict

import shapely
from shapely import STRtree
from shapely.geometry import Point

_SUFFIX = {
    "STREET": "ST", "AVENUE": "AVE", "AV": "AVE", "BOULEVARD": "BLVD", "BL": "BLVD",
    "DRIVE": "DR", "COURT": "CT", "LANE": "LN", "ROAD": "RD", "PLACE": "PL",
    "TERRACE": "TER", "CIRCLE": "CIR", "PARKWAY": "PKWY", "HIGHWAY": "HWY",
    "WAY": "WAY", "SQUARE": "SQ", "ALLEY": "ALY", "WALK": "WALK", "TRAIL": "TRL",
}
_DIRS = {"NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W"}
_UNIT_RE = re.compile(r"\b(UNIT|APT|STE|SUITE|SPC|SPACE|BLDG|#)\b.*$")


def normalize_address(text: str | None) -> str | None:
    """'7655 Girard Ave #B, La Jolla, CA 92037' -> '7655 GIRARD AVE'. Street part only."""
    if not isinstance(text, str) or not text:
        return None
    s = text.upper().split(",")[0]
    s = s.replace("#", " # ")
    s = _UNIT_RE.sub("", s)
    s = re.sub(r"[^A-Z0-9 /]", " ", s)
    toks = []
    for t in s.split():
        t = _DIRS.get(t, t)
        toks.append(_SUFFIX.get(t, t))
    if not toks or not re.match(r"^\d", toks[0]):
        return None
    toks[0] = toks[0].lstrip("0") or "0"
    return " ".join(toks)


class ParcelIndex:
    def __init__(self, conn):
        rows = conn.execute(
            "select apn, situs_address, zip, planning_area, zoning, lot_sqft, "
            "ST_AsBinary(geom), ST_X(centroid), ST_Y(centroid) from parcels order by apn"
        ).fetchall()
        self.apns: list[str] = []
        self.info: dict[str, dict] = {}
        geoms = []
        self.by_address: dict[str, list[str]] = defaultdict(list)
        for apn, addr, zip_, pa, zoning, lot, wkb, cx, cy in rows:
            self.apns.append(apn)
            self.info[apn] = {"situs_address": addr, "zip": zip_, "planning_area": pa,
                              "zoning": zoning, "lot_sqft": float(lot) if lot is not None else None,
                              "cx": cx, "cy": cy}
            geoms.append(shapely.from_wkb(bytes(wkb)) if wkb else None)
            key = normalize_address(addr)
            if key:
                self.by_address[key].append(apn)
        self._geoms = geoms
        valid = [i for i, g in enumerate(geoms) if g is not None]
        self._valid = valid
        self._tree = STRtree([geoms[i] for i in valid]) if valid else None
        polys = conn.execute(
            "select ST_AsBinary(geom) from neighborhoods where is_official and geom is not null"
        ).fetchall()
        territory = [shapely.from_wkb(bytes(r[0])) for r in polys]
        self.territory = shapely.union_all(territory) if territory else None
        if self.territory is not None:
            shapely.prepare(self.territory)

    def __contains__(self, apn: str) -> bool:
        return apn in self.info

    def in_territory(self, lon: float, lat: float) -> bool:
        return self.territory is not None and bool(shapely.contains_xy(self.territory, lon, lat))

    def containing(self, lon: float, lat: float) -> list[str]:
        """APNs of every parcel polygon that contains the point (sorted)."""
        if self._tree is None:
            return []
        idx = self._tree.query(Point(lon, lat), predicate="intersects")
        return sorted(self.apns[self._valid[i]] for i in idx)

    def at_address(self, text: str | None) -> list[str]:
        key = normalize_address(text)
        return list(self.by_address.get(key, [])) if key else []
