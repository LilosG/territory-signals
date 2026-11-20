"""Hand-labelled permit cases: real descriptions from the City permit data (ids are the City's approval ids).
`ok` lists every intent a careful reader could accept; `tags` must all be present in the model's scope_tags."""
import json
from pathlib import Path

I, L, P, M, U = ("investment_or_redevelopment", "long_term_stay", "prep_to_sell", "maintenance", "unclear")
CASES = [
 ("PMT-3122346", "FOR PARTIAL DEMO OF EXISTING DETACHED GARAGE FOR A PROPOSEDF DETACHED ACCESSORY DWELLING UNIT AND NEW DETACHED GARAGE. BC Code 4333", [I], ["adu"]),
 ("PMT-3213436", "Combination Permit for the conversion of an existing accessory structure to JADU and new ADU on Second Story detached from an existing Single Family Dwelling Unit. BC CODE: 4333", [I], ["adu"]),
 ("PMT-3378012", "For a detached garage-to-ADU conversion at the rear of an (E) SDU.", [I], ["adu"]),
 ("PMT-3363361", "For the proposed conversion of (4) existing garages to (2) ADUs attached to an (E) MDU, work to include new stairs , walls, doors, windows, flooring, ceiling, roofing and associated MEP work. BC Code 4333", [I], ["adu"]),
 ("2578103", "VTM No. 2578103 for the Subdivision of a 0.23 acre -site into one (1) lot with a total of 12 residential condominiums approved by PC on 11/17/2022.", [I], []),
 ("PMT-3344301", "Proposed demolition of an existing 488.84 sqft garage and spa in the rear yard of an SDU.", [I, U, L], ["demolition"]),
 ("PMT-3353702", "Demolition/Removal Permit of (1) existing 680 sq.ft. single-story 2-bedroom dwelling unit to be demolished.", [I], ["demolition"]),
 ("703587", "Lot consolidation parcel map of lots 16 and 17 in Block 9 of La Jolla Park. Doc #2010-0102420 Rec 3/2/2010", [I, U], []),
 ("PMT-3427557", "For the Proposed Installation of (1) new illuminated wall sign for an existing commercial building.", [M, U], ["signage"]),
 ("2053920", "SFR ReplaceFurnace and add all Duct Work with Electrical", [M], ["hvac"]),
 ("1910428", "REPLACE TANKLESS WATER HEATER SFD", [M], ["plumbing"]),
 ("1690960", "CHANGE OUT FURNACE AND DUCTING", [M], ["hvac"]),
 ("PMT-3424674", "1. x2 3 ton heat pump 2. x2 3 ton upflow air handler", [M], ["hvac"]),
 ("41852", "Interior remodeling*****epermit***1882", [L, P, U], []),
 ("PMT-3309128", "For a proposed remodel of existing MDU. Proposed work to include demo of existing interior non-load bearing walls, new electrical work, and new Sauna and Jacuzzi Tub in primary bathroom.", [L, I, P], ["bath"]),
 ("PMT-3255896", "For proposed (N) 3-level SFR. Existing single-family residence to be demolished. BC CODE: 1010", [I, L], ["demolition"]),
 ("PMT-3279016", "NEW 8.4DC kW(7.82AC kWE) ROOF MOUNTED PHOTOVOLTAIC SYSTEM W/ 21 MODS AND 1 INV.", [L, M, U], ["solar"]),
 ("PMT-3381960", "ROOF MOUNTED PV SYSTEM 3.48 kW (8) SOLAR MODULES (8) MICROINVERTERS  ENERGY STORAGE 14.16 kW (2) ENPHASE IQ BATTERY 10C (1) METER COLLAR", [L, M, U], ["solar"]),
 ("PMT-3419623", "Installation of two Tesla Powerwall 3 batteries storage only.", [L, M, U], []),
 ("1526747", "Installation of Roof Mounted PV System for  SDU 1.56 kw", [L, M, U], ["solar"]),
 ("2266953", "Construction change to project 578211, approval 2033334. Delta 3 scope to include revision to soffit framing, handrail/guardrail connections, and revision of non-structural beam to foam.", [M, U], []),
 ("386334", "Disregard this job added in error.", [U], []),
 ("857549", "Construction change to approval #780652 to remove 2 patio post & increase header size, increase ridge & hip beam increased to 6x12 & add 4' wide steps on grade in front - sheet 1,2,5,6,7.", [M, U, L], []),
 ("2170766", "to adjust lot line between lots 5 and 6 of Stewart's Subdivision located 1385 and 1405 Tourmaline Street.", [I, U], []),
 ("PMT-3397385", "Emergency replacement of existing gas 40 gal water heater with a gas tankless system in the same location with the existing gas and water plumbing lines.", [M], ["plumbing"]),
 ("1449439", "New Quest Quarters (Habitable Accessory Structure) detached on 2nd floor.", [I, L], []),
 ("396545", "LA JOLLA-ROW permit to replace two existing driveways and install pavers in ROW. LJSPD-SF, Coastal", [M, L, P], []),
 ("691260", "ROW dedication for 2 new sdu's per CDP#599281/#610582.       RECORDED DOC.# 2010-0458280, O.R.", [I, U], []),
 ("2555160", "Digital-Deferred Sprinkler to Project #668331; Approval #2440550; Express-Yes. To install a complete fire sprinkler system to a SFD per 2016 NFPA 13D.", [M, U], []),
 ("PMT-3314965", "Install Package Unit. Unit #1.", [M, U], []),
 ("1750271", "Mechanical permit change out heat pump 2 ton at a SDU", [M], ["hvac"]),
]
out = [{"id": i, "description": d, "permit_type": "", "ok": ok, "tags": tags} for i, d, ok, tags in CASES]
Path(__file__).with_name("permit_intent.json").write_text(json.dumps(out, indent=1))
print(len(out), "cases")
