-- Phase 5C: make the dashboard queries cheap enough for a small cloud instance and the Workers runtime.
--  1. signal-group filter index (leads_page / map_points with p_group probed signals once per parcel without one)
--  2. trend aggregates pre-computed in materialized views (they scanned all 75k signals on every /trends load)
--  3. map_geojson: the finished GeoJSON built in SQL, so the Worker streams it through instead of building
--     26k feature objects in JavaScript (CPU limit on Workers)

-- 1 ---------------------------------------------------------------------------------------------------------
create index if not exists signals_live_group_idx on signals (apn, signal_group) where superseded_by is null;

-- 2 ---------------------------------------------------------------------------------------------------------
-- The materialized views live in a schema that PostgREST does not expose; the public views keep their names,
-- columns and security (team members only) and read from them. Refresh after every data load:
--   select private.refresh_dashboard_aggregates();
create schema if not exists private;
grant usage on schema private to authenticated;

drop view trend_turnover_monthly, trend_signals_monthly, trend_upzoning_by_hood, trend_recipes_by_hood;

create materialized view private.trend_turnover_monthly as
  with transfers as (
    select distinct apn, signal_date from signals
     where signal_type = 'ownership_transfer' and superseded_by is null
  )
  select date_trunc('month', sh.sale_date)::date as month, p.neighborhood,
         count(*) as sales, count(*) filter (where sh.is_sample) as sample_rows
    from sales_history sh
    join parcels p on p.apn = sh.apn
    left join transfers t on t.apn = sh.apn and t.signal_date = sh.sale_date
   where sh.sale_date is not null and t.apn is null
   group by 1, 2;

create materialized view private.trend_signals_monthly as
  select date_trunc('month', g.signal_date)::date as month, p.neighborhood,
         g.signal_type, g.signal_group,
         count(*) as signals, count(*) filter (where g.is_sample) as sample_rows
    from signals g
    join parcels p on p.apn = g.apn
   where g.superseded_by is null and g.signal_date is not null
   group by 1, 2, 3, 4;

create materialized view private.trend_upzoning_by_hood as
  with latest as (
    select signal_type, max(signal_date) as d from signals
     where superseded_by is null and signal_type in ('sb9_lot_split_estimate', 'sb79_transit_estimate')
     group by signal_type
  ), snap as (
    select g.apn, g.signal_type, g.details, g.is_sample
      from signals g join latest l on l.signal_type = g.signal_type and l.d = g.signal_date
     where g.superseded_by is null
  )
  select p.neighborhood,
         count(distinct s.apn) filter (where s.signal_type = 'sb9_lot_split_estimate') as sb9,
         count(distinct s.apn) filter (where s.signal_type = 'sb79_transit_estimate'
                                         and s.details ->> 'distance_band' like '%quarter%') as sb79_quarter_mile,
         count(distinct s.apn) filter (where s.signal_type = 'sb79_transit_estimate') as sb79_half_mile,
         count(*) filter (where s.is_sample) as sample_rows
    from snap s join parcels p on p.apn = s.apn
   group by p.neighborhood;

create materialized view private.trend_recipes_by_hood as
  select p.neighborhood, r.recipe, count(*) as parcels,
         count(*) filter (where s.uses_sample_data) as sample_rows
    from latest_scores s
    join parcels p on p.apn = s.apn
    cross join lateral unnest(s.recipe_matches) as r(recipe)
   group by 1, 2;

grant select on all tables in schema private to authenticated;

create view trend_turnover_monthly with (security_invoker = true) as
  select * from private.trend_turnover_monthly where (select is_team_member());
create view trend_signals_monthly with (security_invoker = true) as
  select * from private.trend_signals_monthly where (select is_team_member());
create view trend_upzoning_by_hood with (security_invoker = true) as
  select * from private.trend_upzoning_by_hood where (select is_team_member());
create view trend_recipes_by_hood with (security_invoker = true) as
  select * from private.trend_recipes_by_hood where (select is_team_member());
grant select on trend_turnover_monthly, trend_signals_monthly, trend_upzoning_by_hood, trend_recipes_by_hood to authenticated;

create or replace function private.refresh_dashboard_aggregates() returns void
language plpgsql set search_path = public, private as $$
begin
  refresh materialized view private.trend_turnover_monthly;
  refresh materialized view private.trend_signals_monthly;
  refresh materialized view private.trend_upzoning_by_hood;
  refresh materialized view private.trend_recipes_by_hood;
end $$;
revoke all on function private.refresh_dashboard_aggregates() from public, anon, authenticated;

-- 3 ---------------------------------------------------------------------------------------------------------
create or replace function public.map_geojson(
  p_recipe text default null, p_group text default null, p_hood text default null,
  p_min int default null, p_max int default null
) returns json
language sql stable security invoker set search_path = public, extensions as $$
  select json_build_object(
           'type', 'FeatureCollection',
           'sample', exists (select 1 from latest_scores where uses_sample_data),
           'features', coalesce(json_agg(json_build_object(
              'type', 'Feature',
              'properties', json_build_object('apn', s.apn, 'score', s.score, 'primary_recipe', s.primary_recipe, 'neighborhood', p.neighborhood),
              'geometry', json_build_object('type', 'Point', 'coordinates',
                            json_build_array(round(st_x(p.centroid)::numeric, 6), round(st_y(p.centroid)::numeric, 6))))), '[]'::json))
    from latest_scores s
    join parcels p on p.apn = s.apn
   where p.centroid is not null
     and (p_recipe is null or p_recipe = any (s.recipe_matches))
     and (p_hood is null or p.neighborhood = p_hood)
     and (p_min is null or s.score >= p_min)
     and (p_max is null or s.score <= p_max)
     and (p_group is null or exists (
           select 1 from signals g where g.apn = s.apn and g.signal_group = p_group and g.superseded_by is null))
     and not exists (select 1 from suppressions x
                      where x.apn = s.apn and (x.until_date is null or x.until_date >= current_date))
$$;
grant execute on function public.map_geojson(text, text, text, int, int) to authenticated;
revoke execute on function public.map_geojson(text, text, text, int, int) from anon, public;
