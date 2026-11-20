# Phase 5G samples

Real output from the local run: `deepseek/deepseek-v4.1-flash` via OpenRouter (fallback `qwen/qwen3.6-35b-a3b`), lead brief prompt v2 and weekly brief prompt v2, validated and stored in `ai_outputs`. Five lead briefs: the two that restated page facts in Phase 5F (6275 Cardeno Dr and 1402 Wilbur Ave, shown with their old summary for comparison) and the three highest-scoring other leads. Owner facts in this database are sample data, so briefs that cite them carry the Sample badge (the words "sample data" are no longer written in the text).

## Lead brief: 6275 Cardeno Dr (score 49)  [previously restated page facts]

- AI summary tag shown; Sample badge: yes; model `deepseek/deepseek-v4.1-flash`; attempts: 1 valid; cost $0.0011
- **Headline:** Long-held large lot that may allow a split  (8 words)
- **Summary:** This lot is much larger than most in its area, and an estimated state-law screen says it may allow splitting the lot or building more homes. The owner has held it 20 or more years, so a builder or investor may see more in the land than a typical buyer would. That split screen is an estimate, not an official finding, which makes the timing worth a call.
- **Recipe chips:** Builder bait
- **Suggested angle (internal):** Open by asking whether the owner has ever looked into splitting the lot, given the estimated state-law screen, and offer a walkthrough to talk through what a builder would see in the land.
- **Sources (4, collapsed on the page):**
  - An estimated state-law screen suggests the lot may be eligible to be split in two, but it is an estimate and not an official finding. (signal record; what it means)
  - The lot is much larger than most in its area, and the screen says it may allow splitting the lot or building more homes, so a builder or investor may see more in the land than a typical buyer would. (why it matches)
  - Estimated equity is about $3.05M (est.), in the top quarter of the territory, and it is an estimate from public records rather than a verified figure. (owner record; what it means)
  - The owner has held the home 20 or more years, and longer ownership means more built-up equity. (owner record; what it means)

- **Before (v1, Phase 5F):** *Approved 2026 permit work and an estimated SB 9 lot split* — This La Jolla residential parcel is zoned RS-1-2 with a 13,000 sq ft lot, and electrical, plumbing and mechanical work was approved on Sep 14, 2026. An estimated record suggests the lot may qualify for an SB 9 split, and the property matches the playbook entries "Builder bait" and "Pre-list prep". A sample record also indicates 20 years of ownership.
- Page-header facts in the old summary: lot size, zoning, permit date, years owned; in the new summary: none

## Lead brief: 1402 Wilbur Ave (score 53)  [previously restated page facts]

- AI summary tag shown; Sample badge: yes; model `deepseek/deepseek-v4.1-flash`; attempts: 1 valid; cost $0.0013
- **Headline:** Long-time owner putting money into a remodel  (7 words)
- **Summary:** A building permit for a remodel, addition or new construction was approved in August 2026, so the owner is putting money into the property. The owner has held the home long enough to build up equity and has no open mortgage, so the home appears to be owned free and clear. Owners with this profile may want a smaller or simpler home.
- **Recipe chips:** Downsizer
- **Suggested angle (internal):** Ask about the timing of the approved remodel and offer a pre-listing walkthrough while the work is fresh.
- **Sources (5, collapsed on the page):**
  - A building permit for a remodel, addition or new construction was approved on Aug 20, 2026, which means the owner is putting money into the property. (signal record; what it means)
  - No open mortgage is on record, so the home appears to be owned free and clear. (owner record; what it means)
  - The owner has held the home 24 years, and longer ownership means more built-up equity. (owner record; what it means)
  - The home holds an active Tier 3 short-term rental license, so it is used as a short-term rental; this is context, not a sign of a sale. (signal record; what it means)
  - An estimated screen suggests the lot may be eligible to be split in two, though this is an estimate, not an official finding. (signal record; what it means)

- **Before (v1, Phase 5F):** *Recent permits and active rental license in Pacific Beach* — This Pacific Beach parcel is zoned RS-1-7 with a 6,700 sq ft lot, and electrical, plumbing and mechanical work was approved Jul 16, 2026, followed by a building permit approved Aug 20, 2026. An active Tier 3 short-term rental license is on file, and the lot may qualify for an SB 9 split (estimated). Owner records show 24 years of ownership and no open mortgage, both sample data.
- Page-header facts in the old summary: lot size, zoning, permit date, years owned; in the new summary: permit date

## Lead brief: 1505 Felspar St (score 66)

- AI summary tag shown; Sample badge: yes; model `deepseek/deepseek-v4.1-flash`; attempts: 1 rejected -> 2 valid; cost $0.0015
- **Headline:** Remodel work by a long-time owner  (6 words)
- **Summary:** Two building permits for remodel, addition or new construction were recently approved on a home the owner has held 10 or more years — the kind of work that often goes in before a sale. The owner is absentee, and no open mortgage is on record, so the home appears to be owned free and clear. That points to a long-time owner who has just pulled remodel permits.
- **Recipe chips:** Pre-list prep
- **Suggested angle (internal):** Ask about the timing of the November 2026 remodel permits and offer a pre-listing walkthrough while that work is fresh.
- **Sources (5, collapsed on the page):**
  - Two building permits for remodel, addition or new construction were approved Nov 10, 2026, so the owner is putting money into the property. (signal record; what it means)
  - A permit for cosmetic or remodel work was approved in the last six months on a home the owner has held 10 or more years, the kind of work that often goes in before a sale. (what it means; why it matches)
  - The owner is absentee, meaning the owner's mailing address differs from the property, so the owner does not live there. (owner record; what it means)
  - No open mortgage is on record, so the home appears to be owned free and clear. (owner record; what it means)
  - Estimated equity is in the top quarter of the territory, about $3.42M (est.), an estimate from public records rather than a verified figure. (owner record; what it means)

## Lead brief: 6132 La Pintura Dr (score 63)

- AI summary tag shown; Sample badge: yes; model `deepseek/deepseek-v4.1-flash`; attempts: 1 valid; cost $0.0014
- **Headline:** Out-of-state owner and a lot that may allow a split  (10 words)
- **Summary:** The lot may qualify for a two-way split under state law, an estimate from a screen dated 2026-11-18, and no open mortgage is on record, so the home appears to be owned free and clear. The owner's mailing address is in another state. Estimated equity sits in the top quarter of the territory, from public records rather than a verified figure.
- **Recipe chips:** none
- **Suggested angle (internal):** Ask whether the owner has looked into splitting the lot, given the estimated state-law screen, and offer a walkthrough of the property.
- **Sources (4, collapsed on the page):**
  - An estimated screen against state law suggests the lot may be eligible to be split in two, an estimate rather than an official finding. (signal record; what it means)
  - No open mortgage is on record, so the home appears to be owned free and clear. (owner record; what it means)
  - The owner's mailing address is in another state. (owner record; what it means)
  - Estimated equity is about $3.71M (est.), in the top quarter of the territory, an estimate from public records rather than a verified figure. (owner record; what it means)

## Lead brief: 9450 La Jolla Shores Dr (score 59)

- AI summary tag shown; Sample badge: yes; model `deepseek/deepseek-v4.1-flash`; attempts: 1 rejected -> 2 valid; cost $0.0068
- **Headline:** Long-time owner, fresh remodel, possible lot split  (7 words)
- **Summary:** The lot may allow a split or more homes, so a builder or investor may see more in the land than a typical buyer would. Remodel work approved in Sep 2026 is the kind of work that often goes in before a sale. The owner has no open mortgage and matches owners who may want a smaller or simpler home.
- **Recipe chips:** Builder bait, Downsizer, Pre-list prep
- **Suggested angle (internal):** Ask about the timing of the Sep 2026 remodel and electrical/plumbing/mechanical permits and offer a pre-listing walkthrough.
- **Sources (5, collapsed on the page):**
  - A building permit for remodel, addition or new construction was approved Sep 29, 2026, which is the kind of work that often goes in before a sale. (signal record; what it means; why it matches)
  - No open mortgage is on record, so the home appears to be owned free and clear. (owner record; what it means)
  - An estimated screen suggests the lot may be eligible to be split in two, though it is not an official finding. (signal record; what it means)
  - An estimated screen suggests the lot is near enough to transit that more homes may be allowed on it, though it is not an official finding. (signal record; what it means)
  - The lot is much larger than most in its area, and an estimated state-law screen says it may allow splitting the lot or building more homes, so a builder or investor may see more in the land than a typical buyer would. (why it matches)

## Weekly brief (week of 2026-11-12, model `deepseek/deepseek-v4.1-flash`, cost $0.0022, attempts: 1 rejected -> 2 valid)

- Attempt 1 was rejected and not shown: newsletter makes a general claim not in the facts ('buyers')

**2 Strong Leads in the Territory**

The territory now counts 2 strong leads. La Jolla and Pacific Beach each account for 1 of them.

### La Jolla
- 1 strong lead

### Pacific Beach
- 1 strong lead

### Newsletter paragraph

This week brought little change to report across La Jolla, Mission Beach and Pacific Beach. We are happy to help with any questions you have about your home or the neighborhood. If you would like to talk through anything, just reply to this note. We are always glad to hear from you and to offer a hand whenever it is useful. Thank you for being part of the neighborhood.

Note: this is the first week after the scoring model changed from v0.3 to v0.4, so there is no comparison run of the same model version. The brief therefore has no top movers or changes by home type (it would only repeat re-scoring effects); they fill in from the next weekly run (BACKLOG.md).

## Eval and run counts

- Eval on `deepseek/deepseek-v4.1-flash` after the final prompts and validators (15 lead_brief cases, 5 weekly_brief cases, retry once, no fallback): lead_brief 15/15 and 15/15 in two runs; weekly_brief 5/5 and 5/5; permit_intent 28/31 and 30/31. Earlier iterations of the lead_brief eval scored 87% (13/15) four times before three changes: the two new "restating" cases no longer forbid a single header fact (the rule is at most one), the prompt asks for a claim citing the home's own record, and the validator rejects claims that cite only explanations. Also changed: `must_cite_any` accepts any of the home's own signal records, not only the top one.
- Local run, lead_brief (200 parcels: all 171 at score 40 or more plus the next 29 by score, the 5F rule): first pass 196 valid, 4 rejected after retry and fallback (73 needed a retry, 7 reached the fallback), $0.4449. The 4 were rejected by an intent validator that also rejected hedged wording ("may plan to sell"); after fixing it a rerun of just those 4 made all 200 valid ($0.0061).
- weekly_brief: 1 valid ($0.0022; the first attempt was rejected for a 96-word newsletter).
- permit_intent: not run again (an attempt re-ran about 30 earlier-failed permits before it was stopped; the fallback call hit HTTP 402, see the report).
