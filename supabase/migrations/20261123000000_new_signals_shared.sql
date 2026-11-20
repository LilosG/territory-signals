-- Phase 5H: ONE definition of "new signal" for the Today tile, its history and the "New signals" panel.
-- A new signal event is a live (not superseded) selling-relevant signal (approved permit outside "other", removed STR license)
-- dated within the last 7 days, today included; same-day signals of one kind on one parcel count once (that is how the panel
-- shows them). The tile and the panel both read this view, so their counts always match.
create or replace view public.new_signal_events with (security_invoker = true) as
  select g.apn, p.neighborhood, g.signal_type, g.signal_group, g.signal_date, count(*) as n,
         bool_or(g.is_sample) as is_sample, bool_or(g.is_estimate) as is_estimate,
         min(g.source_key) as source_key, min(g.source_record_id) as source_record_id,
         (array_agg(g.details order by g.id))[1] as details
    from signals g join parcels p on p.apn = g.apn
   where g.superseded_by is null and g.signal_date <= current_date
     and g.signal_type in ('permit_approved', 'stro_license_removed') and g.signal_group <> 'other'
   group by g.apn, p.neighborhood, g.signal_type, g.signal_group, g.signal_date;
grant select on public.new_signal_events to authenticated;
revoke all on public.new_signal_events from anon;

-- Panel: events of the last p_days days (default 7, today included), newest first.
create or replace function public.recent_signals(p_hood text default null, p_days int default 7, p_limit int default 5)
returns table (
  apn text, situs_address text, neighborhood text, signal_type text, signal_group text, signal_date date,
  n bigint, is_sample boolean, is_estimate boolean, source_key text, source_record_id text, details jsonb, total bigint
)
language sql stable security invoker as $$
  with page as (
    select x.*, count(*) over () as total
      from public.new_signal_events x
     where x.signal_date > current_date - p_days and (p_hood is null or x.neighborhood = p_hood)
     order by x.signal_date desc, x.apn
     limit p_limit
  )
  select pg.apn, p.situs_address, p.neighborhood, pg.signal_type, pg.signal_group, pg.signal_date, pg.n, pg.is_sample,
         pg.is_estimate, pg.source_key, pg.source_record_id, pg.details, pg.total
    from page pg join parcels p on p.apn = pg.apn
   order by pg.signal_date desc, pg.apn
$$;

-- Tile: the same events counted per day.
create or replace function public.today_stats(p_hood text default null)
returns table (metric text, day date, n bigint)
language sql stable security invoker as $$
  with days as (select d::date as day from generate_series(current_date - 13, current_date, interval '1 day') d)
  select 'signals', d.day, (
           select count(*) from public.new_signal_events e
            where e.signal_date = d.day and (p_hood is null or e.neighborhood = p_hood))
    from days d
  union all
  select 'drafts', d.day, (
           select count(*) from outreach o join parcels p on p.apn = o.apn
            where o.created_at >= d.day and o.created_at < d.day + 1 and (p_hood is null or p.neighborhood = p_hood))
    from days d
  union all
  select 'outcomes', d.day, (
           select count(*) from stage_events e join parcels p on p.apn = e.apn
            where e.source = 'dashboard' and e.occurred_at >= d.day and e.occurred_at < d.day + 1
              and (p_hood is null or p.neighborhood = p_hood))
    from days d
  union all
  select 'active_leads', d.day, (
           select count(*) from scored_parcels sp
            where sp.latest_event_date = d.day and sp.score >= 30 and (p_hood is null or sp.neighborhood = p_hood))
    from days d
$$;

-- Weekly history of the tile: the same events, bucketed into 7-day weeks.
create or replace function public.today_stat_history(p_hood text default null)
returns table (metric text, weeks_ago int, n bigint, first_day date)
language sql stable security invoker as $$
  with weeks as (select w from generate_series(0, 12) w),
  sig as (
    select ((current_date - e.signal_date) / 7) as w, count(*) as n
      from public.new_signal_events e
     where e.signal_date > current_date - 91 and (p_hood is null or e.neighborhood = p_hood)
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

-- Scoring model of this week and of the comparison week. The Active leads tile shows "Scoring updated" instead of a
-- percentage when `updated` is true: the model that scored this week differs from the model of the comparison week (the
-- newest model scored before this week began), or more than one model scored during this week (it changed mid-week).
create or replace function public.scoring_model_weeks()
returns table (current_model text, comparison_model text, updated boolean)
language sql stable security invoker as $$
  with cur as (select s.model_version from scores s order by s.scored_at desc, s.created_at desc limit 1),
       cmp as (select s.model_version from scores s where s.scored_at < (current_date - 6)::timestamptz
                order by s.scored_at desc, s.created_at desc limit 1),
       wk as (select count(distinct s.model_version) as n from scores s where s.scored_at >= (current_date - 6)::timestamptz)
  select (select model_version from cur), (select model_version from cmp),
         coalesce((select c.model_version <> m.model_version from cur c, cmp m), false) or (select n from wk) > 1
$$;

grant execute on function public.recent_signals(text, int, int), public.today_stats(text), public.today_stat_history(text),
  public.scoring_model_weeks() to authenticated;
revoke execute on function public.recent_signals(text, int, int), public.today_stats(text), public.today_stat_history(text),
  public.scoring_model_weeks() from anon, public;
