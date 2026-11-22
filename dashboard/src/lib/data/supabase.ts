import { titleAddress } from '../format';
import { topSignalLine, recipeSignalLine, type Marked } from '../present';
import type { SupabaseClient } from '@supabase/supabase-js';
import { loadClientConfig } from '../config';
import { EVENT_TYPES, INTERNAL_SOURCES, RECIPE_LABELS, SENSITIVE_TYPES, SOURCE_CATALOG, STAGES, TRAIT_TYPES, bandOf } from './catalog';
import type { DataProvider, MarkSample, SharePageReader } from './provider';
import { buildTrends, leadStatus, scoreItems, yearsSince, type TrendRows } from './shared';
import type {
  AiStatus, AiTaskRow, AttomUsage, StageValue, WeeklyBriefAi, Backtest, ClientConfig, Coverage, FunnelRow, LeadDetail, LeadFilters, LeadPage, LeadSummary, MapData, NavCounts, OffMarketPage,
  Outreach, OutreachItem, OutreachPage, Performance, Pipeline, RecentOutcome, RecipeCard, SearchHit, SharePage,
  SignalEvent, SourceCard, StatSeries, TeamMember, TodayFeed, Trends,
} from './types';

type Row = Record<string, any>;
const DAY = 86_400_000;
const must = <T>(res: { data: T | null; error: { message: string } | null }, what: string): T => {
  if (res.error) throw new Error(`${what}: ${res.error.message}`);
  return res.data as T;
};
const count = (res: { count: number | null; error: { message: string } | null }, what: string): number => {
  if (res.error) throw new Error(`${what}: ${res.error.message}`);
  return res.count ?? 0;
};
const num = (v: unknown) => Number(v ?? 0);

// Whether any displayed score is sample data. Cached briefly so every page does not pay for it.
let sampleCache: { at: number; value: boolean } | null = null;

/** Parcel columns without the polygon geometry (the dashboard never needs it). */
const PARCEL_COLS = 'apn,situs_address,zip,planning_area,neighborhood,centroid,lot_sqft,land_use,zoning,year_built,last_recorded_doc_date,source_key,created_at,updated_at';

function toLead(r: Row, now: Date): LeadSummary {
  return {
    parcel: { apn: r.apn, situs_address: titleAddress(r.situs_address) || null, neighborhood: r.neighborhood },
    score: { score: r.score, reason_text: r.reason_text, recipe_matches: r.recipe_matches ?? [], primary_recipe: r.primary_recipe, model_version: r.model_version, scored_at: r.scored_at, uses_sample_data: r.uses_sample_data },
    owner: r.owner_name !== null || r.owner_as_of ? { owner_name: r.owner_name, is_sample: !!r.owner_is_sample, last_sale_date: r.last_sale_date, est_equity: r.est_equity, est_value: r.est_value != null ? Number(r.est_value) : null, absentee: r.absentee ?? null, out_of_state: r.out_of_state ?? null } : null,
    years_owned: yearsSince(r.last_sale_date, now),
    lot_sqft: r.lot_sqft != null ? Number(r.lot_sqft) : null,
    zoning: r.zoning ?? null,
    latest_signal_date: r.latest_event_date ?? null,
    top_components: (r.top_components ?? []).map((c: Row) => ({ key: c.key, facts: c.facts ?? null, points: num(c.points), signal_date: c.signal_date ?? null, is_sample: !!c.is_sample, is_estimate: !!c.is_estimate })),
    status: r.outreach_status === 'draft' ? 'draft_ready' : (r.outreach_status ?? 'new'),
    is_sample: !!r.uses_sample_data || !!r.owner_is_sample,
  };
}

function toOutreachItem(r: Row): OutreachItem {
  return {
    id: r.id, apn: r.apn, channel: r.channel, status: r.status, recipe: r.recipe, content: r.content,
    blocked_reason: r.blocked_reason, blocked: String(r.blocked_reason ?? '').split(';').map((x) => x.trim()).filter(Boolean),
    uses_sample_data: !!r.uses_sample_data, situs_address: titleAddress(r.situs_address) || null, neighborhood: r.neighborhood,
    score: r.score ?? null, assigned_name: r.assigned_name ?? null, created_at: r.created_at, due_date: r.due_date ?? null, approved_by: r.approved_by ?? null,
  };
}

/** Daily rows from today_stats -> a series with this week's and last week's totals; weekly rows from today_stat_history add the
 *  history that tells a real week-over-week change from the initial data load. */
function toSeries(rows: Row[], metric: StatSeries['metric'], history: Row[] = []): StatSeries {
  const days = rows.filter((r) => r.metric === metric).map((r) => ({ day: String(r.day), n: num(r.n) })).sort((a, b) => a.day.localeCompare(b.day));
  const sum = (xs: { n: number }[]) => xs.reduce((a, b) => a + b.n, 0);
  const h = history.filter((r) => r.metric === metric).sort((a, b) => num(a.weeks_ago) - num(b.weeks_ago));
  return {
    metric, days, this_week: sum(days.slice(-7)), last_week: sum(days.slice(-14, -7)),
    weeks: h.map((r) => num(r.n)), first_day: h.length && h[0]!.first_day ? String(h[0]!.first_day).slice(0, 10) : null,
  };
}

const FUNNEL_KEYS = ['signal', 'contacted', 'conversation', 'appointment', 'listing'] as const;
const funnelRow = (label: string, r: Row | undefined): FunnelRow => ({
  label,
  stages: STAGES.filter((s) => (FUNNEL_KEYS as readonly string[]).includes(s.key))
    .map((s) => ({ key: s.key as FunnelRow['stages'][number]['key'], label: s.label, count: num(r?.[s.key]) })),
});

const FRIENDLY_NOT_CONNECTED = /awaiting manual|manual download|not configured|not connected/i;

/** All reads go through `db`, the signed-in user's client, so row level security applies. `territory` limits everything to one neighborhood. */
export function supabaseProvider(db: SupabaseClient, mark: MarkSample, territory: string | null = null): DataProvider {
  const now = () => new Date();
  const hood = territory;
  /** Territory-aware filters: the switcher wins over a neighborhood chosen on the page. */
  const rpcArgs = (f: LeadFilters = {}) => ({
    p_recipe: f.recipe || null, p_group: f.signalGroup || null, p_hood: hood ?? (f.neighborhood || null),
    p_min: f.minScore ?? null, p_max: f.maxScore ?? null, p_search: f.search || null,
  });

  async function anySample(): Promise<boolean> {
    if (sampleCache && Date.now() - sampleCache.at < 60_000) return sampleCache.value;
    const res = await db.from('scored_parcels').select('apn').eq('uses_sample_data', true).limit(1);
    const value = (must(res, 'sample check') as Row[]).length > 0;
    sampleCache = { at: Date.now(), value };
    return value;
  }

  async function addresses(apns: string[]): Promise<Map<string, Row>> {
    if (!apns.length) return new Map();
    const rows = must(await db.from('parcels').select('apn,situs_address,neighborhood').in('apn', apns), 'parcels') as Row[];
    return new Map(rows.map((r) => [r.apn, { ...r, situs_address: titleAddress(r.situs_address) || null }]));
  }

  const navCounts = async (): Promise<NavCounts> => {
    const c = must(await db.rpc('nav_counts', { p_hood: hood }), 'nav_counts') as Row;
    return { leads: num(c.leads), drafts: num(c.drafts), awaiting_approval: num(c.awaiting_approval), approved: num(c.approved), call_tasks: num(c.call_tasks), off_market: num(c.off_market) };
  };

  // ---- AI layer (Phase 5F). Everything here returns null/empty when llm.enabled is false. ----
  const aiOn = () => loadClientConfig().ai.enabled;
  async function aiRows(task: string, subjectIds?: string[], limit = 60): Promise<Row[]> {
    if (!aiOn()) return [];
    let q = db.from('latest_ai_outputs').select('subject_id,output,uses_sample,model,created_at').eq('task', task).eq('client_id', loadClientConfig().client_id);
    if (subjectIds) q = q.in('subject_id', subjectIds); else q = q.order('subject_id', { ascending: false }).limit(limit);
    return must(await q, `ai ${task}`) as Row[];
  }
  async function aiHeadlines(apns: string[]): Promise<Map<string, string>> {
    if (apns.length === 0) return new Map();
    return new Map((await aiRows('lead_brief', apns)).map((r) => [String(r.subject_id), String((r.output as Row).headline)]));
  }
  /** Top-signal lines for a set of parcels, from their latest score components (one shared rule: topSignal in present.ts). */
  async function topSignalLines(apns: string[]): Promise<Map<string, Marked | null>> {
    if (apns.length === 0) return new Map();
    const rows = must(await db.from('latest_scores').select('apn,components').in('apn', apns), 'latest_scores') as Row[];
    return new Map(rows.map((r) => [String(r.apn), topSignalLine(r.components)]));
  }
  /** Raw score components per parcel, for the recipe-scoped lines on /recipes. */
  async function componentsByApn(apns: string[]): Promise<Map<string, unknown>> {
    if (apns.length === 0) return new Map();
    const rows = must(await db.from('latest_scores').select('apn,components').in('apn', apns), 'latest_scores') as Row[];
    return new Map(rows.map((r) => [String(r.apn), r.components]));
  }
  /** Territory portfolios for parcels whose owner holds 2+ territory parcels. An older database without the
   *  Phase 5L table simply returns no portfolios (nothing is invented). */
  async function portfolios(apns: string[]): Promise<Map<string, NonNullable<LeadDetail['portfolio']>>> {
    if (apns.length === 0) return new Map();
    const res = await db.from('latest_parcel_portfolios').select('*').in('apn', apns).gte('territory_parcel_count', 2);
    if (res.error) return new Map();
    const rows = (res.data ?? []) as Row[];
    if (rows.some((r) => r.is_sample)) mark();
    return new Map(rows.map((r) => [String(r.apn), {
      portfolio_key: String(r.portfolio_key), entity_type: r.entity_type,
      territory_parcel_count: num(r.territory_parcel_count),
      total_est_value: r.total_est_value != null ? Number(r.total_est_value) : null,
      total_est_equity: r.total_est_equity != null ? Number(r.total_est_equity) : null,
      is_sample: !!r.is_sample,
    }]));
  }
  const toWeekly = (r: Row): WeeklyBriefAi => {
    const o = r.output as Row;
    return { week_start: String(r.subject_id), title: o.title, intro: o.intro, sections: o.sections ?? [], newsletter_paragraph: o.newsletter_paragraph, model: r.model, created_at: r.created_at };
  };

  async function aiStatus(): Promise<AiStatus | null> {
    const cfg = loadClientConfig();
    if (!cfg.ai.enabled) return null;
    const [runs, spend] = await Promise.all([
      db.from('ai_task_runs').select('*').eq('client_id', cfg.client_id).order('started_at', { ascending: false }).limit(60),
      db.from('ai_month_spend').select('task,cost_usd').eq('client_id', cfg.client_id),
    ]);
    const runRows = must(runs, 'ai_task_runs') as Row[];
    const monthBy = new Map((must(spend, 'ai_month_spend') as Row[]).map((r) => [String(r.task), num(r.cost_usd)]));
    if (runRows.length === 0) return null;
    const tasks: AiTaskRow[] = (['permit_intent', 'lead_brief', 'weekly_brief'] as const).flatMap((t) => {
      const r = runRows.find((x) => x.task === t);
      if (!r) return [];
      return [{ task: t, model: r.model, status: r.status, skip_reason: r.skip_reason, last_run_at: r.started_at, calls: num(r.calls), cached: num(r.cached), invalid: num(r.invalid), rejected: num(r.rejected),
        tokens: num(r.input_tokens) + num(r.output_tokens), cost_run: r.cost_unknown ? null : num(r.cost_usd), cost_unknown: !!r.cost_unknown, cost_month: monthBy.get(t) ?? 0, warnings: (r.warnings as string[]) ?? [] }];
    });
    const warnings = [...new Set(tasks.flatMap((t) => t.warnings))];
    return { tasks, monthly_budget_usd: cfg.ai.monthly_budget_usd, cost_month: [...monthBy.values()].reduce((a, b) => a + b, 0), warnings };
  }


  /** ATTOM trial usage from the append-only api_usage_log. Null when the table does not exist yet. */
  async function attomUsage(): Promise<AttomUsage | null> {
    const today = new Date().toISOString().slice(0, 10);
    const monthStart = today.slice(0, 7) + '-01';
    const [todayRes, monthRes, lastRes] = await Promise.all([
      db.from('api_usage_log').select('request_count').eq('source_key', 'attom').eq('call_date', today),
      db.from('api_usage_log').select('request_count').eq('source_key', 'attom').gte('call_date', monthStart),
      db.from('api_usage_log').select('created_at').eq('source_key', 'attom').order('created_at', { ascending: false }).limit(1),
    ]);
    if (todayRes.error || monthRes.error) return null;
    const sum = (rows: Row[]) => rows.reduce((total, r) => total + num(r.request_count), 0);
    const last = (lastRes.error ? [] : lastRes.data ?? []) as Row[];
    return { calls_today: sum((todayRes.data ?? []) as Row[]), daily_call_cap: 450,
      calls_this_month: sum((monthRes.data ?? []) as Row[]), last_call_at: last[0]?.created_at ?? null };
  }

  const provider: DataProvider = {
    name: 'supabase',
    territory: hood,

    getNavCounts: navCounts,

    async getLeads(filters = {}, page = 1, pageSize = 25) {
      const rows = must(await db.rpc('leads_list', {
        ...rpcArgs(filters),
        p_status: filters.status ?? null, p_new: !!filters.isNew, p_sort: filters.sort ?? 'score',
        p_limit: pageSize, p_offset: (page - 1) * pageSize,
      }), 'leads_list') as Row[];
      const t = now();
      const items = rows.map((r) => toLead(r, t));
      const heads = await aiHeadlines(items.map((l) => l.parcel.apn));
      for (const l of items) l.ai_headline = heads.get(l.parcel.apn) ?? null;
      if (items.some((l) => l.is_sample)) mark();
      return { items, total: num(rows[0]?.total), page, pageSize } satisfies LeadPage;
    },

    async getTodayFeed(): Promise<TodayFeed> {
      const cfg = loadClientConfig();
      const [coverage, leads, stats, history, recipes, counts, approvals, calls, signals, models] = await Promise.all([
        provider.getCoverage(),
        provider.getLeads({ minScore: 30 }, 1, 8),
        db.rpc('today_stats', { p_hood: hood }),
        db.rpc('today_stat_history', { p_hood: hood }),
        db.rpc('recipe_summary', { p_hood: hood }),
        navCounts(),
        (() => { let q = db.from('outreach_queue').select('*').eq('status', 'awaiting_approval').neq('channel', 'call_task').order('created_at', { ascending: false }).limit(5); if (hood) q = q.eq('neighborhood', hood); return q; })(),
        (() => { let q = db.from('outreach_queue').select('*').eq('channel', 'call_task').in('status', ['draft', 'awaiting_approval', 'approved']).order('created_at', { ascending: false }).limit(5); if (hood) q = q.eq('neighborhood', hood); return q; })(),
        db.rpc('recent_signals', { p_hood: hood, p_days: 7, p_limit: 5 }),
        db.rpc('scoring_model_weeks'),
      ]);
      const weeklyRow = (await aiRows('weekly_brief', undefined, 1))[0];
      const statRows = must(stats, 'today_stats') as Row[];
      const scoringUpdated = !models.error && !!((models.data ?? []) as Row[])[0]?.updated;     // older database: no flag
      const histRows = (history.error ? [] : history.data ?? []) as Row[];     // older database: tiles simply show the plain change
      const byRecipe = new Map((must(recipes, 'recipe_summary') as Row[]).map((r) => [r.recipe, r]));
      const sigRows = must(signals, 'recent_signals') as Row[];
      const apRows = must(approvals, 'approvals') as Row[];
      const callRows = must(calls, 'call tasks') as Row[];
      if (apRows.some((r) => r.uses_sample_data) || callRows.some((r) => r.uses_sample_data)) mark();
      const new_signals: SignalEvent[] = sigRows.map((r) => ({
        apn: r.apn, situs_address: titleAddress(r.situs_address) || null, neighborhood: r.neighborhood, type: r.signal_type, group: r.signal_group,
        date: r.signal_date, count: num(r.n), is_sample: !!r.is_sample, is_estimate: !!r.is_estimate, source_key: r.source_key, source_record_id: r.source_record_id, details: r.details,
      }));
      return {
        as_of: new Date().toISOString(), territory: hood, coverage,
        stats: (['signals', 'active_leads', 'drafts', 'outcomes'] as const).map((m) => ({ ...toSeries(statRows, m, histRows), ...(m === 'active_leads' && scoringUpdated ? { scoring_updated: true } : {}) })),
        leads_total: counts.leads, top_leads: leads.items,
        recipe_strip: cfg.recipes.filter((r) => r.enabled).map((r) => {
          const parcels = num(byRecipe.get(r.key)?.parcels);
          return { key: r.key, label: r.name, parcels, new_this_week: num(byRecipe.get(r.key)?.new_this_week), idle_reason: parcels > 0 ? null : idleReason(r.key, r.enabled, r.requires_data ?? []) };
        }),
        weekly: weeklyRow ? toWeekly(weeklyRow) : null,
        approvals: apRows.map(toOutreachItem), approvals_total: counts.awaiting_approval,
        call_tasks: callRows.map(toOutreachItem), call_tasks_total: counts.call_tasks,
        new_signals, new_signals_total: sigRows.length ? num(sigRows[0]!.total) : 0,
      };
    },

    async getLead(apn): Promise<LeadDetail | null> {
      const [parcel, score, owner, sales, events, context, outreach, stages, links] = await Promise.all([
        db.from('parcels').select(PARCEL_COLS).eq('apn', apn).maybeSingle(),
        db.from('latest_scores').select('*').eq('apn', apn).maybeSingle(),
        db.from('latest_owners').select('*').eq('apn', apn).maybeSingle(),
        db.from('sales_history').select('*').eq('apn', apn).order('sale_date', { ascending: false }).limit(25),
        // Selling events only: never the "other" permit group, never snapshots or sensitive context.
        db.from('signals').select('*', { count: 'exact' }).eq('apn', apn).is('superseded_by', null).in('signal_type', [...EVENT_TYPES]).neq('signal_group', 'other')
          .order('signal_date', { ascending: false, nullsFirst: false }).limit(80),
        db.from('signals').select('*').eq('apn', apn).is('superseded_by', null).in('signal_type', [...SENSITIVE_TYPES, ...TRAIT_TYPES])
          .order('signal_date', { ascending: false, nullsFirst: false }).limit(40),
        db.from('outreach').select('*').eq('apn', apn).order('created_at', { ascending: false }),
        db.from('stage_events').select('*').eq('apn', apn).order('occurred_at', { ascending: false }).limit(50),
        db.from('share_links').select('*').eq('apn', apn).is('revoked_at', null).order('created_at', { ascending: false }),
      ]);
      const p = must(parcel, 'parcel') as Row | null;
      const sc = must(score, 'score') as Row | null;
      if (!p || !sc) return null;
      const o = must(owner, 'owner') as Row | null;
      const sl = must(sales, 'sales') as Row[];
      const out = must(outreach, 'outreach') as Outreach[];
      const ctx = must(context, 'signal context') as LeadDetail['signals'];
      const latestOf = (types: readonly string[]) => {
        const seen = new Set<string>(); const keep: LeadDetail['signals'] = [];
        for (const s of ctx) if (types.includes(s.signal_type) && !seen.has(s.signal_type)) { seen.add(s.signal_type); keep.push(s); }
        return keep;
      };
      const isSample = !!sc.uses_sample_data || !!o?.is_sample || sl.some((s) => s.is_sample);
      if (isSample) mark();
      const briefRow = (await aiRows('lead_brief', [apn]))[0];
      const bo = briefRow?.output as Row | undefined;
      const portfolioBy = await portfolios([apn]);
      return {
        ai_brief: briefRow && bo ? { headline: bo.headline, summary: bo.summary, claims: bo.claims ?? [], suggested_angle: bo.suggested_angle, uses_sample: !!briefRow.uses_sample, model: briefRow.model, created_at: briefRow.created_at } : null,
        portfolio: portfolioBy.get(apn) ?? null,
        parcel: { ...p, situs_address: titleAddress(p.situs_address) || null, geom: null, centroid: p.centroid ?? null } as LeadDetail['parcel'],
        score: sc as LeadDetail['score'],
        score_items: scoreItems(sc.components),
        owner: o as LeadDetail['owner'],
        years_owned: yearsSince(o?.last_sale_date, now()),
        sales: sl as LeadDetail['sales'],
        signals: must(events, 'signals') as LeadDetail['signals'],
        signal_total: count(events, 'signals'),
        sensitive_signals: ctx.filter((s) => (SENSITIVE_TYPES as readonly string[]).includes(s.signal_type)),
        trait_signals: latestOf(TRAIT_TYPES),
        outreach: out,
        stage_events: must(stages, 'stage events') as LeadDetail['stage_events'],
        share_links: must(links, 'share links') as LeadDetail['share_links'],
        status: leadStatus(out),
        is_sample: isSample,
      };
    },

    async getMapData(filters = {}): Promise<MapData> {
      const rows = must(await db.rpc('map_points', (({ p_search: _s, ...rest }) => rest)(rpcArgs(filters))), 'map_points') as [string, number, string | null, string, number, number][];
      const sample = await anySample();
      if (sample) mark();
      return { is_sample: sample, points: rows.map(([apn, score, recipe, neighborhood, lng, lat]) => ({ apn, score, band: bandOf(score), recipe, neighborhood, lng, lat })) };
    },

    async getTrends(area): Promise<Trends> {
      const cfg = loadClientConfig();
      const hoods = area === 'All' || !cfg.territory.neighborhoods.includes(area) ? cfg.territory.neighborhoods : [area];
      const start = new Date(Date.UTC(now().getUTCFullYear(), now().getUTCMonth() - 11, 1)).toISOString().slice(0, 10);
      const [t, s, u, r] = await Promise.all([
        db.from('trend_turnover_monthly').select('*').gte('month', start),
        db.from('trend_signals_monthly').select('*').gte('month', start),
        db.from('trend_upzoning_by_hood').select('*'),
        db.from('trend_recipes_by_hood').select('*'),
      ]);
      const rows: TrendRows = {
        turnover: must(t, 'turnover') as any, signals: must(s, 'signals trend') as any,
        upzoning: must(u, 'upzoning') as any, recipes: must(r, 'recipes') as any,
      };
      const out = buildTrends(area === 'All' ? 'All' : area, hoods, now(), rows);
      if (out.is_sample) mark();
      return out;
    },

    async getPipeline(): Promise<Pipeline> {
      const [overall, recent, values, usage] = await Promise.all([
        db.rpc('funnel_by', { p_dim: 'all', p_hood: hood }),
        db.from('stage_events').select('apn,stage,team_member_email,note,occurred_at').eq('source', 'dashboard').order('occurred_at', { ascending: false }).limit(40),
        db.rpc('pipeline_stage_value', { p_hood: hood }),
        attomUsage(),
      ]);
      const o = (must(overall, 'funnel_by') as Row[])[0];
      const valueBy = new Map((values.error ? [] : (values.data ?? []) as Row[]).map((r) => [String(r.stage), r]));    // older database: no value, GCI shows as unavailable
      const stage_values: StageValue[] = FUNNEL_KEYS.map((key) => { const v = valueBy.get(key); return { key, parcels: num(v?.parcels), valued_parcels: num(v?.valued_parcels), est_value: num(v?.est_value), sample_parcels: num(v?.sample_parcels) }; });
      const evs = must(recent, 'stage_events') as Row[];
      const addr = await addresses([...new Set(evs.map((e) => e.apn))]);
      const names = new Map((must(await db.from('team_members').select('email,name'), 'team') as Row[]).map((r) => [String(r.email).toLowerCase(), r.name]));
      const recentOut: RecentOutcome[] = evs.filter((e) => !hood || addr.get(e.apn)?.neighborhood === hood).slice(0, 10).map((e) => ({
        apn: e.apn, situs_address: addr.get(e.apn)?.situs_address ?? null, neighborhood: addr.get(e.apn)?.neighborhood ?? null,
        stage: e.stage, by: e.team_member_email ? (names.get(String(e.team_member_email).toLowerCase()) ?? e.team_member_email) : null, note: e.note, occurred_at: e.occurred_at,
      }));
      const is_sample = (await anySample()) && num(o?.signal) > 0;
      if (is_sample) mark();
      return { overall: funnelRow('All leads', o), stage_values, has_events: num(o?.signal) > 0, recent: recentOut, by_agent: [], by_recipe: [], is_sample, attom_usage: usage };
    },

    async getAiStatus(): Promise<AiStatus | null> { return aiStatus(); },

    async getBriefings(): Promise<WeeklyBriefAi[]> {
      return (await aiRows('weekly_brief', undefined, 60)).map(toWeekly);
    },

    async getPerformance(): Promise<Performance> {
      const [overall, rec, agent, cov, team] = await Promise.all([
        db.rpc('funnel_by', { p_dim: 'all', p_hood: hood }), db.rpc('funnel_by', { p_dim: 'recipe', p_hood: hood }),
        db.rpc('funnel_by', { p_dim: 'agent', p_hood: hood }), db.rpc('coverage_weekly', { p_weeks: 12, p_hood: hood }),
        db.from('team_members').select('email,name'),
      ]);
      const names = new Map((must(team, 'team') as Row[]).map((r) => [String(r.email).toLowerCase(), r.name]));
      const o = (must(overall, 'funnel_by') as Row[])[0];
      const sample = await anySample();
      if (sample && num(o?.signal) > 0) mark();
      return {
        overall: funnelRow('All leads', o), has_events: num(o?.signal) > 0, is_sample: sample && num(o?.signal) > 0,
        by_recipe: (must(rec, 'funnel_by recipe') as Row[]).map((r) => funnelRow(RECIPE_LABELS[r.label] ?? r.label, r)).sort((a, b) => b.stages[0]!.count - a.stages[0]!.count),
        by_agent: (must(agent, 'funnel_by agent') as Row[]).map((r) => funnelRow(r.label === 'unassigned' ? 'Unassigned' : (names.get(String(r.label).toLowerCase()) ?? r.label), r)),
        coverage: (must(cov, 'coverage_weekly') as Row[]).map((r) => ({ week: r.week, signals: num(r.signals), sources_live: num(r.sources_live), parcels_monitored: num(r.parcels_monitored) })),
        // Real backtests need owner sale history (Phase 6). Never show fixture numbers as live.
        backtest: null,
      };
    },

    async getBacktest(): Promise<Backtest | null> {
      const cfg = loadClientConfig();
      const res = await db.from('backtest_runs').select('*').eq('client_id', cfg.client_id)
        .order('computed_at', { ascending: false }).limit(1);
      if (res.error) return null;                                  // older database: designed empty state
      const row = ((res.data ?? []) as Row[])[0];
      if (!row) return null;
      if (row.is_sample) mark();
      const total = num(row.total_sales_evaluated);
      const flagged = num(row.flagged_before_sale_count);
      return {
        past_sales_considered: total,
        flagged_before_listing: flagged,
        share_flagged: total ? flagged / total : 0,
        capture_rate_pct: num(row.capture_rate_pct),
        avg_days_early: row.avg_days_early != null ? Number(row.avg_days_early) : 0,
        median_days_early: row.median_days_early != null ? Number(row.median_days_early) : 0,
        breakdown_by_signal_group: (row.breakdown_by_signal_group as Record<string, number>) ?? {},
        window: { from: String(row.window_start), to: String(row.window_end) },
        is_sample: !!row.is_sample,
        note: `Evaluated ${total} recorded sales; ${flagged} had a public signal 14 to 365 days before the sale.`,
        computed_at: row.computed_at,
      };
    },

    async getCoverage(): Promise<Coverage> {
      const since = new Date(Date.now() - 7 * DAY).toISOString();
      const [parcels, signals, runs, sample] = await Promise.all([
        (() => { let q = db.from('parcels').select('apn', { count: 'exact', head: true }); if (hood) q = q.eq('neighborhood', hood); return q; })(),
        db.from('signals').select('id', { count: 'exact', head: true }).is('superseded_by', null).gte('detected_at', since).neq('signal_group', 'other'),
        db.from('source_latest').select('*'),
        anySample(),
      ]);
      const latest = (must(runs, 'sources') as Row[]).filter((r) => !INTERNAL_SOURCES.has(r.source_key));
      const finished = latest.filter((r) => r.status === 'success' && r.finished_at).map((r) => r.finished_at as string).sort();
      return {
        parcels_monitored: count(parcels, 'parcels'), sources_live: latest.filter((r) => r.status === 'success').length,
        sources_total: SOURCE_CATALOG.length, last_pull: finished.at(-1) ?? null, signals_this_week: count(signals, 'signals'), is_sample: sample,
      };
    },

    async getConfig(): Promise<ClientConfig> { return loadClientConfig(); },

    async getSources(): Promise<SourceCard[]> {
      const rows = must(await db.from('source_latest').select('*'), 'sources') as Row[];
      const by = new Map(rows.map((r) => [r.source_key, r]));
      const cfg = loadClientConfig();
      return SOURCE_CATALOG.map((c): SourceCard => {
        if (c.key === 'owner_data') {
          const mode = cfg.owner_data_provider;
          if (mode !== 'attom') {
            return { key: c.key, label: c.label, description: c.description, state: 'sample', last_run: null, rows_fetched: null, rows_matched: null,
              note: mode === 'hybrid' ? 'ATTOM for prioritized parcels; labeled sample data for the rest.' : 'Sample records are in use until the owner data provider is connected (Phase 6).' };
          }
          return { key: c.key, label: c.label, description: c.description, state: 'live', last_run: null, rows_fetched: null, rows_matched: null, note: null };
        }
        const r = by.get(c.key);
        if (!r) return { key: c.key, label: c.label, description: c.description, state: 'not_connected', last_run: null, rows_fetched: null, rows_matched: null, note: 'Not connected yet.' };
        const waiting = r.status === 'failed' && FRIENDLY_NOT_CONNECTED.test(String(r.error_message ?? ''));
        const state = waiting ? 'not_connected' : r.status === 'success' ? 'live' : r.status === 'running' ? 'running' : 'failed';
        return {
          key: c.key, label: c.label, description: c.description, state, last_run: r.finished_at ?? r.started_at,
          rows_fetched: r.rows_fetched, rows_matched: r.rows_matched,
          note: waiting ? 'Waiting for the file to be added.' : state === 'failed' ? 'The last update did not finish. It will be retried on the next run.' : null,
        };
      });
    },

    async getTeam(): Promise<TeamMember[]> {
      return must(await db.from('team_members').select('id,email,name,role,created_at').order('role').order('email'), 'team') as TeamMember[];
    },

    async getOutreach(tab, page = 1, pageSize = 25): Promise<OutreachPage> {
      let q = db.from('outreach_queue').select('*', { count: 'exact' });
      if (tab === 'call_tasks') q = q.eq('channel', 'call_task').in('status', ['draft', 'awaiting_approval', 'approved']);
      else q = q.neq('channel', 'call_task').eq('status', tab === 'drafts' ? 'draft' : tab);
      if (hood) q = q.eq('neighborhood', hood);
      const [res, counts] = await Promise.all([
        q.order('score', { ascending: false, nullsFirst: false }).order('created_at', { ascending: false }).range((page - 1) * pageSize, page * pageSize - 1),
        navCounts(),
      ]);
      const rows = must(res, 'outreach') as Row[];
      if (rows.some((r) => r.uses_sample_data)) mark();
      return { tab, items: rows.map(toOutreachItem), total: count(res, 'outreach'), page, pageSize, counts };
    },

    async getRecipes(): Promise<RecipeCard[]> {
      const cfg = loadClientConfig();
      const [sum, top, sample] = await Promise.all([db.rpc('recipe_summary', { p_hood: hood }), db.rpc('recipe_top_leads', { p_hood: hood, p_n: 5 }), anySample()]);
      const by = new Map((must(sum, 'recipe_summary') as Row[]).map((r) => [r.recipe, r]));
      const tops = (must(top, 'recipe_top_leads') as Row[]);
      if (sample) mark();
      const comps = await componentsByApn([...new Set(tops.map((t) => String(t.apn)))]);
      return cfg.recipes.map((r): RecipeCard => {
        const s = by.get(r.key);
        const parcels = num(s?.parcels);
        return {
          key: r.key, name: r.name, description: r.description, enabled: r.enabled, parcels, new_this_week: num(s?.new_this_week), strong: num(s?.strong),
          top: tops.filter((t) => t.recipe === r.key).sort((a, b) => a.rank - b.rank).map((t) => ({ apn: t.apn, score: t.score, situs_address: titleAddress(t.situs_address) || null, neighborhood: t.neighborhood, top_signal: recipeSignalLine(r.key, comps.get(String(t.apn))) })),
          idle_reason: parcels > 0 ? null : idleReason(r.key, r.enabled, r.requires_data ?? []),
          is_sample: sample,
        };
      });
    },

    async getOffMarket(filters = {}, page = 1, pageSize = 25): Promise<OffMarketPage> {
      const [inv, links] = await Promise.all([
        db.rpc('off_market_inventory', { p_hood: hood, p_kind: filters.kind ?? null, p_sort: filters.sort ?? 'lot', p_limit: pageSize, p_offset: (page - 1) * pageSize }),
        (() => { let q = db.from('share_links_active').select('*').order('created_at', { ascending: false }).limit(50); if (hood) q = q.eq('neighborhood', hood); return q; })(),
      ]);
      const rows = must(inv, 'off_market_inventory') as Row[];
      const lines = await topSignalLines(rows.map((r) => String(r.apn)));
      const portfolioBy = await portfolios(rows.map((r) => String(r.apn)));
      return {
        total: num(rows[0]?.total), page, pageSize,
        items: rows.map((r) => ({
          apn: r.apn, situs_address: titleAddress(r.situs_address) || null, neighborhood: r.neighborhood, lot_sqft: r.lot_sqft != null ? Number(r.lot_sqft) : null,
          zoning: r.zoning, year_built: r.year_built, land_use: r.land_use, kinds: r.kinds ?? [], upzoning: r.upzoning_estimates ?? [], has_share_link: !!r.has_share_link, top_signal: lines.get(String(r.apn)) ?? null,
          portfolio: portfolioBy.get(String(r.apn)) ?? null,
        })),
        links: (must(links, 'share links') as Row[]).map((l) => ({ token: l.token, apn: l.apn, situs_address: titleAddress(l.situs_address) || null, neighborhood: l.neighborhood, created_by: l.created_by, created_at: l.created_at })),
      };
    },

    async searchLeads(q): Promise<SearchHit[]> {
      if (q.trim().length < 2) return [];
      const rows = must(await db.rpc('search_leads', { p_q: q.slice(0, 80), p_hood: hood, p_limit: 8 }), 'search_leads') as Row[];
      return rows.map((r) => ({ apn: r.apn, situs_address: titleAddress(r.situs_address) || null, neighborhood: r.neighborhood, score: r.score }));
    },
  };
  return provider;
}

/** Why a recipe has no matches, in plain words. */
function idleReason(key: string, enabled: boolean, requires: string[]): string {
  if (!enabled) return key === 'quiet_inheritance' ? 'Needs ATTOM recorder data' : 'Switched off for this team';
  if (requires.includes('fire_zones')) return 'Needs the fire hazard zone file';
  if (key === 'str_exit') return 'Needs a second weekly license snapshot';
  return 'No matching properties yet';
}

/** The public share page reads through a SECURITY DEFINER function that returns property facts only. */
export function supabaseShareReader(anon: SupabaseClient): SharePageReader {
  return {
    async getSharePage(token): Promise<SharePage | null> {
      if (!/^[A-Za-z0-9_-]{8,128}$/.test(token)) return null;
      const rows = must(await anon.rpc('share_page', { p_token: token }), 'share_page') as Row[];
      const r = rows[0];
      if (!r) return null;
      const phone = loadClientConfig().team_members.find((m) => m.email === String(r.agent_email ?? '').toLowerCase())?.phone ?? null;
      return {
        neighborhood: r.neighborhood, lot_sqft: r.lot_sqft, zoning: r.zoning, year_built: r.year_built,
        upzoning_estimates: r.upzoning_estimates ?? [], agent_name: r.agent_name, agent_email: r.agent_email, agent_phone: phone || null,
      };
    },
  };
}
