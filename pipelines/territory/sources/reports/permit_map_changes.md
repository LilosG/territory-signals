# Permit map changes (proposed -> reviewed)

Types whose signal group changed: 36 of 147 (4187 of 53924 territory approvals).

Rules applied (Phase 3 prompt): pre_sale_prep = roofing, residential electrical/plumbing/mechanical, sewer lateral, water heater, window/door, residential repair; remodel_addition = residential remodels, additions, kitchen/bath, building alterations to dwellings; adu = names ADU/accessory dwelling/companion unit/garage conversion; demolition_lot_split = demolition, parcel/tentative maps, lot splits, lot-line adjustments; solar_energy = PV/solar/battery/EV charger; other = everything else.

| APPROVAL_TYPE | Proposed | Final | Territory approvals |
|---|---|---|---|
| `Lot Tie Agreement` | demolition_lot_split | other | 8 |
| `Condominium Conversion` | demolition_lot_split | other | 1 |
| `Certificate of Compliance` | pre_sale_prep | other | 128 |
| `Zone History Letter` | pre_sale_prep | other | 67 |
| `Certificate of Correction` | pre_sale_prep | other | 11 |
| `Map - Certificate of Compliance` | pre_sale_prep | other | 8 |
| `Map - Certificate of Correction` | pre_sale_prep | other | 2 |
| `Coastal Development Permit` | remodel_addition | other | 1789 |
| `Site Development Permit` | remodel_addition | other | 654 |
| `Coastal Development` | remodel_addition | other | 308 |
| `Substantial Conformance Review` | remodel_addition | other | 174 |
| `Grading Permit` | remodel_addition | other | 164 |
| `Conditional Use Permit` | remodel_addition | other | 121 |
| `Neighborhood Use Permit` | remodel_addition | other | 117 |
| `Variance` | remodel_addition | other | 117 |
| `Neighborhood Developmnt Permit` | remodel_addition | other | 84 |
| `Planned Development Permit` | remodel_addition | other | 63 |
| `Grading + Right of Way Permit` | remodel_addition | other | 59 |
| `Site  Development Permit` | remodel_addition | other | 48 |
| `Approval - Construction - Grading-Right of Way Pmt` | remodel_addition | other | 47 |
| `Individual Historical Resource Nomination` | remodel_addition | other | 37 |
| `Approval - Construction - Grading Pmt` | remodel_addition | other | 32 |
| `Approval - Construction - Grading Pmt-Private` | remodel_addition | other | 31 |
| `Mills Act Agreement` | remodel_addition | other | 25 |
| `Neighborhood Development Permit` | remodel_addition | other | 23 |
| `Limited Use Permit` | remodel_addition | other | 16 |
| `Emergency Coastal Dev Permit` | remodel_addition | other | 15 |
| `Special Permit` | remodel_addition | other | 11 |
| `Emergency Authorization-ESL` | remodel_addition | other | 6 |
| `La Jolla Shores Planned Dist.` | remodel_addition | other | 6 |
| `Grading Permit - Private` | remodel_addition | other | 4 |
| `Variance permit` | remodel_addition | other | 4 |
| `Emergency Authorization-Hist` | remodel_addition | other | 2 |
| `La Jolla Planned District` | remodel_addition | other | 2 |
| `Sensitive Coastal Resource` | remodel_addition | other | 2 |
| `Hillside Review Overlay Zone` | remodel_addition | other | 1 |

## Notes

- Discretionary land-use approvals (coastal development, site development, conditional/neighborhood use, variance, planned district, historic) and all grading types do not name a dwelling remodel or addition, so under the rules they fall in `other`. Revisit with Mike (BACKLOG.md).
- `Electrical`, `Plumbing` and `Mechanical` permit types do not say residential or commercial; they stay in `pre_sale_prep` and only parcels with residential land use are scored.
- `Certificate of Compliance/Correction`, `Zone History Letter`, `Lot Tie Agreement` and `Condominium Conversion` are not in the rules, so they are `other`.
- No approval type names an ADU. The adu group is filled by the re-derivation step, which regroups any permit with `APPROVAL_ADU_TOTAL > 0` as `adu` (the count is kept in signal details).
