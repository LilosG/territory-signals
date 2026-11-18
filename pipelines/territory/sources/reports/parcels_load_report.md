# Parcel load report

Source: SanGIS Parcels_shapefile.zip, run date 2026-11-18.

- Parcel polygons read inside the territory bounding box: 46818
- Distinct APNs after dissolving duplicate APN rows: 46710
- Loaded (centroid inside a territory planning area): 30866
- Excluded (centroid outside the three planning areas, e.g. University area): 15844

## Parcels per planning area

| Planning area | Parcels |
|---|---|
| La Jolla | 15272 |
| Mission Beach | 2446 |
| Pacific Beach | 13148 |

## DOCDATE (MMDDYY, century pivot YY<=26 -> 20YY else 19YY)

- parsed: 30763
- blank: 0
- invalid: 103
- future: 0
(blank, invalid and future values are stored as null; invalid includes the 000000 placeholder.)

## lot_sqft source

- none: 11182
- polygon_area: 2449
- usable_sq_feet: 17235

## ZIP x planning area

| Planning area | ZIP | Parcels |
|---|---|---|
| La Jolla | 92037 | 14944 |
| La Jolla | 92093 | 4 |
| La Jolla | 92109 | 37 |
| La Jolla | 92121 | 1 |
| La Jolla | None | 286 |
| Mission Beach | 92058 | 1 |
| Mission Beach | 92109 | 2359 |
| Mission Beach | 92113 | 3 |
| Mission Beach | None | 83 |
| Pacific Beach | 92037 | 9 |
| Pacific Beach | 92101 | 1 |
| Pacific Beach | 92106 | 1 |
| Pacific Beach | 92109 | 12935 |
| Pacific Beach | 92110 | 1 |
| Pacific Beach | 92121 | 1 |
| Pacific Beach | 92124 | 1 |
| Pacific Beach | None | 199 |
