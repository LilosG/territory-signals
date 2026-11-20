-- Phase 5G: weekly history behind the Today stat tiles, so a week-over-week % is never shown against the initial data load.
-- weeks_ago 0 = the last 7 days (this week), 1 = the 7 days before (the comparison week), ... up to 12.
-- first_day = the day this metric first had data: the first successful pull of the sources that feed it, or the first
-- draft / outcome / score row. The dashboard hides the % and says "First full week" when that day falls in the comparison
-- week, or the comparison week is more than 5x the median of the weeks after it (see dashboard/src/lib/present.ts).
create or replace function public.today_stat_history(p_hood text default null)
returns table (metric text, weeks_ago int, n bigint, first_day date)
language sql stable security invoker as $$
  with weeks as (select w from generate_series(0, 12) w),
  sig as (
    select ((current_date - g.signal_date) / 7) as w, count(*) as n
      from signals g left join parcels p on p_hood is not null and p.apn = g.apn
     where g.superseded_by is null and g.signal_date > current_date - 91 and g.signal_date <= current_date
       and g.signal_type in ('permit_approved', 'stro_license_removed') and g.signal_group <> 'other'
       and (p_hood is null or p.neighborhood = p_hood)
     group by 1),
  dr as (
    select ((current_date - o.created_at::date) / 7) as w, count(*) as n
      from outreach o join parcels p on p.apn = o.apn
     where o.created_at::date > current_date - 91 and (p_hood is null or p.neighborhood = p_hood)
     group by 1),
  oc as (
    select ((current_date - e.occurred_at::date) / 7) as w, count(*) as n
      from stage_events e join parcels p on p.apn = e.apn
     where e.source = 'dashboard' and e.occurred_at::date > current_date - 91 and (p_hood is null or p.neighborhood = p_hood)
     group by 1),
  al as (
    select ((current_date - sp.latest_event_date) / 7) as w, count(*) as n
      from scored_parcels sp
     where sp.latest_event_date > current_date - 91 and sp.latest_event_date <= current_date and sp.score >= 30
       and (p_hood is null or sp.neighborhood = p_hood)
     group by 1)
  select 'signals', w.w, coalesce((select n from sig where sig.w = w.w), 0),
         (select min(r.started_at)::date from source_runs r where r.status = 'success' and r.source_key in ('dev_permits', 'stro_licenses'))
    from weeks w
  union all
  select 'drafts', w.w, coalesce((select n from dr where dr.w = w.w), 0), (select min(o.created_at)::date from outreach o)
    from weeks w
  union all
  select 'outcomes', w.w, coalesce((select n from oc where oc.w = w.w), 0),
         (select min(e.occurred_at)::date from stage_events e where e.source = 'dashboard')
    from weeks w
  union all
  select 'active_leads', w.w, coalesce((select n from al where al.w = w.w), 0), (select min(s.scored_at)::date from scores s)
    from weeks w
$$;

grant execute on function public.today_stat_history(text) to authenticated;
revoke execute on function public.today_stat_history(text) from anon, public;
