# Permit intent: AI vs permit group (shadow mode)

22,628 permits with an AI intent. Model `openai/gpt-oss-20b`. Cost of all permit_intent calls on record: $0.69.

The AI intent is stored and shown nowhere; it does not change scores or recipes. Agreement compares it with the group `config/permit_signal_map.yaml` assigns, read as follows (the groups are not intents, so this reading is the assumption being tested):

- `pre_sale_prep` implies `prep_to_sell`
- `remodel_addition` implies `long_term_stay`
- `adu` implies `investment_or_redevelopment`
- `demolition_lot_split` implies `investment_or_redevelopment`
- `solar_energy` implies `long_term_stay`
- `other` has no implied intent (distribution only)

## Agreement per group

| Group | Permits | Agree | Agreement | Most common AI intent |
|---|---|---|---|---|
| pre_sale_prep | 4,472 | 57 | 1.3% | maintenance (66%) |
| remodel_addition | 6,732 | 2,717 | 40.4% | long_term_stay (40%) |
| adu | 347 | 336 | 96.8% | investment_or_redevelopment (97%) |
| demolition_lot_split | 526 | 462 | 87.8% | investment_or_redevelopment (88%) |
| solar_energy | 1,190 | 1,174 | 98.7% | long_term_stay (99%) |
| other | 9,361 | n/a | n/a | maintenance (63%) |

**Overall (groups with an implied intent): 4,746 of 13,267 = 35.8%.**

## Group by AI intent (permit counts)

| Group | prep_to_sell | long_term_stay | investment_or_redevelopment | maintenance | unclear |
|---|---|---|---|---|---|
| pre_sale_prep | 57 | 823 | 508 | 2,931 | 153 |
| remodel_addition | 193 | 2,717 | 857 | 2,247 | 718 |
| adu | 0 | 11 | 336 | 0 | 0 |
| demolition_lot_split | 0 | 3 | 462 | 10 | 51 |
| solar_energy | 0 | 1,174 | 6 | 8 | 2 |
| other | 28 | 604 | 579 | 5,874 | 2,276 |

## 20 sample disagreements (8,521 in total)

| Description | Group | AI intent |
|---|---|---|
| Construction change to project 578211, approval 2033334. Delta 3 scope to include revision to soffit framing, handrail/guardrail connections, and revision of non-structural beam to | remodel_addition | maintenance |
| SFR ReplaceFurnace and add all Duct Work with Electrical | pre_sale_prep | maintenance |
| Interior remodeling*****epermit***1882 | pre_sale_prep | long_term_stay |
| Disregard this job added in error. | remodel_addition | unclear |
| Construction change to approval #780652 to remove 2 patio post & increase header size, increase ridge & hip beam increased to 6x12 & add 4' wide steps on grade in front - sheet 1,2 | remodel_addition | maintenance |
| CONST CHG 474115CC CHANGE MODULES TO HYUNSUI & RELOCATE INVERTER MSP | remodel_addition | maintenance |
| OVERHEAD TO UNDERGROUND | pre_sale_prep | maintenance |
| to adjust lot line between lots 5 and 6 of Stewart's Subdivision located 1385 and 1405 Tourmaline Street. | remodel_addition | investment_or_redevelopment |
| Construction change to project 379293, approval 1325683. Reverting an ADA parking space shown on plans to non-accessible parking due to financial hardship. Sheets A1 and A2. | remodel_addition | unclear |
| CONST CHG #465940, INVERTER LOCATION AND CONDUIT. PROFESSIONAL CERTIFICATION. | remodel_addition | maintenance |
| For the associated plumbing work to the proposed interior improvement to the the existing bank branch and building common area within an existing mixed use retail building for the  | pre_sale_prep | investment_or_redevelopment |
| Mechanical permit change out heat pump 2 ton at a SDU | pre_sale_prep | maintenance |
| OH TO UG CONV. PROG. | pre_sale_prep | maintenance |
| For the construction of custom retaining wall on an existing SDU. | remodel_addition | unclear |
| underground utility district. 100 amp. rvf | pre_sale_prep | maintenance |
| Construction change for approval #823218 for electrical & plumbing revisions per field inspection. Sheet A-1, A-2, A2.1 added & A-3. | remodel_addition | maintenance |
| 1. x2 3 ton heat pump 2. x2 3 ton upflow air handler | pre_sale_prep | long_term_stay |
| Construction change from incandescent lights to LED lights. See parent approval#535859/Pts#207364 for inspections. | remodel_addition | maintenance |
| Construction Change to project 466737, approval 163309. Delta 2 revised drawing to show the existing tree and CMU wall to be reduced to 3'-0" high within visibility triangle. | remodel_addition | maintenance |
| DUCT WORK ONLY | pre_sale_prep | maintenance |

## Reading

- The AI agrees with the map where the group names the work itself: ADU (97%), solar (99%), demolition and lot split (88%).
- The one large gap is `pre_sale_prep` (1.3% agree). That group is mostly furnace, heat pump, water heater and panel replacements; the AI reads 66% of them as routine `maintenance`, not preparing to sell. The group name and its score weight imply a selling intent the permit text rarely shows. This is shadow data and changes nothing; whether to re-weight or rename the group is a decision for a later phase (see BACKLOG.md).
- `remodel_addition` splits: 40% `long_term_stay`, 33% `maintenance` (mostly construction-change revisions), 13% `investment_or_redevelopment`.
- Scope of this run: permits issued in the last 36 months or on parcels scoring 40 or more, plus the earlier unscoped batch (22,628 permits with an intent in total). The AI could not produce a valid answer for 538 permits (reply missing an item) and its quote check rejected 1,161 (paraphrased, stitched or over 12 words); none of these are shown.
