-- Phase 3: scoring and recipes.
set search_path = public, extensions;

-- 1. Superseded signals. A signal is never overwritten or deleted. When the permit
--    re-derivation step (territory.permit_rederive) replaces or retires a signal it
--    stamps the OLD row with the id of the derivation run (source_runs.id) that
--    superseded it. Replacement rows carry that same run_id. Live = superseded_by is null.
alter table signals add column superseded_by uuid references source_runs(id);
create index signals_live_idx on signals (apn, signal_type) where superseded_by is null;

-- The only change allowed on an existing signal: superseded_by going from null to a run id.
create or replace function public.signals_guard() returns trigger
language plpgsql as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'DELETE on signals is not allowed: table is append-only'
      using errcode = 'restrict_violation';
  end if;
  if old.superseded_by is null and new.superseded_by is not null
     and (to_jsonb(new) - 'superseded_by') = (to_jsonb(old) - 'superseded_by') then
    return new;
  end if;
  raise exception 'UPDATE on signals is not allowed except marking superseded_by: table is append-only'
    using errcode = 'restrict_violation';
end;
$$;

drop trigger signals_append_only on signals;
create trigger signals_append_only before update or delete on signals
  for each row execute function public.signals_guard();

-- A corrected permit signal (new group, same approval, same date) is a new row, so the
-- signal group becomes part of the natural key. Reruns still deduplicate.
alter table signals drop constraint signals_natural_key;
alter table signals
  add constraint signals_natural_key
  unique nulls not distinct (source_key, source_record_id, signal_type, signal_group, signal_date);

-- 2. Scores are an append-only history (one row per scored parcel per run).
alter table scores add column uses_sample_data boolean not null default false;
create index scores_apn_scored_idx on scores (apn, scored_at);

create trigger scores_append_only before update or delete on scores
  for each row execute function public.reject_modification();
