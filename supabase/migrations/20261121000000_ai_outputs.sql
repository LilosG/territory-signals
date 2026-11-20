-- Phase 5F: AI layer storage. Every AI output is stored, append-only, with the records it cites.
-- AI never writes to scores, signals or eligibility; this table is read-only context for people.
set search_path = public, extensions;

create table ai_outputs (
  id                 uuid primary key default gen_random_uuid(),
  client_id          text not null,
  task               text not null,                       -- permit_intent | lead_brief | weekly_brief
  subject_type       text not null check (subject_type in ('parcel', 'permit', 'territory')),
  subject_id         text not null,                       -- apn | permit approval id | week start (YYYY-MM-DD)
  input_hash         text not null,                       -- sha256 of the facts the model saw
  prompt_version     text not null,                       -- from config/prompts/<task>/<version>.md
  provider           text not null,
  model              text not null,
  output             jsonb,                               -- null when status = invalid
  cited_record_ids   text[] not null default '{}',
  uses_sample        boolean not null default false,
  status             text not null check (status in ('valid', 'invalid', 'rejected')),
  rejection_reason   text,
  input_tokens       integer not null default 0,
  output_tokens      integer not null default 0,
  cost_usd           numeric(12, 6),                      -- null = unknown (never guessed)
  created_at         timestamptz not null default now()
);
create index ai_outputs_subject_idx on ai_outputs (task, subject_type, subject_id, created_at desc);
create index ai_outputs_cache_idx   on ai_outputs (client_id, task, subject_id, input_hash, prompt_version) where status = 'valid';
create index ai_outputs_month_idx   on ai_outputs (client_id, created_at);

create trigger ai_outputs_append_only before update or delete on ai_outputs
  for each row execute function public.reject_modification();

alter table ai_outputs enable row level security;
create policy ai_outputs_select_authenticated on ai_outputs for select to authenticated
  using ((select public.is_team_member()));

-- Latest valid row per (task, subject). Readers use this view only.
create view latest_ai_outputs with (security_invoker = true) as
  select distinct on (client_id, task, subject_type, subject_id) *
    from ai_outputs
   where status = 'valid'
   order by client_id, task, subject_type, subject_id, created_at desc, id;
grant select on latest_ai_outputs to authenticated;

-- One row per task per pipeline run, for the Pipeline page. Also carries warnings (budget stops, unknown prices).
create table ai_task_runs (
  id             uuid primary key default gen_random_uuid(),
  client_id      text not null,
  task           text not null,
  started_at     timestamptz not null default now(),
  finished_at    timestamptz,
  status         text not null check (status in ('success', 'skipped', 'budget_stopped', 'failed')),
  skip_reason    text,
  calls          integer not null default 0,
  cached         integer not null default 0,
  valid          integer not null default 0,
  invalid        integer not null default 0,
  rejected       integer not null default 0,
  input_tokens   integer not null default 0,
  output_tokens  integer not null default 0,
  cost_usd       numeric(12, 6) not null default 0,
  cost_unknown   boolean not null default false,
  warnings       text[] not null default '{}',
  model          text,
  created_at     timestamptz not null default now()
);
create index ai_task_runs_idx on ai_task_runs (client_id, task, started_at desc);
create trigger ai_task_runs_append_only before update or delete on ai_task_runs
  for each row execute function public.reject_modification();
alter table ai_task_runs enable row level security;
create policy ai_task_runs_select_authenticated on ai_task_runs for select to authenticated
  using ((select public.is_team_member()));

-- Spend this calendar month (UTC) per task, for the budget guard and the Pipeline page.
create view ai_month_spend with (security_invoker = true) as
  select client_id, task, coalesce(sum(cost_usd), 0)::numeric(12, 4) as cost_usd, count(*) as outputs
    from ai_outputs
   where created_at >= date_trunc('month', now())
   group by client_id, task;
grant select on ai_month_spend to authenticated;
