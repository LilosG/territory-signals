-- Phase 3 checkpoint corrections.
set search_path = public, extensions;

-- A permit type mapped back to a group it once had must produce a live signal. The natural key
-- gains superseded_by (nulls not distinct): at most one LIVE row per key, while any number of
-- superseded rows (each stamped by a different derivation run) can sit beside it. Reruns of an
-- adapter still deduplicate against the live row.
alter table signals drop constraint signals_natural_key;
alter table signals
  add constraint signals_natural_key
  unique nulls not distinct (source_key, source_record_id, signal_type, signal_group, signal_date, superseded_by);

-- Most recent score per parcel. security_invoker: the view runs with the caller's rights, so the
-- RLS policies on scores (authenticated select) apply.
create view latest_scores with (security_invoker = true) as
  select distinct on (apn) *
  from scores
  order by apn, scored_at desc, created_at desc;
grant select on latest_scores to authenticated;
