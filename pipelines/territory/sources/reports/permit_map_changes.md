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

## Checkpoint: residential discretionary types (conditional move to remodel_addition)

These types stay `other` in `approval_types`, and are listed under `residential_remodel_types` in the map. The record is
grouped `remodel_addition` when it is residential (the parcel's land use is a residential code, or the record's own
PROJECT_TYPE / APPROVAL_TYPE says residential); non-residential records stay `other`. Grading types are not moved.

| APPROVAL_TYPE | Default group | Group when residential | Territory approvals |
|---|---|---|---|
| `Coastal Development Permit` | other | remodel_addition | 1789 |
| `Coastal Development` | other | remodel_addition | 308 |
| `Emergency Coastal Dev Permit` | other | remodel_addition | 15 |
| `Sensitive Coastal Resource` | other | remodel_addition | 2 |
| `Site Development Permit` | other | remodel_addition | 654 |
| `Site  Development Permit` | other | remodel_addition | 48 |
| `Substantial Conformance Review` | other | remodel_addition | 174 |
| `Conditional Use Permit` | other | remodel_addition | 121 |
| `Neighborhood Use Permit` | other | remodel_addition | 117 |
| `Limited Use Permit` | other | remodel_addition | 16 |
| `Special Permit` | other | remodel_addition | 11 |
| `Variance` | other | remodel_addition | 117 |
| `Variance permit` | other | remodel_addition | 4 |
| `Neighborhood Developmnt Permit` | other | remodel_addition | 84 |
| `Neighborhood Development Permit` | other | remodel_addition | 23 |
| `Planned Development Permit` | other | remodel_addition | 63 |
| `Individual Historical Resource Nomination` | other | remodel_addition | 37 |
| `Mills Act Agreement` | other | remodel_addition | 25 |
| `Emergency Authorization-ESL` | other | remodel_addition | 6 |
| `Emergency Authorization-Hist` | other | remodel_addition | 2 |
| `La Jolla Shores Planned Dist.` | other | remodel_addition | 6 |
| `La Jolla Planned District` | other | remodel_addition | 2 |
| `Hillside Review Overlay Zone` | other | remodel_addition | 1 |

