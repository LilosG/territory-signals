# Model selection (Phase 5F)

Catalog: OpenRouter `/api/v1/models`, fetched 2026-11-19. Eval: `tests/llm_eval/` (31 permit_intent, 10 lead_brief, 3 weekly_brief cases), `python -m territory.llm.eval`. Every request sends `provider.data_collection = deny` and `require_parameters = true`, so only endpoints that do not retain or train on prompts serve it; the catalog descriptions are too short to be a reliable retention signal on their own.

Filters: structured outputs or response_format; context >= 64k; no free, beta, preview, contributor, batch or specialty (code, image, audio, vision, safety) variants; established lab (OpenAI, Google, DeepSeek, Qwen, Mistral, Meta, xAI, Anthropic, Moonshot, Z.ai). Ranked by input + 3 x output price.

## permit_intent: the 4 cheapest plus a mid-priced reference

| Model | $/M in | $/M out | permit_intent | Eval cost | Chosen |
|---|---|---|---|---|---|
| `mistralai/mistral-nemo` | 0.029 | 0.030 | 16/31 (52%) | $0.0005 | no |
| `meta-llama/llama-3.1-8b-instruct` | 0.020 | 0.040 | 21/31 (68%) | $0.0011 | no |
| `openai/gpt-oss-20b` | 0.018 | 0.090 | 29/31 (94%) | $0.0007 | **yes** |
| `google/gemma-3-4b-it` | 0.050 | 0.100 | 23/31 (74%) | $0.0002 | no |
| `qwen/qwen3.6-27b` (reference) | 0.320 | 3.200 | 30/31 (97%) | $0.0525 | no |

Rerun of the chosen model: 30/31 (97%), so it holds. **permit_intent -> `openai/gpt-oss-20b`** ($0.018 / $0.090 per M): cheapest model at or above 90%.

## lead_brief and weekly_brief: models of at least ~20B parameters

Small models were dropped for these two tasks (llama-3.1-8b scored 10/10 on lead_brief but 1/3 on weekly_brief; gemma-3-4b 0/3; gpt-oss-20b 7/10 on lead_brief). Candidates: the current DeepSeek chat model, the best-value current Qwen of at least 30B with structured outputs, and the qwen3.6-27b reference.

| Model | $/M in | $/M out | lead_brief | weekly_brief | Eval cost | Cost per lead brief | Cost per weekly brief | Projected monthly* |
|---|---|---|---|---|---|---|---|---|
| `deepseek/deepseek-v4.1-flash` | 0.051 | 0.567 | 10/10 (100%) | 3/3 (100%) | $0.0134 | $0.0007 | $0.0015 | $0.31 |
| `qwen/qwen3.6-35b-a3b` | 0.100 | 0.900 | 9/10 (90%) | 3/3 (100%) | $0.0408 | $0.0031 | $0.0053 | $1.37 |
| `qwen/qwen3.6-27b (reference)` | 0.320 | 3.200 | 9/10 (90%) | 3/3 (100%) | $0.3628 | $0.0110 | $0.0113 | $4.82 |

\* Projected monthly cost of weekly runs = 4.33 x (1 weekly brief + 100 lead briefs). 100 is an assumption for leads whose facts changed that week; unchanged leads are cached and cost nothing. Costs per brief are measured on the three samples below. Permit intent is a one-time cost plus new permits only.

## Side by side: the same 3 top leads and the weekly brief

Lead addresses are left out here; the packets are the same for every model. Sample data is flagged in the records.

### Lead 1 (score 70)

Records the model saw:

- R1: Residential parcel in La Jolla, zoned RS-1-2, lot 13,000 sq ft
- R2: Electrical, plumbing and mechanical work approved Sep 14, 2026
- R3: Owned 20 years (sample data)
- R4: Equity in the top quarter of the territory (sample data, estimated); estimated equity about $3,047,960
- R5: Lot may qualify for an SB 9 split (estimated)
- R6: Matches the playbook: Builder bait, Pre-list prep

**deepseek/deepseek-v4.1-flash** (valid)

- Headline: Recent permits and a large La Jolla lot
- Summary: This La Jolla home sits on a 13,000 sq ft RS-1-2 residential lot, and electrical, plumbing and mechanical work was approved on Sep 14, 2026. Sample data shows 20 years of ownership, and an estimate flags that the lot may qualify for an SB 9 split. It matches the Builder bait and Pre-list prep playbooks.
- Claims: The subject is a residential parcel in La Jolla, zoned RS-1-2, with a 13,000 sq ft lot. / Electrical, plumbing and mechanical work was approved on Sep 14, 2026. / Sample data shows the home has been owned 20 years. / The lot may qualify for an SB 9 split, which is an estimate. / The property matches the Builder bait and Pre-list prep playbooks.
- Suggested angle: Open with a La Jolla market update and recent permit activity nearby, then ask whether a walkthrough of the lot and its options would be useful.

**qwen/qwen3.6-35b-a3b** (valid)

- Headline: Large La Jolla lot with recent permits and builder potential
- Summary: This residential parcel in La Jolla features a 13,000 square foot lot zoned RS-1-2 and recently had electrical, plumbing, and mechanical work approved on September 14, 2026. Sample data shows the property has been owned for 20 years and matches builder-focused playbooks. Recent permit approvals combined with estimated subdivision eligibility create a timely window for development-focused buyers.
- Claims: The property is a residential parcel in La Jolla zoned RS-1-2 with a 13,000 square foot lot. / Electrical, plumbing, and mechanical work was approved on September 14, 2026. / Sample data indicates the owner has held the property for 20 years. / Estimated equity sits in the top quarter of the territory, valued at approximately $3,047,960. / The lot may qualify for an SB 9 split, which is estimated.
- Suggested angle: Consider opening the conversation by offering a current market update for La Jolla parcels that have recently cleared building permits.

**qwen/qwen3.6-27b (reference)** (valid)

- Headline: La Jolla Lot With Approved Renovations And Potential SB 9 Split
- Summary: This La Jolla property sits on a 13,000 sq ft lot with recently approved electrical, plumbing, and mechanical work. The parcel may also qualify for an SB 9 split, aligning with builder bait and pre-list prep strategies. These recent approvals and development potential make it a timely opportunity for targeted outreach.
- Claims: The 13,000 sq ft La Jolla lot recently received approvals for electrical, plumbing, and mechanical work on Sep 14, 2026. / The property may qualify for an SB 9 lot split, according to an estimated assessment. / Sample data estimates the owner's equity at approximately $3,047,960, placing it in the top quarter of the territory.
- Suggested angle: Consider opening with a brief market update on recent La Jolla renovation trends and local development opportunities to naturally introduce the property's potential.

### Lead 2 (score 66)

Records the model saw:

- R1: Residential parcel in Pacific Beach, zoned RM-2-5, lot 6,250 sq ft
- R2: Heating, cooling or mechanical work approved Nov 10, 2026
- R3: Owner is absentee (sample data)
- R4: No open mortgage (sample data)
- R5: 2 building permits (remodel, addition or new construction) approved Nov 10, 2026
- R6: Building permit (remodel, addition or new construction) approved Nov 10, 2026
- R7: Equity in the top quarter of the territory (sample data, estimated); estimated equity about $3,420,000
- R8: Matches the playbook: Pre-list prep

**deepseek/deepseek-v4.1-flash** (valid)

- Headline: Recent permits and sample owner signals make this worth a look
- Summary: This Pacific Beach residential parcel saw building permits for remodel, addition or new construction approved on Nov 10, 2026, along with heating, cooling or mechanical work the same day. Sample data also flags an absentee owner and no open mortgage, with estimated equity in the top quarter of the territory. It matches the playbook: Pre-list prep.
- Claims: The subject is a residential parcel in Pacific Beach, zoned RM-2-5, with a 6,250 sq ft lot. / Building permits for remodel, addition or new construction were approved Nov 10, 2026, and heating, cooling or mechanical work was approved the same day. / Sample data indicates the owner is absentee and there is no open mortgage. / Sample data estimates equity in the top quarter of the territory, at about $3,420,000 (estimated). / The property matches the playbook: Pre-list prep.
- Suggested angle: Open with a Pacific Beach market update and recent permit activity nearby, then ask whether they have thought about timing for pre-list prep.

**qwen/qwen3.6-35b-a3b** (valid)

- Headline: Pacific Beach parcel with recent mechanical and building permits.
- Summary: This residential parcel in Pacific Beach features a 6,250 square foot lot zoned RM-2-5. Recent approvals on November 10, 2026 include heating, cooling, mechanical work alongside two building permits for remodeling or additions. These active development signals align with the pre-list prep playbook, making it a timely prospect for engagement.
- Claims: This residential parcel in Pacific Beach is zoned RM-2-5 and covers 6,250 square feet. / Heating, cooling, or mechanical work received approval on November 10, 2026. / Two building permits for remodeling, addition, or new construction were approved on November 10, 2026. / Equity is estimated in the top quarter of the territory at about $3,420,000, based on sample data. / The listing aligns with the pre-list prep playbook.
- Suggested angle: Offer a brief overview of current Pacific Beach inventory levels and recent sales activity to gauge interest in upcoming listings.

**qwen/qwen3.6-27b (reference)** (valid)

- Headline: Pacific Beach Home With Recent Permits And High Estimated Equity
- Summary: This Pacific Beach residential lot features recent mechanical and building permits approved in November 2026, indicating active renovation work. The property aligns with a pre-list prep strategy and shows estimated equity in the top quarter of the territory. These factors make it a timely opportunity for focused outreach.
- Claims: Building permits for remodel, addition or new construction and a mechanical work permit were approved on November 10, 2026. / Sample data estimates the property's equity at approximately $3,420,000, placing it in the top quarter of the territory. / The Pacific Beach residential parcel matches a pre-list prep playbook strategy.
- Suggested angle: Consider opening the conversation by offering a complimentary neighborhood market update and highlighting recent renovation trends in Pacific Beach.

### Lead 3 (score 65)

Records the model saw:

- R1: Residential parcel in Pacific Beach, zoned RS-1-7, lot 6,700 sq ft
- R2: Owned 24 years (sample data)
- R3: No open mortgage (sample data)
- R4: Electrical, plumbing and mechanical work approved Jul 16, 2026
- R5: Building permit (remodel, addition or new construction) approved Aug 20, 2026
- R6: Building permit (remodel, addition or new construction) approved Aug 20, 2026
- R7: Holds an active Tier 3 short-term rental license
- R8: Lot may qualify for an SB 9 split (estimated)
- R9: Matches the playbook: Downsizer, Pre-list prep

**deepseek/deepseek-v4.1-flash** (valid)

- Headline: Recent permits and an active rental license in Pacific Beach
- Summary: This Pacific Beach parcel has two recent development permits: electrical, plumbing and mechanical work approved Jul 16, 2026, and a building permit for remodel, addition or new construction approved Aug 20, 2026. It also holds an active Tier 3 short-term rental license, and the lot is estimated to possibly qualify for an SB 9 split. Sample data shows 24 years of ownership with no open mortgage, and the property matches the playbook: Downsizer, Pre-list prep.
- Claims: The subject is a residential parcel in Pacific Beach, zoned RS-1-7, with a 6,700 sq ft lot. / Electrical, plumbing and mechanical work was approved Jul 16, 2026. / A building permit for remodel, addition or new construction was approved Aug 20, 2026. / The property holds an active Tier 3 short-term rental license. / Sample data shows 24 years of ownership and no open mortgage, and the lot is estimated to possibly qualify for an SB 9 split.
- Suggested angle: Open with a Pacific Beach market update and offer to walk through how recent permit activity in the area is showing up in current values.

**qwen/qwen3.6-35b-a3b** (valid)

- Headline: Pacific Beach parcel with recent permits, rental license, and downsizer potential
- Summary: This Pacific Beach residential parcel offers a 6,700-square-foot lot zoned RS-1-7 and holds an active Tier 3 short-term rental license. Recent development signals show electrical, plumbing, and mechanical work approved on July 16, 2026, alongside a building permit for a remodel or addition approved August 20, 2026. The property aligns with the downsizer and pre-list prep playbook, making it worth reviewing now.
- Claims: This Pacific Beach residential parcel is zoned RS-1-7 and sits on a 6,700 square foot lot. / The property holds an active Tier 3 short-term rental license. / Electrical, plumbing, and mechanical work were approved on July 16, 2026, followed by a building permit for a remodel or addition on August 20, 2026.
- Suggested angle: The agent could open by offering a brief overview of current Pacific Beach inventory levels and recent permit activity in the neighborhood.

**qwen/qwen3.6-27b (reference)** (valid)

- Headline: Pacific Beach Home With Active Rental License and Recent Remodel Permits
- Summary: This Pacific Beach property sits on a 6,700-square-foot lot and currently holds an active Tier 3 short-term rental license. Recent development activity includes approved electrical, plumbing, and mechanical work in July 2026, followed by building permits for a remodel or addition in August 2026. The lot may also qualify for an SB 9 split (estimated), aligning with a pre-list preparation strategy.
- Claims: The residential parcel is located in Pacific Beach and features a 6,700-square-foot lot zoned RS-1-7. / Electrical, plumbing, and mechanical work was approved on July 16, 2026, and a building permit for a remodel or addition was approved on August 20, 2026. / The property currently holds an active Tier 3 short-term rental license. / The lot may qualify for an SB 9 split, which is an estimated possibility.
- Suggested angle: Lead with a neighborhood market update focusing on recent development trends and short-term rental regulations in Pacific Beach.

### Weekly brief

**deepseek/deepseek-v4.1-flash** (valid)

- Title: No new strong leads; La Jolla adds 4 pre-sale permits
- Intro: The territory holds 7 strong leads with none new this week, and 4 new pre-sale permits arrived, all of them in La Jolla. No new short-term rental removals were recorded, and neighborhood counts either eased or held steady against the earliest available baseline.
- La Jolla: 3 strong leads now, with none new this week. 4 new pre-sale permits, the only ones recorded in the territory this week. Tax-default total is 15, with none new this week. Top movers include 5598 CORAL REEF AVE (48 to 18) and 1260 RHODA DR (66 to 37).
- Mission Beach: 1 strong lead now, with none new this week. No new pre-sale permits, and the tax-default total is 0 with none new this week. Pre-list prep count held at 16, unchanged from the baseline. Top movers include 3932 BAYSIDE WALK (38 to 16) and 3595 BAYSIDE WALK (52 to 30).
- Pacific Beach: 3 strong leads now, with none new this week. No new pre-sale permits this week. Tax-default total is 24, with none new this week. Top movers include 1260 BERYL ST (60 to 29) and 1059 REED AVE (48 to 18).
- Newsletter paragraph: It has been a steady week across La Jolla, Pacific Beach and Mission Beach. Most of the activity we track eased rather than grew, and no new short-term rental removals were recorded in any of the three neighborhoods. La Jolla saw 4 new pre-sale permits, while Pacific Beach and Mission Beach saw none. If you have been thinking about a project, a refresh or a future move, this is a good moment to plan ahead and get your questions answered early.

**qwen/qwen3.6-35b-a3b** (valid)

- Title: November 12 to 19 Territory Market Update
- Intro: This week, the territory recorded seven active opportunities across three neighborhoods with four new pre-sale permits issued. Strong opportunity counts remained steady while new activity paused.
- La Jolla: 3 active opportunities remain with 4 new pre-sale permits filed this week. The area shows 15 total tax defaults and 0 new removals. Inventory lists 24 tired landlords, 364 builder bait properties, 224 pre-list prep homes, 168 stalled projects, and 1315 downsizers. New activity paused completely with 0 fresh opportunities added.
- Mission Beach: 1 active opportunity remains alongside 0 new pre-sale permits. The neighborhood reports 0 total tax defaults and 0 new removals. Current listings include 5 tired landlords, 16 pre-list prep homes, 14 stalled projects, and 256 downsizers. Zero new opportunities were added during the reporting period.
- Pacific Beach: 3 active opportunities stand with 0 new pre-sale permits issued. The district holds 24 total tax defaults and 0 new removals. Available inventory tracks 12 tired landlords, 109 builder bait properties, 120 pre-list prep homes, 73 stalled projects, and 1165 downsizers. Activity paused entirely as 0 new opportunities entered the pipeline.
- Newsletter paragraph: Homeowners in La Jolla, Mission Beach, and Pacific Beach saw steady market conditions between November 12 and 19. Several areas reported new building permits, while listing volumes shifted across various property types. Some sellers are preparing their homes for sale, while others are exploring smaller living spaces. These shifts reflect ongoing adjustments in local inventory levels. Residents can review current neighborhood data to understand how their specific area is performing this week.

**qwen/qwen3.6-27b (reference)** (valid)

- Title: Territory Briefing: November 12 to 19, 2026
- Intro: The territory currently holds 7 strong leads with 0 new strong leads added this week. Pre-sale permits issued in La Jolla reached 4, while overall category counts declined across the board.
- La Jolla: Strong leads now total 3, with 0 new strong leads added. Builder bait counts fell to 364, a change of -2764. Stalled project counts dropped to 168, a change of -1444. Tax default total remains at 15.
- Mission Beach: Strong leads now total 1, with 0 new strong leads added. Tired landlord counts decreased to 5, a change of -25. Stalled project counts fell to 14, a change of -161. Tax default total is 0.
- Pacific Beach: Strong leads now total 3, with 0 new strong leads added. Builder bait counts dropped to 109, a change of -1855. Stalled project counts fell to 73, a change of -546. Tax default total stands at 24.
- Newsletter paragraph: Homeowners in La Jolla, Mission Beach, and Pacific Beach can expect steady market activity this week. Recent data shows noticeable shifts in property categories across all three areas, with several neighborhoods seeing reduced counts in renovation and lifestyle change segments. 4 new pre-sale permits were issued in La Jolla, reflecting ongoing local development interest. We continue to monitor these neighborhood trends closely to keep you informed about broader market conditions and community updates.

## Choice

**lead_brief and weekly_brief -> `deepseek/deepseek-v4.1-flash`** ($0.051 / $0.567 per M): cheapest model at or above 90% on both, and its writing is the most specific and least repetitive; the Qwen drafts are vaguer ("development-focused buyers", "listing volumes shifted across various property types") and cost 2x to 15x more.

Evals are noisy at 10 cases (one miss is 90%): lead_brief misses: qwen3.6-35b on `lead-5` (cited none of the required records), qwen3.6-27b on `lead-6` (the word 'financ' in the output); DeepSeek missed none. In production, 4 of the first 25 DeepSeek lead briefs came back empty and were rejected and not shown.

