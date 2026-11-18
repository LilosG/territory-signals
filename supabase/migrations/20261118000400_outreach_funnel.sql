-- Phase 5A: outreach draft columns, stage_events (funnel), funnel views.
set search_path = public, extensions;

-- 1. Outreach drafts carry what the generator decided, so a reviewer can see why and for whom.
alter table outreach
  add column recipe text,
  add column assigned_to text,
  add column due_date date,
  add column mailing_address text,
  add column salutation text,
  add column template_key text,
  add column model_version text,
  -- Not in the original column list: D11 and the office-address rule need somewhere to record
  -- why a draft cannot be approved, and sample-derived drafts must stay labeled.
  add column blocked_reason text,
  add column uses_sample_data boolean not null default false;

-- D11: a draft with a blocked_reason can never be approved or sent.
alter table outreach
  add constraint outreach_blocked_not_approved
  check (blocked_reason is null or status not in ('approved', 'sent'));

-- 2. stage_events: append-only history of where each parcel is in the funnel.
create table stage_events (
  id uuid primary key default gen_random_uuid(),
  apn text not null references parcels(apn),
  stage text not null check (stage in
    ('signal', 'contacted', 'conversation', 'appointment', 'listing', 'not_interested', 'bad_data')),
  team_member_email text,
  occurred_at timestamptz not null default now(),
  note text,
  source text not null check (source in ('dashboard', 'system')),
  created_at timestamptz not null default now()
);
create index stage_events_apn_idx on stage_events (apn, occurred_at);
create index stage_events_stage_idx on stage_events (stage);

create trigger stage_events_append_only before update or delete on stage_events
  for each row execute function public.reject_modification();

alter table stage_events enable row level security;
create policy stage_events_select_authenticated on stage_events for select to authenticated using (true);

-- 3. Funnel views. security_invoker: they run with the caller's rights, so RLS on stage_events and
-- scores applies. Counts are distinct parcels that have at least one event at that stage.
create view funnel_by_recipe with (security_invoker = true) as
  select r.recipe,
         count(distinct e.apn) filter (where e.stage = 'signal')         as signal,
         count(distinct e.apn) filter (where e.stage = 'contacted')      as contacted,
         count(distinct e.apn) filter (where e.stage = 'conversation')   as conversation,
         count(distinct e.apn) filter (where e.stage = 'appointment')    as appointment,
         count(distinct e.apn) filter (where e.stage = 'listing')        as listing,
         count(distinct e.apn) filter (where e.stage = 'not_interested') as not_interested,
         count(distinct e.apn) filter (where e.stage = 'bad_data')       as bad_data
  from stage_events e
  join latest_scores s on s.apn = e.apn
  cross join lateral unnest(s.recipe_matches) as r(recipe)
  group by r.recipe;

create view funnel_by_agent with (security_invoker = true) as
  select coalesce(e.team_member_email, 'unassigned') as team_member_email,
         count(distinct e.apn) filter (where e.stage = 'signal')         as signal,
         count(distinct e.apn) filter (where e.stage = 'contacted')      as contacted,
         count(distinct e.apn) filter (where e.stage = 'conversation')   as conversation,
         count(distinct e.apn) filter (where e.stage = 'appointment')    as appointment,
         count(distinct e.apn) filter (where e.stage = 'listing')        as listing,
         count(distinct e.apn) filter (where e.stage = 'not_interested') as not_interested,
         count(distinct e.apn) filter (where e.stage = 'bad_data')       as bad_data,
         round(avg(s.score), 1)                                          as avg_score
  from stage_events e
  join latest_scores s on s.apn = e.apn
  group by coalesce(e.team_member_email, 'unassigned');

grant select on funnel_by_recipe, funnel_by_agent to authenticated;
