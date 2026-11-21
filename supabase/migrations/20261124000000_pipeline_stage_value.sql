-- Phase 5I: estimated property value behind each pipeline stage, so /pipeline can show estimated GCI (2.5% of est_value).
-- Parcels are counted once per stage (distinct apn); the latest owners row supplies est_value. A parcel with no est_value adds
-- to `parcels` but not to `est_value`. `sample_parcels` counts parcels whose value comes from sample owner data.
set search_path = public, extensions;

create or replace function public.pipeline_stage_value(p_hood text default null)
returns table (stage text, parcels bigint, valued_parcels bigint, est_value numeric, sample_parcels bigint)
language sql stable security invoker as $$
  with reached as (
    select distinct e.apn, e.stage
      from stage_events e
      join parcels p on p.apn = e.apn
     where e.stage in ('signal', 'contacted', 'conversation', 'appointment', 'listing')
       and (p_hood is null or p.neighborhood = p_hood)
  )
  select r.stage, count(*), count(o.est_value), coalesce(sum(o.est_value), 0), count(*) filter (where o.is_sample)
    from reached r
    left join lateral (
      select w.est_value, w.is_sample from owners w where w.apn = r.apn order by w.as_of desc, w.created_at desc limit 1) o on true
   group by r.stage
$$;

grant execute on function public.pipeline_stage_value(text) to authenticated;
revoke execute on function public.pipeline_stage_value(text) from anon, public;
