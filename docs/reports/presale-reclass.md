# Pre-sale prep reclassification (Phase 5G, scoring model v0.3 to v0.4)

Run locally on 2026-11-19. Cloud DB untouched.

## Why

Of the 7,220 permits grouped as `pre_sale_prep`, most were like-for-like systems work (furnace, water heater, AC condenser, panel or service upgrade, repipe, sewer lateral, undergrounding). That is maintenance, not preparation to sell, yet the group carried the highest permit weight (20). `docs/reports/permit-intent-agreement.md` showed the AI agreed with the group on only 1.3% of these permits.

## Rule (D14)

The permit **type** (electrical, plumbing, mechanical, or the combined residential permit) only makes a permit a candidate. Its **description** decides, using the regex lists in `config/permit_signal_map.yaml` (`presale_rules`), first match wins:

1. Tenant improvement, office, restaurant, cell site, new building: `other`
2. Solar or battery install: `solar_energy`
3. Remodel, renovation, paint, flooring, landscaping or hardscape, facade, addition, interior improvement: `pre_sale_prep`
4. Kitchen, bath, window, door, roof, stucco, deck words: `pre_sale_prep`, unless systems-work words (repipe, drain, water heater, furnace, panel, meter, underground ...) are present
5. Everything else, including a blank description: `maintenance` (weight 0)

The rules were written and tested against the 20 disagreements in the agreement report, a random sample of 100 `pre_sale_prep` descriptions, and a read of about 300 further descriptions on both sides. Unit tests with real descriptions for both sides are in `tests/test_presale_rules.py`. The 100-permit sample comes out as: {'maintenance': 86, 'pre_sale_prep': 5, 'other': 7, 'solar_energy': 2}.

## Permits moved

**6,770 permits moved out of `pre_sale_prep`** (7,220 to 450).

| New group | Permits |
|---|---|
| maintenance | 6,146 |
| other | 507 |
| solar_energy | 117 |

About a third of the group has no description of its own; those permits have no cosmetic scope on record, so they move to `maintenance` unless their project title or scope supplies one.

## Parcels

| | Before (v0.3) | After (v0.4) |
|---|---|---|
| Pre-list prep parcels | 360 | 30 |
| Scored parcels | 26,266 | 26,266 |
| Leads at score 40 or more | 320 | 171 |
| Distinct top signals in the top 20 | 5 | 10 |

## Top 20 leads, before (v0.3)

| # | Address | Score | Top signal (group) |
|---|---|---|---|
| 1 | 6275 Cardeno Dr | 70 | Electrical, plumbing and mechanical work (pre_sale_prep) |
| 2 | 1505 Felspar St | 66 | Heating, cooling or mechanical work (pre_sale_prep) |
| 3 | 1402 Wilbur Ave | 65 | Electrical, plumbing and mechanical work (pre_sale_prep) |
| 4 | 6132 La Pintura Dr | 63 | sb9_lot_split_estimate |
| 5 | 1370 Emerald St | 63 | Electrical, plumbing and mechanical work (pre_sale_prep) |
| 6 | 375 Via Del Norte | 61 | Electrical, plumbing and mechanical work (pre_sale_prep) |
| 7 | 715 Yarmouth Ct | 60 | Electrical, plumbing and mechanical work (pre_sale_prep) |
| 8 | 9450 La Jolla Shores Dr | 59 | Electrical, plumbing and mechanical work (pre_sale_prep) |
| 9 | 904 Candlelight Pl | 58 | Electrical, plumbing and mechanical work (pre_sale_prep) |
| 10 | 1827 Amalfi St | 57 | permit_stalled |
| 11 | 1301 Virginia Way | 57 | Electrical, plumbing and mechanical work (pre_sale_prep) |
| 12 | 5520 Taft Ave | 57 | Electrical, plumbing and mechanical work (pre_sale_prep) |
| 13 | 722 Jersey Ct #A | 57 | Electrical, plumbing and mechanical work (pre_sale_prep) |
| 14 | 4944 Cass St #201 | 56 | Electrical work (pre_sale_prep) |
| 15 | 730 San Luis Rey Pl | 56 | Electrical, plumbing and mechanical work (pre_sale_prep) |
| 16 | 939 Coast Blvd #10C | 55 | Electrical work (pre_sale_prep) |
| 17 | 1320 Muirlands Dr | 55 | Electrical, plumbing and mechanical work (pre_sale_prep) |
| 18 | 6059 Wooddale Row | 55 | Electrical, plumbing and mechanical work (pre_sale_prep) |
| 19 | 5453 Cardeno Dr | 55 | Electrical, plumbing and mechanical work (pre_sale_prep) |
| 20 | 5709 Waverly Ave | 54 | Electrical, plumbing and mechanical work (pre_sale_prep) |

## Top 20 leads, after (v0.4)

| # | Address | Score | Top signal (group) |
|---|---|---|---|
| 1 | 1505 Felspar St | 66 | Heating, cooling or mechanical work (pre_sale_prep) |
| 2 | 6132 La Pintura Dr | 63 | sb9_lot_split_estimate |
| 3 | 9450 La Jolla Shores Dr | 59 | Electrical, plumbing and mechanical work (pre_sale_prep) |
| 4 | 1827 Amalfi St | 57 | permit_stalled |
| 5 | 5171 Crystal Dr | 54 | Demolition (demolition_lot_split) |
| 6 | 1402 Wilbur Ave | 53 | Building permit (remodel, addition or new construction) (adu) |
| 7 | 1421 Sandal Ln | 53 | Building permit (remodel, addition or new construction) (remodel_addition) |
| 8 | 845 Van Nuys St | 52 | stro_license_active |
| 9 | 933 Missouri St | 52 | Building permit (remodel, addition or new construction) (adu) |
| 10 | 2651 Greentree Ln | 51 | stro_license_active |
| 11 | 1404 Diamond St | 51 | stro_license_active |
| 12 | 7455 Cuvier St | 50 | permit_stalled |
| 13 | 7362 Brodiaea Way | 50 | stro_license_active |
| 14 | 6219 Camino De La Costa | 50 | Building permit (remodel, addition or new construction) (remodel_addition) |
| 15 | 6275 Cardeno Dr | 49 | sb9_lot_split_estimate |
| 16 | 1278 Pacific Beach Dr #04 | 49 | Electrical, plumbing and mechanical work (pre_sale_prep) |
| 17 | 7773 Starlight Dr | 48 | (none) |
| 18 | 7550 Eads Ave #301 | 48 | Plumbing work (pre_sale_prep) |
| 19 | 5624 La Jolla Hermosa Ave | 48 | Building permit (remodel, addition or new construction) (adu) |
| 20 | 7427 Cabrillo Ave | 47 | stro_license_active |

Top signal = the largest non-tax signal component. Scores fell for parcels whose only permit signal was routine systems work. The change is deterministic; no AI is involved in scoring.
