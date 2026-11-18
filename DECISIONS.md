# Decisions

Approved decisions, recorded 2026-11-18.

- **D1** Probate, court and obituary sources are not scraped; inheritance signals come from ATTOM recorder data or a licensed probate vendor (Phase 6). A permission request to capublicnotice/CNPA is sent separately by Mike.
- **D2** The treasurer-tax collector default list is ingested as a low-volume signal.
- **D3** STRO licenses are matched to parcels by point-in-polygon on latitude/longitude; only license id, tier, location and status are stored.
- **D4** Permit signal groups are mapped from the real distinct `APPROVAL_TYPE` values profiled in Phase 2, not guessed.
- **D5** The territory is defined by City planning areas: La Jolla, Pacific Beach, Mission Beach. ZIP is kept as an attribute. Bird Rock and La Jolla Shores stay inside La Jolla until Mike draws their boundaries.
- **D6** Fire hazard zones are added from a file Mike downloads by hand (Phase 2); never guessed.
- **D7** SB 79 and SB 9 eligibility is an in-house screen, stored with `is_estimate = true` and labeled "estimated eligibility". Official data is requested from the City or SANDAG.
- **D8** Parcel `DOCDATE` is shown only as "last recorded document date", never as a purchase date. Tenure and sales come from ATTOM.
- **D9** ATTOM is a required core source. Until the API key is added, the `SampleOwnerProvider` supplies labeled sample owner and sales records.
- **D10** Phase 5 outreach drafts are generated deterministically from recipe templates in `config/outreach_templates/`, using only scored component facts. AI-polished drafts may be added later on top of the same facts.
- **D11** California first-point-of-contact solicitation materials must show the agent's name and DRE license number; outreach cannot be approved for sending unless both are present in the client config.
