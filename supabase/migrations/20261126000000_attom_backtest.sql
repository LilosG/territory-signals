-- Phase 6: ATTOM owner/recorder integration and historical backtest.
--
-- api_usage_log is the permanent, append-only ledger of every ATTOM API call attempt. The quota
-- governor (territory/owner_data/attom.py) reads it before each call and refuses to exceed the
-- day's --max-calls budget. It is written only by the pipeline service role.
--
-- backtest_runs stores one deterministic row per backtest execution. The dashboard reads the
-- newest row per client; a row is sample data when any sale or prior signal it used was sample.

create table public.api_usage_log (
  id uuid primary key default gen_random_uuid(),
  call_date date not null default current_date,
  source_key text not null,
  endpoint text,
  apn text,
  request_count int not null default 1 check (request_count > 0),
  status text not null default 'success',
  http_status int,
  note text,
  created_at timestamptz not null default now()
);

create index api_usage_log_source_date_idx on public.api_usage_log (source_key, call_date);
create index api_usage_log_created_idx on public.api_usage_log (created_at desc);

alter table public.api_usage_log enable row level security;
create policy api_usage_log_select_authenticated on public.api_usage_log
  for select to authenticated using (true);
grant select on public.api_usage_log to authenticated;
revoke all on public.api_usage_log from anon;

create table public.backtest_runs (
  id uuid primary key default gen_random_uuid(),
  client_id text not null,
  window_start date not null,
  window_end date not null,
  months int not null default 24,
  min_days int not null default 14,
  max_days int not null default 365,
  total_sales_evaluated int not null,
  flagged_before_sale_count int not null,
  capture_rate_pct numeric,
  median_days_early numeric,
  avg_days_early numeric,
  breakdown_by_signal_group jsonb not null default '{}'::jsonb,
  is_sample boolean not null default false,
  computed_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create index backtest_runs_client_computed_idx on public.backtest_runs (client_id, computed_at desc);

alter table public.backtest_runs enable row level security;
create policy backtest_runs_select_authenticated on public.backtest_runs
  for select to authenticated using (true);
grant select on public.backtest_runs to authenticated;
revoke all on public.backtest_runs from anon;

-- Newest run per client (the dashboard reads this; the table keeps the execution history).
create view public.latest_backtest_runs with (security_invoker = true) as
  select distinct on (client_id)
         id, client_id, window_start, window_end, months, min_days, max_days,
         total_sales_evaluated, flagged_before_sale_count, capture_rate_pct,
         median_days_early, avg_days_early, breakdown_by_signal_group, is_sample,
         computed_at, created_at
    from public.backtest_runs
   order by client_id, computed_at desc, created_at desc;

grant select on public.latest_backtest_runs to authenticated;
revoke all on public.latest_backtest_runs from anon;
