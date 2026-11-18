-- Phase 2: append-only enforcement and rerun safety.
set search_path = public, extensions;

-- raw_records, signals, owners and sales_history may be inserted into but never
-- changed or removed (CLAUDE.md data rules).
create or replace function public.reject_modification() returns trigger
language plpgsql as $$
begin
  raise exception '% on % is not allowed: table is append-only', tg_op, tg_table_name
    using errcode = 'restrict_violation';
end;
$$;

do $$
declare t text;
begin
  foreach t in array array['raw_records','signals','owners','sales_history'] loop
    execute format(
      'create trigger %I before update or delete on public.%I '
      'for each row execute function public.reject_modification()',
      t || '_append_only', t);
  end loop;
end $$;

-- Reruns never duplicate a signal. NULLS NOT DISTINCT so a signal without a
-- date is still deduplicated.
alter table signals
  add constraint signals_natural_key
  unique nulls not distinct (source_key, source_record_id, signal_type, signal_date);
