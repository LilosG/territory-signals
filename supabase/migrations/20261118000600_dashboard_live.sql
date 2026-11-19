-- Phase 5B: team login gate, working actions, share links, lead/map queries and trend views.
set search_path = public, extensions;

-- ---------------------------------------------------------------------------------------------
-- 1. Who is on the team. The JWT email is the identity; only team_members may read or act.
-- ---------------------------------------------------------------------------------------------
create or replace function public.current_email() returns text
language sql stable as $$
  select lower(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'email')
$$;

create unique index if not exists team_members_email_lower_key on team_members (lower(email));

create or replace function public.is_team_member() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.team_members t where lower(t.email) = public.current_email())
$$;

-- Reads are limited to team members (before: any authenticated user). Policy names, commands and roles
-- are unchanged; only the condition. The subselect makes Postgres evaluate it once per query.
do $$
declare t text;
begin
  foreach t in array array[
    'neighborhoods','parcels','source_runs','raw_records','signals','owners','sales_history','scores',
    'suppressions','outreach','outcomes','team_members','stage_events'
  ] loop
    execute format('alter policy %I on public.%I using ((select public.is_team_member()))',
                   t || '_select_authenticated', t);
  end loop;
end $$;

-- Sign-in gate in the database: an auth user can only be created for an email in team_members.
create or replace function public.auth_gate_team_only() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.email is null
     or not exists (select 1 from public.team_members t where lower(t.email) = lower(new.email)) then
    raise exception 'This email is not on the team.' using errcode = 'P0001';
  end if;
  return new;
end;
$$;

do $$
begin
  if to_regclass('auth.users') is not null then
    drop trigger if exists auth_gate_team_only on auth.users;
    create trigger auth_gate_team_only before insert on auth.users
      for each row execute function public.auth_gate_team_only();
  end if;
end $$;

-- ---------------------------------------------------------------------------------------------
-- 2. Outreach edits and share links
-- ---------------------------------------------------------------------------------------------
alter table outreach
  add column original_content text,
  add column edited_by text,
  add column edited_at timestamptz;

create table share_links (
  token text primary key,
  apn text not null references parcels(apn),
  created_by text not null,
  created_at timestamptz not null default now(),
  revoked_at timestamptz
);
create index share_links_apn_idx on share_links (apn);
alter table share_links enable row level security;
create policy share_links_select_authenticated on share_links for select to authenticated
  using ((select public.is_team_member()));

-- ---------------------------------------------------------------------------------------------
-- 3. Working actions. SECURITY DEFINER; each checks the caller is on the team.
-- ---------------------------------------------------------------------------------------------
create or replace function public.require_team() returns text
language plpgsql stable security definer set search_path = public as $$
begin
  if not public.is_team_member() then
    raise exception 'Not a team member' using errcode = '42501';
  end if;
  return public.current_email();
end;
$$;

create or replace function public.edit_outreach(p_id uuid, p_content text) returns void
language plpgsql security definer set search_path = public as $$
declare who text := public.require_team(); o outreach;
begin
  select * into o from outreach where id = p_id for update;
  if not found then raise exception 'Draft not found'; end if;
  if o.status not in ('draft', 'awaiting_approval') then
    raise exception 'Only a draft that is not yet approved can be edited';
  end if;
  if p_content is null or btrim(p_content) = '' then raise exception 'The draft cannot be empty'; end if;
  update outreach
     set original_content = coalesce(original_content, content),
         content = p_content, edited_by = who, edited_at = now()
   where id = p_id;
end;
$$;

-- Approval never sends anything (mode is preview); it only moves the draft to approved.
create or replace function public.approve_outreach(p_id uuid) returns void
language plpgsql security definer set search_path = public as $$
declare who text := public.require_team(); o outreach;
begin
  select * into o from outreach where id = p_id for update;
  if not found then raise exception 'Draft not found'; end if;
  if o.blocked_reason is not null then
    raise exception 'Blocked: %', o.blocked_reason using errcode = 'check_violation';
  end if;
  if o.status not in ('draft', 'awaiting_approval') then
    raise exception 'Draft is already %', o.status;
  end if;
  update outreach set status = 'approved', approved_by = who where id = p_id;
end;
$$;

-- Records an outcome. A parcel's first dashboard stage also writes the 'signal' stage (source system), so the
-- funnel never shows more contacted parcels than parcels that entered it.
create or replace function public.record_stage(p_apn text, p_stage text, p_note text default null) returns uuid
language plpgsql security definer set search_path = public as $$
declare who text := public.require_team(); new_id uuid;
begin
  if not exists (select 1 from parcels where apn = p_apn) then raise exception 'Unknown parcel'; end if;
  if p_stage is null or p_stage = 'signal' then raise exception 'Invalid stage'; end if;
  if not exists (select 1 from stage_events where apn = p_apn and stage = 'signal') then
    insert into stage_events (apn, stage, team_member_email, source) values (p_apn, 'signal', who, 'system');
  end if;
  insert into stage_events (apn, stage, team_member_email, note, source)
    values (p_apn, p_stage, who, nullif(btrim(coalesce(p_note, '')), ''), 'dashboard') returning id into new_id;
  return new_id;
end;
$$;

create or replace function public.create_share_link(p_apn text) returns text
language plpgsql security definer set search_path = public as $$
declare who text := public.require_team(); tok text;
begin
  if not exists (select 1 from parcels where apn = p_apn) then raise exception 'Unknown parcel'; end if;
  tok := replace(gen_random_uuid()::text || gen_random_uuid()::text, '-', '');
  insert into share_links (token, apn, created_by) values (tok, p_apn, who);
  return tok;
end;
$$;

create or replace function public.revoke_share_link(p_token text) returns void
language plpgsql security definer set search_path = public as $$
begin
  perform public.require_team();
  update share_links set revoked_at = now() where token = p_token and revoked_at is null;
  if not found then raise exception 'Share link not found or already revoked'; end if;
end;
$$;

-- The public share page. Returns property facts only: no owner, address, APN, equity, mortgage, sales or distress.
create or replace function public.share_page(p_token text)
returns table (
  neighborhood text, lot_sqft numeric, zoning text, year_built integer,
  upzoning_estimates jsonb, agent_name text, agent_email text
)
language sql stable security definer set search_path = public as $$
  select p.neighborhood, p.lot_sqft::numeric, p.zoning, p.year_built,
         coalesce((
           select jsonb_agg(distinct g.signal_type) from signals g
            where g.apn = p.apn and g.superseded_by is null and g.is_estimate
              and g.signal_type in ('sb9_lot_split_estimate', 'sb79_transit_estimate')
              and g.signal_date = (select max(m.signal_date) from signals m
                                    where m.signal_type = g.signal_type and m.superseded_by is null)
         ), '[]'::jsonb),
         tm.name, l.created_by
    from share_links l
    join parcels p on p.apn = l.apn
    left join team_members tm on lower(tm.email) = lower(l.created_by)
   where l.token = p_token and l.revoked_at is null
$$;

revoke all on function
  public.require_team(), public.edit_outreach(uuid, text), public.approve_outreach(uuid),
  public.record_stage(text, text, text), public.create_share_link(text), public.revoke_share_link(text),
  public.is_team_member(), public.current_email(), public.share_page(text)
  from public, anon;
grant execute on function
  public.edit_outreach(uuid, text), public.approve_outreach(uuid), public.record_stage(text, text, text),
  public.create_share_link(text), public.revoke_share_link(text), public.is_team_member(), public.current_email()
  to authenticated;
grant execute on function public.share_page(text) to anon, authenticated;

grant select on share_links to authenticated;

-- ---------------------------------------------------------------------------------------------
-- 4. Reads for the dashboard (security invoker: RLS applies to the signed-in user)
-- ---------------------------------------------------------------------------------------------
create view latest_owners with (security_invoker = true) as
  select distinct on (apn) *
  from owners
  order by apn, as_of desc, created_at desc;
grant select on latest_owners to authenticated;

-- One page of leads, filtered in SQL. total is the match count before paging.
create or replace function public.leads_page(
  p_recipe text default null, p_group text default null, p_hood text default null,
  p_min int default null, p_max int default null, p_search text default null,
  p_limit int default 25, p_offset int default 0
) returns table (
  apn text, score int, reason_text text, recipe_matches text[], primary_recipe text, model_version text,
  scored_at timestamptz, uses_sample_data boolean,
  situs_address text, neighborhood text,
  owner_name text, owner_is_sample boolean, owner_as_of date, last_sale_date date, est_equity numeric, est_value numeric,
  signal_count bigint, latest_signal_date date, signal_types text[], outreach_status text, total bigint
)
language sql stable security invoker set search_path = public, extensions as $$
  with base as (
    select s.apn, s.score, s.reason_text, s.recipe_matches, s.primary_recipe, s.model_version, s.scored_at,
           s.uses_sample_data, p.situs_address, p.neighborhood
      from latest_scores s
      join parcels p on p.apn = s.apn
     where (p_recipe is null or p_recipe = any (s.recipe_matches))
       and (p_hood is null or p.neighborhood = p_hood)
       and (p_min is null or s.score >= p_min)
       and (p_max is null or s.score <= p_max)
       and (p_search is null or p.situs_address ilike '%' || p_search || '%' or s.apn like p_search || '%')
       and (p_group is null or exists (
             select 1 from signals g where g.apn = s.apn and g.signal_group = p_group and g.superseded_by is null))
       and not exists (select 1 from suppressions x
                        where x.apn = s.apn and (x.until_date is null or x.until_date >= current_date))
  ), page as (
    select b.*, count(*) over () as total from base b order by b.score desc, b.apn limit p_limit offset p_offset
  )
  select g.apn, g.score, g.reason_text, g.recipe_matches, g.primary_recipe, g.model_version, g.scored_at,
         g.uses_sample_data, g.situs_address, g.neighborhood,
         o.owner_name, o.is_sample, o.as_of, o.last_sale_date, o.est_equity, o.est_value,
         sg.n, sg.latest, sg.types, ob.status, g.total
    from page g
    left join latest_owners o on o.apn = g.apn
    left join lateral (
      select count(*) as n, max(signal_date) as latest, array_agg(distinct signal_type) as types
        from signals where apn = g.apn and superseded_by is null) sg on true
    left join lateral (
      select (array_agg(status order by case status when 'sent' then 4 when 'awaiting_approval' then 3
                                                    when 'approved' then 2 else 1 end desc))[1] as status
        from outreach where apn = g.apn and channel <> 'call_task' and status in
             ('draft', 'awaiting_approval', 'approved', 'sent')) ob on true
   order by g.score desc, g.apn
$$;

-- Compact map payload: one array row [apn, score, primary_recipe, neighborhood, lng, lat] per scored parcel.
create or replace function public.map_points(
  p_recipe text default null, p_group text default null, p_hood text default null,
  p_min int default null, p_max int default null
) returns jsonb
language sql stable security invoker set search_path = public, extensions as $$
  select coalesce(jsonb_agg(jsonb_build_array(
           s.apn, s.score, s.primary_recipe, p.neighborhood,
           round(st_x(p.centroid)::numeric, 6), round(st_y(p.centroid)::numeric, 6))), '[]'::jsonb)
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

grant execute on function public.leads_page(text, text, text, int, int, text, int, int),
                          public.map_points(text, text, text, int, int) to authenticated;
revoke execute on function public.leads_page(text, text, text, int, int, text, int, int),
                           public.map_points(text, text, text, int, int) from anon, public;

-- ---------------------------------------------------------------------------------------------
-- 5. Trend aggregates (monthly, by neighborhood). sample_rows counts rows that are sample data.
-- ---------------------------------------------------------------------------------------------
-- Turnover = arm's-length sales: a sales_history row that is also an ownership_transfer signal is excluded.
create view trend_turnover_monthly with (security_invoker = true) as
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

create view trend_signals_monthly with (security_invoker = true) as
  select date_trunc('month', g.signal_date)::date as month, p.neighborhood,
         g.signal_type, g.signal_group,
         count(*) as signals, count(*) filter (where g.is_sample) as sample_rows
    from signals g
    join parcels p on p.apn = g.apn
   where g.superseded_by is null and g.signal_date is not null
   group by 1, 2, 3, 4;

-- Upzoning estimates: distinct parcels on the latest snapshot of each estimate type.
create view trend_upzoning_by_hood with (security_invoker = true) as
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

create view trend_recipes_by_hood with (security_invoker = true) as
  select p.neighborhood, r.recipe, count(*) as parcels,
         count(*) filter (where s.uses_sample_data) as sample_rows
    from latest_scores s
    join parcels p on p.apn = s.apn
    cross join lateral unnest(s.recipe_matches) as r(recipe)
   group by 1, 2;

-- Overall funnel plus how many of its parcels have a sample-derived score.
create view funnel_overall with (security_invoker = true) as
  select count(distinct e.apn) filter (where e.stage = 'signal')         as signal,
         count(distinct e.apn) filter (where e.stage = 'contacted')      as contacted,
         count(distinct e.apn) filter (where e.stage = 'conversation')   as conversation,
         count(distinct e.apn) filter (where e.stage = 'appointment')    as appointment,
         count(distinct e.apn) filter (where e.stage = 'listing')        as listing,
         count(distinct e.apn) filter (where e.stage = 'not_interested') as not_interested,
         count(distinct e.apn) filter (where e.stage = 'bad_data')       as bad_data,
         count(distinct e.apn) filter (where s.uses_sample_data)         as sample_parcels
    from stage_events e
    left join latest_scores s on s.apn = e.apn;

grant select on trend_turnover_monthly, trend_signals_monthly, trend_upzoning_by_hood,
                trend_recipes_by_hood, funnel_overall to authenticated;
