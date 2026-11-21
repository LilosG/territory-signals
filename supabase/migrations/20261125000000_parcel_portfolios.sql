-- Phase 5L: deterministic territory portfolio clustering.
-- One row per parcel per recompute (the table is refreshed by territory.portfolio after owner loads).
-- portfolio_key groups parcels that share a normalized mailing address or a corporate/trust owner name;
-- entity_type is one of trust, llc_corp, individual_multi, single. Values are sums over the group's parcels.
create table public.parcel_portfolios (
  id uuid primary key default gen_random_uuid(),
  apn text not null references public.parcels(apn) on delete cascade,
  portfolio_key text not null,
  entity_type text not null check (entity_type in ('trust', 'llc_corp', 'individual_multi', 'single')),
  territory_parcel_count int not null default 1 check (territory_parcel_count >= 1),
  total_est_value numeric,
  total_est_equity numeric,
  is_sample boolean not null default false,
  computed_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create index parcel_portfolios_apn_computed_idx on public.parcel_portfolios (apn, computed_at desc);
create index parcel_portfolios_key_idx on public.parcel_portfolios (portfolio_key);

alter table public.parcel_portfolios enable row level security;
create policy parcel_portfolios_select_authenticated on public.parcel_portfolios
  for select to authenticated using (true);
grant select on public.parcel_portfolios to authenticated;
revoke all on public.parcel_portfolios from anon;

-- The newest computed row per parcel (readers use this; the table keeps the recompute history).
create view public.latest_parcel_portfolios with (security_invoker = true) as
  select distinct on (apn) id, apn, portfolio_key, entity_type, territory_parcel_count,
         total_est_value, total_est_equity, is_sample, computed_at, created_at
    from public.parcel_portfolios
   order by apn, computed_at desc, created_at desc;

grant select on public.latest_parcel_portfolios to authenticated;
revoke all on public.latest_parcel_portfolios from anon;
