-- Phase 1 foundation schema for territory-signals.
create extension if not exists postgis with schema extensions;
create extension if not exists pgcrypto with schema extensions;

set search_path = public, extensions;

create table neighborhoods (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  planning_area text,
  geom geometry(MultiPolygon, 4326),
  is_official boolean not null default false,
  created_at timestamptz not null default now()
);

create table parcels (
  apn text primary key,
  situs_address text,
  zip text,
  planning_area text,
  neighborhood text,
  geom geometry(MultiPolygon, 4326),
  centroid geometry(Point, 4326),
  lot_sqft numeric,
  land_use text,
  zoning text,
  year_built int,
  last_recorded_doc_date date,
  source_key text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table source_runs (
  id uuid primary key default gen_random_uuid(),
  source_key text not null,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null check (status in ('running', 'success', 'failed')),
  rows_fetched int,
  rows_matched int,
  rows_unmatched int,
  error_message text,
  created_at timestamptz not null default now()
);

create table raw_records (
  id uuid primary key default gen_random_uuid(),
  source_key text not null,
  source_record_id text not null,
  run_id uuid not null references source_runs(id),
  payload jsonb not null,
  fetched_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  unique (source_key, source_record_id, fetched_at)
);

create table signals (
  id uuid primary key default gen_random_uuid(),
  apn text not null references parcels(apn),
  signal_type text not null,
  signal_group text not null,
  signal_date date,
  detected_at timestamptz not null default now(),
  source_key text not null,
  source_record_id text not null,
  run_id uuid references source_runs(id),
  confidence numeric not null check (confidence >= 0 and confidence <= 1),
  match_method text not null check (match_method in ('apn', 'spatial', 'address', 'name')),
  is_estimate boolean not null default false,
  is_sample boolean not null default false,
  details jsonb,
  created_at timestamptz not null default now()
);

create table owners (
  id uuid primary key default gen_random_uuid(),
  apn text not null references parcels(apn),
  owner_name text,
  mailing_address text,
  owner_occupied boolean,
  absentee boolean,
  out_of_state boolean,
  last_sale_date date,
  last_sale_price numeric,
  mortgage_open boolean,
  est_value numeric,
  est_equity numeric,
  provider text not null check (provider in ('attom', 'sample')),
  is_sample boolean not null default false,
  as_of date not null,
  created_at timestamptz not null default now()
);

create table sales_history (
  id uuid primary key default gen_random_uuid(),
  apn text not null references parcels(apn),
  sale_date date,
  sale_price numeric,
  doc_type text,
  provider text not null,
  is_sample boolean not null default false,
  created_at timestamptz not null default now()
);

create table scores (
  id uuid primary key default gen_random_uuid(),
  apn text not null references parcels(apn),
  score int not null check (score >= 0 and score <= 100),
  components jsonb,
  reason_text text,
  recipe_matches text[],
  model_version text not null,
  scored_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create table suppressions (
  id uuid primary key default gen_random_uuid(),
  apn text not null references parcels(apn),
  reason text not null,
  until_date date,
  created_at timestamptz not null default now()
);

create table outreach (
  id uuid primary key default gen_random_uuid(),
  apn text not null references parcels(apn),
  channel text not null check (channel in ('mail', 'email', 'call_task')),
  status text not null check (status in ('draft', 'awaiting_approval', 'approved', 'sent', 'suppressed')),
  content text,
  source_facts jsonb,
  approved_by text,
  sent_at timestamptz,
  created_at timestamptz not null default now()
);

create table outcomes (
  id uuid primary key default gen_random_uuid(),
  apn text not null references parcels(apn),
  team_member_email text,
  status text not null check (status in ('contacted', 'conversation', 'appointment', 'listing', 'not_interested', 'bad_data')),
  noted_at timestamptz not null default now(),
  note text,
  created_at timestamptz not null default now()
);

create table team_members (
  id uuid primary key default gen_random_uuid(),
  email text not null unique,
  name text,
  role text not null check (role in ('owner', 'agent', 'assistant')),
  created_at timestamptz not null default now()
);

-- Indexes
create index neighborhoods_geom_gix on neighborhoods using gist (geom);
create index parcels_geom_gix on parcels using gist (geom);
create index parcels_centroid_gix on parcels using gist (centroid);
create index signals_apn_type_date_idx on signals (apn, signal_type, signal_date);
create index scores_scored_at_idx on scores (scored_at);
create index outreach_status_idx on outreach (status);

-- Row level security: authenticated users may read; writes only via the service
-- role, which bypasses RLS. No insert/update/delete policies are defined.
do $$
declare t text;
begin
  foreach t in array array[
    'neighborhoods','parcels','source_runs','raw_records','signals','owners',
    'sales_history','scores','suppressions','outreach','outcomes','team_members'
  ] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('create policy %I on public.%I for select to authenticated using (true)',
                   t || '_select_authenticated', t);
  end loop;
end $$;
