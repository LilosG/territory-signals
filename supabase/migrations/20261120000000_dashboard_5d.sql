-- Phase 5D: reads for the new dashboard pages (navigation counts, leads list, outreach queue, recipes, off-market,
-- global search, today stats, territory-aware funnels, coverage over time, friendly source status).
-- Nothing here changes scoring. Every view is security_invoker (RLS applies to the signed-in user) and returns rows
-- to team members only; every function is security invoker and reads through those gated views.
set search_path = public, extensions;

-- ---------------------------------------------------------------------------------------------
-- 1. Indexes for everything the new pages filter or sort on
-- ---------------------------------------------------------------------------------------------
create index if not exists signals_event_date_idx on signals (signal_date) where superseded_by is null;
create index if not exists signals_detected_idx on signals (detected_at);
create index if not exists outreach_apn_idx on outreach (apn);
create index if not exists outreach_channel_status_idx on outreach (channel, status);
create index if not exists stage_events_occurred_idx on stage_events (occurred_at);
create index if not exists source_runs_key_started_idx on source_runs (source_key, started_at desc);
create index if not exists owners_apn_asof_idx on owners (apn, as_of desc, created_at desc);
create index if not exists share_links_active_idx on share_links (created_at desc) where revoked_at is null;

-- ---------------------------------------------------------------------------------------------
-- 2. scored_parcels: one row per scored, unsuppressed parcel (latest score + the parcel facts the lists filter
--    on). Pre-computed because latest_scores is a per-parcel lookup over ~130k score rows; refreshed with the
--    other dashboard aggregates after every pipeline load. latest_event_date is the most recent selling-relevant
--    event on the parcel (an approved permit that is not in the "other" group, or a removed STR license); the
--    dashboard calls a parcel "new this week" when that date is within 7 days.
-- ---------------------------------------------------------------------------------------------
create materialized view private.scored_parcels as
  select s.apn, p.neighborhood, p.situs_address, p.lot_sqft, p.zoning, p.year_built, p.land_use,
         s.score, s.primary_recipe, coalesce(s.recipe_matches, '{}'::text[]) as recipe_matches,
         s.uses_sample_data, s.scored_at, ev.latest_event_date
    from latest_scores s
    join parcels p on p.apn = s.apn
    left join lateral (
      select max(g.signal_date) as latest_event_date
        from signals g
       where g.apn = s.apn and g.superseded_by is null
         and g.signal_type in ('permit_approved', 'stro_license_removed') and g.signal_group <> 'other'
    ) ev on true
   where not exists (select 1 from suppressions x
                      where x.apn = s.apn and (x.until_date is null or x.until_date >= current_date));
create unique index scored_parcels_apn_idx on private.scored_parcels (apn);
create index scored_parcels_hood_score_idx on private.scored_parcels (neighborhood, score desc);
create index scored_parcels_score_idx on private.scored_parcels (score desc);
create index scored_parcels_recipes_idx on private.scored_parcels using gin (recipe_matches);
create index scored_parcels_event_idx on private.scored_parcels (latest_event_date desc nulls last);
grant select on private.scored_parcels to authenticated;

create view scored_parcels with (security_invoker = true) as
  select * from private.scored_parcels where (select is_team_member());
grant select on scored_parcels to authenticated;

create or replace function private.refresh_dashboard_aggregates() returns void
language plpgsql set search_path = public, private as $$
begin
  refresh materialized view private.trend_turnover_monthly;
  refresh materialized view private.trend_signals_monthly;
  refresh materialized view private.trend_upzoning_by_hood;
  refresh materialized view private.trend_recipes_by_hood;
  refresh materialized view private.scored_parcels;
end $$;
revoke all on function private.refresh_dashboard_aggregates() from public, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- 3. Outreach queue: every draft with its address, score and assigned agent. Filter by status/channel/hood.
-- ---------------------------------------------------------------------------------------------
create view outreach_queue with (security_invoker = true) as
  select o.id, o.apn, o.channel, o.status, o.content, o.recipe, o.assigned_to, tm.name as assigned_name,
         o.blocked_reason, o.uses_sample_data, o.created_at, o.edited_by, o.edited_at, o.approved_by,
         o.sent_at, o.due_date, p.situs_address, p.neighborhood, s.score
    from outreach o
    join parcels p on p.apn = o.apn
    left join team_members tm on lower(tm.email) = lower(o.assigned_to)
    left join lateral (
      select x.score from scores x where x.apn = o.apn order by x.scored_at desc, x.created_at desc limit 1
    ) s on true;
grant select on outreach_queue to authenticated;

-- ---------------------------------------------------------------------------------------------
-- 4. Navigation counts (one cheap call per page) for a territory (null = all)
-- ---------------------------------------------------------------------------------------------
create or replace function public.nav_counts(p_hood text default null) returns json
language sql stable security invoker as $$
  with ob as (
    select o.channel, o.status
      from outreach o join parcels p on p.apn = o.apn
     where p_hood is null or p.neighborhood = p_hood
  )
  select json_build_object(
    'leads',   (select count(*) from scored_parcels where score >= 30 and (p_hood is null or neighborhood = p_hood)),
    'drafts',  (select count(*) from ob where channel <> 'call_task' and status = 'draft'),
    'awaiting_approval', (select count(*) from ob where channel <> 'call_task' and status = 'awaiting_approval'),
    'approved', (select count(*) from ob where channel <> 'call_task' and status = 'approved'),
    'call_tasks', (select count(*) from ob where channel = 'call_task' and status in ('draft', 'awaiting_approval', 'approved')),
    'off_market', (select count(*) from scored_parcels
                    where recipe_matches && array['builder_bait', 'tired_landlord'] and (p_hood is null or neighborhood = p_hood))
  )
$$;

-- ---------------------------------------------------------------------------------------------
-- 5. Leads list: filters, saved views (p_new), sort, paging. The default sort is score, highest first.
-- ---------------------------------------------------------------------------------------------
create or replace function public.leads_list(
  p_recipe text default null, p_group text default null, p_hood text default null,
  p_min int default null, p_max int default null, p_search text default null,
  p_status text default null, p_new boolean default false, p_sort text default 'score',
  p_limit int default 25, p_offset int default 0
) returns table (
  apn text, score int, reason_text text, recipe_matches text[], primary_recipe text, model_version text,
  scored_at timestamptz, uses_sample_data boolean, situs_address text, neighborhood text,
  lot_sqft numeric, zoning text, latest_event_date date,
  owner_name text, owner_is_sample boolean, owner_as_of date, last_sale_date date, est_equity numeric,
  est_value numeric, absentee boolean, out_of_state boolean,
  top_components jsonb, outreach_status text, total bigint
)
language sql stable security invoker as $$
  with base as (
    select sp.apn, sp.score, sp.primary_recipe, sp.recipe_matches, sp.uses_sample_data, sp.situs_address,
           sp.neighborhood, sp.lot_sqft::numeric as lot_sqft, sp.zoning, sp.latest_event_date, ob.status as outreach_status
      from scored_parcels sp
      left join lateral (
        select (array_agg(o.status order by case o.status when 'sent' then 4 when 'awaiting_approval' then 3
                                                          when 'approved' then 2 else 1 end desc))[1] as status
          from outreach o where o.apn = sp.apn and o.channel <> 'call_task'
           and o.status in ('draft', 'awaiting_approval', 'approved', 'sent')) ob on true
     where (p_recipe is null or p_recipe = any (sp.recipe_matches))
       and (p_hood is null or sp.neighborhood = p_hood)
       and (p_min is null or sp.score >= p_min)
       and (p_max is null or sp.score <= p_max)
       and (p_search is null
            or sp.situs_address ilike '%' || replace(replace(p_search, '%', ''), '_', '') || '%'
            or sp.apn like regexp_replace(p_search, '[^0-9]', '', 'g') || '%')
       and (not p_new or sp.latest_event_date >= current_date - 7)
       and (p_group is null or exists (
             select 1 from signals g where g.apn = sp.apn and g.signal_group = p_group and g.superseded_by is null))
       and (p_status is null
            or (p_status = 'new' and ob.status is null)
            or (p_status = 'draft_ready' and ob.status = 'draft')
            or (p_status in ('awaiting_approval', 'approved', 'sent') and ob.status = p_status))
  ), page as (
    select b.*, count(*) over () as total from base b
     order by
       case when p_sort = 'recent'  then b.latest_event_date end desc nulls last,
       case when p_sort = 'lot'     then b.lot_sqft end desc nulls last,
       case when p_sort = 'address' then b.situs_address end asc,
       b.score desc, b.apn
     limit p_limit offset p_offset
  )
  select g.apn, g.score, sc.reason_text, g.recipe_matches, g.primary_recipe, sc.model_version, sc.scored_at,
         g.uses_sample_data, g.situs_address, g.neighborhood, g.lot_sqft, g.zoning, g.latest_event_date,
         o.owner_name, o.is_sample, o.as_of, o.last_sale_date, o.est_equity, o.est_value, o.absentee, o.out_of_state,
         tc.items, g.outreach_status, g.total
    from page g
    left join lateral (
      select x.reason_text, x.model_version, x.scored_at, x.components from scores x
       where x.apn = g.apn order by x.scored_at desc, x.created_at desc limit 1) sc on true
    left join lateral (
      select w.owner_name, w.is_sample, w.as_of, w.last_sale_date, w.est_equity, w.est_value, w.absentee, w.out_of_state
        from owners w where w.apn = g.apn order by w.as_of desc, w.created_at desc limit 1) o on true
    left join lateral (
      -- the three largest signal components (keys, facts and points), for the card headline
      select jsonb_agg(jsonb_build_object('key', c ->> 'key', 'facts', c -> 'facts', 'points', (c ->> 'contribution')::numeric,
                                          'signal_date', c ->> 'signal_date', 'is_sample', (c ->> 'is_sample')::boolean,
                                          'is_estimate', (c ->> 'is_estimate')::boolean)
                       order by (c ->> 'contribution')::numeric desc) as items
        from (select c from jsonb_array_elements(coalesce(sc.components, '[]'::jsonb)) c
               where c ->> 'kind' = 'signal' order by (c ->> 'contribution')::numeric desc limit 3) t) tc on true
   order by
     case when p_sort = 'recent'  then g.latest_event_date end desc nulls last,
     case when p_sort = 'lot'     then g.lot_sqft end desc nulls last,
     case when p_sort = 'address' then g.situs_address end asc,
     g.score desc, g.apn
$$;

-- ---------------------------------------------------------------------------------------------
-- 6. Recipes: counts per recipe and the top leads in each
-- ---------------------------------------------------------------------------------------------
create or replace function public.recipe_summary(p_hood text default null)
returns table (recipe text, parcels bigint, new_this_week bigint, strong bigint)
language sql stable security invoker as $$
  select r.recipe, count(*), count(*) filter (where sp.latest_event_date >= current_date - 7),
         count(*) filter (where sp.score >= 60)
    from scored_parcels sp
   cross join lateral unnest(sp.recipe_matches) as r(recipe)
   where p_hood is null or sp.neighborhood = p_hood
   group by r.recipe
$$;

create or replace function public.recipe_top_leads(p_hood text default null, p_n int default 5)
returns table (recipe text, rank int, apn text, score int, situs_address text, neighborhood text, uses_sample_data boolean)
language sql stable security invoker as $$
  select t.recipe, t.rn::int, t.apn, t.score, t.situs_address, t.neighborhood, t.uses_sample_data
    from (
      select r.recipe, row_number() over (partition by r.recipe order by sp.score desc, sp.apn) as rn,
             sp.apn, sp.score, sp.situs_address, sp.neighborhood, sp.uses_sample_data
        from scored_parcels sp
       cross join lateral unnest(sp.recipe_matches) as r(recipe)
       where p_hood is null or sp.neighborhood = p_hood
    ) t
   where t.rn <= p_n
   order by t.recipe, t.rn
$$;

-- ---------------------------------------------------------------------------------------------
-- 7. Off-market inventory: property facts only (no owner, equity, mortgage, sales or distress fields).
--    p_kind: null (both), 'builder_bait' or 'tired_landlord'.
-- ---------------------------------------------------------------------------------------------
create or replace function public.off_market_inventory(
  p_hood text default null, p_kind text default null, p_sort text default 'lot', p_limit int default 25, p_offset int default 0
) returns table (
  apn text, situs_address text, neighborhood text, lot_sqft numeric, zoning text, year_built int, land_use text,
  kinds text[], upzoning_estimates jsonb, has_share_link boolean, total bigint
)
language sql stable security invoker as $$
  with latest as (
    select signal_type, max(signal_date) as d from signals
     where superseded_by is null and signal_type in ('sb9_lot_split_estimate', 'sb79_transit_estimate')
     group by signal_type
  ), base as (
    select sp.apn, sp.situs_address, sp.neighborhood, sp.lot_sqft::numeric as lot_sqft, sp.zoning, sp.year_built,
           sp.land_use, sp.score,
           array(select k from unnest(array['builder_bait', 'tired_landlord']) k where k = any (sp.recipe_matches)) as kinds
      from scored_parcels sp
     where sp.recipe_matches && case when p_kind is null then array['builder_bait', 'tired_landlord'] else array[p_kind] end
       and (p_hood is null or sp.neighborhood = p_hood)
  ), page as (
    select b.*, count(*) over () as total from base b
     order by case when p_sort = 'address' then b.situs_address end asc,
              case when p_sort = 'score' then b.score end desc nulls last,
              b.lot_sqft desc nulls last, b.apn
     limit p_limit offset p_offset
  )
  select g.apn, g.situs_address, g.neighborhood, g.lot_sqft, g.zoning, g.year_built, g.land_use, g.kinds,
         coalesce((select jsonb_agg(distinct s.signal_type) from signals s join latest l on l.signal_type = s.signal_type and l.d = s.signal_date
                    where s.apn = g.apn and s.superseded_by is null and s.is_estimate), '[]'::jsonb),
         exists (select 1 from share_links l where l.apn = g.apn and l.revoked_at is null),
         g.total
    from page g
   order by case when p_sort = 'address' then g.situs_address end asc,
            case when p_sort = 'score' then g.score end desc nulls last,
            g.lot_sqft desc nulls last, g.apn
$$;

-- Active share links with the property address (for the team only; the public page never shows it).
create view share_links_active with (security_invoker = true) as
  select l.token, l.apn, p.situs_address, p.neighborhood, l.created_by, l.created_at
    from share_links l join parcels p on p.apn = l.apn
   where l.revoked_at is null;
grant select on share_links_active to authenticated;

-- ---------------------------------------------------------------------------------------------
-- 8. Global search (address or APN). Digits-only input matches the APN, with or without dashes.
-- ---------------------------------------------------------------------------------------------
create or replace function public.search_leads(p_q text, p_hood text default null, p_limit int default 8)
returns table (apn text, situs_address text, neighborhood text, score int)
language sql stable security invoker as $$
  select sp.apn, sp.situs_address, sp.neighborhood, sp.score
    from scored_parcels sp
   where length(btrim(coalesce(p_q, ''))) >= 2
     and (p_hood is null or sp.neighborhood = p_hood)
     and (sp.situs_address ilike '%' || replace(replace(btrim(p_q), '%', ''), '_', '') || '%'
          or (regexp_replace(p_q, '[^0-9]', '', 'g') <> '' and sp.apn like regexp_replace(p_q, '[^0-9]', '', 'g') || '%'))
   order by (sp.situs_address ilike replace(replace(btrim(p_q), '%', ''), '_', '') || '%') desc, sp.score desc, sp.apn
   limit least(p_limit, 20)
$$;

-- ---------------------------------------------------------------------------------------------
-- 9. Today: 14 days of daily counts (signals, drafts, outcomes, parcels with fresh activity) and recent signals
-- ---------------------------------------------------------------------------------------------
create or replace function public.today_stats(p_hood text default null)
returns table (metric text, day date, n bigint)
language sql stable security invoker as $$
  with days as (select d::date as day from generate_series(current_date - 13, current_date, interval '1 day') d)
  select 'signals', d.day, (
           select count(*) from signals g
             left join parcels p on p_hood is not null and p.apn = g.apn
            where g.superseded_by is null and g.signal_date = d.day
              and g.signal_type in ('permit_approved', 'stro_license_removed') and g.signal_group <> 'other'
              and (p_hood is null or p.neighborhood = p_hood))
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

create or replace function public.recent_signals(p_hood text default null, p_days int default 14, p_limit int default 5)
returns table (
  apn text, situs_address text, neighborhood text, signal_type text, signal_group text, signal_date date,
  n bigint, is_sample boolean, is_estimate boolean, source_key text, source_record_id text, details jsonb, total bigint
)
language sql stable security invoker as $$
  with grouped as (
    select g.apn, g.signal_type, g.signal_group, g.signal_date, count(*) as n, bool_or(g.is_sample) as is_sample,
           bool_or(g.is_estimate) as is_estimate, min(g.source_key) as source_key, min(g.source_record_id) as source_record_id,
           (array_agg(g.details order by g.id))[1] as details
      from signals g
     where g.superseded_by is null and g.signal_date >= current_date - p_days
       and g.signal_type in ('permit_approved', 'stro_license_removed') and g.signal_group <> 'other'
     group by g.apn, g.signal_type, g.signal_group, g.signal_date
  ), page as (
    select x.*, count(*) over () as total
      from grouped x join parcels p on p.apn = x.apn
     where p_hood is null or p.neighborhood = p_hood
     order by x.signal_date desc, x.apn
     limit p_limit
  )
  select pg.apn, p.situs_address, p.neighborhood, pg.signal_type, pg.signal_group, pg.signal_date, pg.n, pg.is_sample,
         pg.is_estimate, pg.source_key, pg.source_record_id, pg.details, pg.total
    from page pg join parcels p on p.apn = pg.apn
   order by pg.signal_date desc, pg.apn
$$;

-- ---------------------------------------------------------------------------------------------
-- 10. Funnels for one territory (the 5B views cover the whole territory only)
-- ---------------------------------------------------------------------------------------------
create or replace function public.funnel_by(p_dim text, p_hood text default null)
returns table (label text, signal bigint, contacted bigint, conversation bigint, appointment bigint, listing bigint,
               not_interested bigint, bad_data bigint, avg_score numeric)
language sql stable security invoker as $$
  select case p_dim when 'recipe' then s.primary_recipe when 'agent' then coalesce(e.team_member_email, 'unassigned') else 'all' end,
         count(distinct e.apn) filter (where e.stage = 'signal'),
         count(distinct e.apn) filter (where e.stage = 'contacted'),
         count(distinct e.apn) filter (where e.stage = 'conversation'),
         count(distinct e.apn) filter (where e.stage = 'appointment'),
         count(distinct e.apn) filter (where e.stage = 'listing'),
         count(distinct e.apn) filter (where e.stage = 'not_interested'),
         count(distinct e.apn) filter (where e.stage = 'bad_data'),
         round(avg(s.score), 1)
    from stage_events e
    join parcels p on p.apn = e.apn
    left join lateral (
      select x.primary_recipe, x.score from scores x where x.apn = e.apn order by x.scored_at desc, x.created_at desc limit 1) s on true
   where (p_hood is null or p.neighborhood = p_hood)
     and (p_dim <> 'recipe' or s.primary_recipe is not null)
   group by 1
$$;

-- ---------------------------------------------------------------------------------------------
-- 11. Coverage over time: weekly signals detected, sources reporting, parcels monitored
-- ---------------------------------------------------------------------------------------------
create or replace function public.coverage_weekly(p_weeks int default 12, p_hood text default null)
returns table (week date, signals bigint, sources_live bigint, parcels_monitored bigint)
language sql stable security invoker as $$
  with weeks as (
    select (date_trunc('week', current_date) - (i * 7) * interval '1 day')::date as week
      from generate_series(0, least(greatest(p_weeks, 1), 52) - 1) i
  ), first_week as (select min(week) as w from weeks),
  sig as (
    select date_trunc('week', g.detected_at)::date as week, count(*) as n
      from signals g
     where g.detected_at >= (select w from first_week) and g.signal_group <> 'other'
       and (p_hood is null or g.apn in (select p.apn from parcels p where p.neighborhood = p_hood))
     group by 1
  ), src as (
    select date_trunc('week', r.started_at)::date as week, count(distinct r.source_key) as n
      from source_runs r
     where r.status = 'success' and r.started_at >= (select w from first_week)
       and r.source_key not in ('permit_rederive', 'parcels', 'zoning', 'planning_areas')
     group by 1
  ), par as materialized (
    select date_trunc('week', p.created_at)::date as week, count(*) as n
      from parcels p where (p_hood is null or p.neighborhood = p_hood) group by 1
  )
  select w.week, coalesce(sig.n, 0), coalesce(src.n, 0),
         (select coalesce(sum(par.n), 0) from par where par.week <= w.week)::bigint
    from weeks w
    left join sig on sig.week = w.week
    left join src on src.week = w.week
   order by w.week
$$;

-- ---------------------------------------------------------------------------------------------
-- 12. Latest run of every source (the Data sources page decides what to show and how)
-- ---------------------------------------------------------------------------------------------
create view source_latest with (security_invoker = true) as
  select distinct on (source_key) source_key, status, started_at, finished_at, rows_fetched, rows_matched,
         rows_unmatched, error_message
    from source_runs order by source_key, started_at desc;
grant select on source_latest to authenticated;

-- ---------------------------------------------------------------------------------------------
-- 13. Grants
-- ---------------------------------------------------------------------------------------------
grant execute on function
  public.nav_counts(text),
  public.leads_list(text, text, text, int, int, text, text, boolean, text, int, int),
  public.recipe_summary(text), public.recipe_top_leads(text, int),
  public.off_market_inventory(text, text, text, int, int),
  public.search_leads(text, text, int),
  public.today_stats(text), public.recent_signals(text, int, int),
  public.funnel_by(text, text), public.coverage_weekly(int, text)
  to authenticated;
revoke execute on function
  public.nav_counts(text),
  public.leads_list(text, text, text, int, int, text, text, boolean, text, int, int),
  public.recipe_summary(text), public.recipe_top_leads(text, int),
  public.off_market_inventory(text, text, text, int, int),
  public.search_leads(text, text, int),
  public.today_stats(text), public.recent_signals(text, int, int),
  public.funnel_by(text, text), public.coverage_weekly(int, text)
  from anon, public;

analyze private.scored_parcels;
