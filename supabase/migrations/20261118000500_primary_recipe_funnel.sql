-- Phase 5A corrections: each parcel counts once in funnel_by_recipe, under its primary recipe.
set search_path = public, extensions;

-- Primary recipe = the matched recipe whose components contribute the most points (computed by the scorer).
alter table scores add column primary_recipe text;

-- latest_scores is "select *", which is frozen when the view is created, so it is rebuilt to expose the new
-- column (the two funnel views depend on it and are rebuilt too; funnel_by_agent is unchanged).
drop view funnel_by_recipe;
drop view funnel_by_agent;
drop view latest_scores;
create view latest_scores with (security_invoker = true) as
  select distinct on (apn) *
  from scores
  order by apn, scored_at desc, created_at desc;
grant select on latest_scores to authenticated;

create view funnel_by_agent with (security_invoker = true) as
  select coalesce(e.team_member_email, 'unassigned') as team_member_email,
         count(distinct e.apn) filter (where e.stage = 'signal')         as signal,
         count(distinct e.apn) filter (where e.stage = 'contacted')      as contacted,
         count(distinct e.apn) filter (where e.stage = 'conversation')   as conversation,
         count(distinct e.apn) filter (where e.stage = 'appointment')    as appointment,
         count(distinct e.apn) filter (where e.stage = 'listing')        as listing,
         count(distinct e.apn) filter (where e.stage = 'not_interested') as not_interested,
         count(distinct e.apn) filter (where e.stage = 'bad_data')       as bad_data,
         round(avg(s.score), 1)                                          as avg_score
  from stage_events e
  join latest_scores s on s.apn = e.apn
  group by coalesce(e.team_member_email, 'unassigned');
grant select on funnel_by_agent to authenticated;

create view funnel_by_recipe with (security_invoker = true) as
  select s.primary_recipe as recipe,
         count(distinct e.apn) filter (where e.stage = 'signal')         as signal,
         count(distinct e.apn) filter (where e.stage = 'contacted')      as contacted,
         count(distinct e.apn) filter (where e.stage = 'conversation')   as conversation,
         count(distinct e.apn) filter (where e.stage = 'appointment')    as appointment,
         count(distinct e.apn) filter (where e.stage = 'listing')        as listing,
         count(distinct e.apn) filter (where e.stage = 'not_interested') as not_interested,
         count(distinct e.apn) filter (where e.stage = 'bad_data')       as bad_data
  from stage_events e
  join latest_scores s on s.apn = e.apn
  where s.primary_recipe is not null
  group by s.primary_recipe;
grant select on funnel_by_recipe to authenticated;
