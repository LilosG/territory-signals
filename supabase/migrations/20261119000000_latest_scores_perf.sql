-- Phase 5C: latest_scores was "select distinct on (apn) ... from scores order by apn, scored_at desc, created_at desc",
-- which sorts all ~131k score rows on every call. On the small cloud instance leads_page took 12-14 s and hit the
-- authenticated role's 8 s statement timeout (HTTP 500 on /). The same result now comes from one index probe per
-- parcel (every scores.apn is a parcels.apn by foreign key), with identical columns and semantics.
create index if not exists scores_apn_latest_idx on scores (apn, scored_at desc, created_at desc);

create or replace view latest_scores with (security_invoker = true) as
select s.id, s.apn, s.score, s.components, s.reason_text, s.recipe_matches, s.model_version, s.scored_at,
       s.created_at, s.uses_sample_data, s.primary_recipe
  from parcels p
 cross join lateral (
   select x.* from scores x where x.apn = p.apn order by x.scored_at desc, x.created_at desc limit 1
 ) s;
