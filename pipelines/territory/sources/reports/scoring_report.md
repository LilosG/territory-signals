# Scoring report

Model v0.5-handset, as of 2026-11-21.

- residential parcels: 26591; scored: 26268; non-residential (not scored): 4275
- suppressed: {'sale within 24 months': 323}
- fire-zone data loaded: False
- est_equity top-quartile cutoff (territory 75th percentile): 3022784.06

## builder_bait lot-size medians

Median lot_sqft of residential parcels with a known lot size, per planning area. builder_bait requires lot_sqft >= 1.5 x the median of the parcel's planning area.

| Planning area | Median lot_sqft | Threshold (lot_sqft >=) |
|---|---|---|
| La Jolla | 8000.0 | 12000.0 |
| Mission Beach | 2400.0 | 3600.0 |
| Pacific Beach | 6250.0 | 9375.0 |
