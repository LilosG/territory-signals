# Match report: dev_permits

Generated 2026-11-18T01:06:59

| Measure | Count |
|---|---|
| Rows fetched (in territory scope, stored in raw_records) | 53924 |
| Matched to a parcel | 50744 |
| Unmatched | 3180 |
| Signals written (new rows) | 54635 |

## Match method breakdown

| Method | Rows |
|---|---|
| apn | 45340 |
| spatial | 5404 |

## Notes

- rows read from all permit files: 837279
- excluded: outside territory: 731522
- excluded: blank/unknown APN and no usable location: 32839
- distinct approvals in territory scope: 53924
- permit_signal_map status: proposed

## Example unmatched rows (max 10, no personal data)

- approval_id=1000224, approval_type=Right Of Way Permit-Const Plan, address=2274 1/3 GARNET AV , apn=None, lat=32.803003, lon=-117.228463
- approval_id=1002875, approval_type=Right Of Way Permit-Const Plan, address=1940 1/3 LITTLE ST , apn=None, lat=32.849968, lon=-117.259483
- approval_id=1009482, approval_type=Right Of Way Permit-Const Plan, address=4337 1/3 INGRAHAM ST , apn=None, lat=32.797472, lon=-117.239993
- approval_id=1009887, approval_type=Right Of Way Permit-Const Plan, address=8596 1/3 LA JOLLA SCENIC N DR , apn=None, lat=32.862792, lon=-117.24024
- approval_id=1015588, approval_type=Right Of Way Permit-Const Plan, address=5348 1/3 CHELSEA ST , apn=None, lat=32.809632, lon=-117.26637
- approval_id=1022990, approval_type=Right Of Way Permit-Const Plan, address=7755 1/3 SIERRA MAR DR , apn=None, lat=32.847822, lon=-117.261471
- approval_id=1024166, approval_type=Right Of Way Permit-Const Plan, address=6590 1/3 AVENIDA MIROLA , apn=None, lat=32.829735, lon=-117.269255
- approval_id=1029319, approval_type=Right Of Way Permit-Const Plan, address=6565 1/3 LA JOLLA SCENIC S DR , apn=None, lat=32.834013, lon=-117.249032
- approval_id=1030855, approval_type=Right Of Way Permit-Const Plan, address=7504 1/3 LA JOLLA BL , apn=None, lat=32.839291, lon=-117.278648
- approval_id=1033539, approval_type=Right Of Way Permit-Const Plan, address=1825 1/3 VIKING WY , apn=None, lat=32.849772, lon=-117.261978
