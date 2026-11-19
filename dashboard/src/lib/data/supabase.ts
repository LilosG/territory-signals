import { titleAddress } from '../format';
import type { SupabaseClient } from '@supabase/supabase-js';
import { loadClientConfig } from '../config';
import { RECIPE_LABELS, SOURCE_LABEL, STAGES, bandOf } from './catalog';
import type { DataProvider, MarkSample, SharePageReader } from './provider';
import { buildTrends, leadStatus, scoreItems, yearsSince, type TrendRows } from './shared';
import type {
  Backtest, ClientConfig, Coverage, CoverageSource, FeedSignal, FunnelRow, LeadDetail, LeadFilters, LeadPage, LeadSummary,
  MapData, Outreach, Pipeline, SharePage, SourceRun, TodayFeed, Trends,
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

// Whether any displayed score is sample data. Cached briefly so every page does not pay for it.
let sampleCache: { at: number; value: boolean } | null = null;

/** Parcel columns without the polygon geometry (the dashboard never needs it). */
const PARCEL_COLS = 'apn,situs_address,zip,planning_area,neighborhood,centroid,lot_sqft,land_use,zoning,year_built,last_recorded_doc_date,source_key,created_at,updated_at';

function toLead(r: Row, now: Date): LeadSummary {
  return {
    parcel: { apn: r.apn, situs_address: titleAddress(r.situs_address) || null, neighborhood: r.neighborhood },
    score: { score: r.score, reason_text: r.reason_text, recipe_matches: r.recipe_matches ?? [], primary_recipe: r.primary_recipe, model_version: r.model_version, scored_at: r.scored_at, uses_sample_data: r.uses_sample_data },
    owner: r.owner_name !== null || r.owner_as_of ? { owner_name: r.owner_name, is_sample: !!r.owner_is_sample, last_sale_date: r.last_sale_date, est_equity: r.est_equity } : null,
    years_owned: yearsSince(r.last_sale_date, now),
    signal_count: Number(r.signal_count ?? 0),
    top_signal_types: r.signal_types ?? [],
    latest_signal_date: r.latest_signal_date,
    status: r.outreach_status === 'draft' ? 'draft_ready' : (r.outreach_status ?? 'new'),
    is_sample: !!r.uses_sample_data || !!r.owner_is_sample,
  };
}

const rpcArgs = (f: LeadFilters = {}) => ({
  p_recipe: f.recipe || null, p_group: f.signalGroup || null, p_hood: f.neighborhood || null,
  p_min: f.minScore ?? null, p_max: f.maxScore ?? null, p_search: f.search || null,
});

/** All reads go through `db`, the signed-in user's client, so row level security applies. */
export function supabaseProvider(db: SupabaseClient, mark: MarkSample): DataProvider {
  const now = () => new Date();

  async function anySample(): Promise<boolean> {
    if (sampleCache && Date.now() - sampleCache.at < 60_000) return sampleCache.value;
    const res = await db.from('latest_scores').select('apn').eq('uses_sample_data', true).limit(1);
    const value = (must(res, 'sample check') as Row[]).length > 0;
    sampleCache = { at: Date.now(), value };
    return value;
  }

  async function addresses(apns: string[]): Promise<Map<string, Row>> {
    if (!apns.length) return new Map();
    const rows = must(await db.from('parcels').select('apn,situs_address,neighborhood').in('apn', apns), 'parcels') as Row[];
    return new Map(rows.map((r) => [r.apn, { ...r, situs_address: titleAddress(r.situs_address) || null }]));
  }

  const provider: DataProvider = {
    name: 'supabase',

    async getLeads(filters = {}, page = 1, pageSize = 25) {
      const rows = must(await db.rpc('leads_page', { ...rpcArgs(filters), p_limit: pageSize, p_offset: (page - 1) * pageSize }), 'leads_page') as Row[];
      const t = now();
      const items = rows.map((r) => toLead(r, t));
      if (items.some((l) => l.is_sample)) mark();
      return { items, total: Number(rows[0]?.total ?? 0), page, pageSize } satisfies LeadPage;
    },

    async getTodayFeed(): Promise<TodayFeed> {
      const since = new Date(Date.now() - 36 * 3600_000).toISOString();
      const [coverage, leads, newSig, approvals, calls] = await Promise.all([
        provider.getCoverage(),
        provider.getLeads({}, 1, 10),
        db.from('signals').select('*', { count: 'exact' }).is('superseded_by', null).gte('detected_at', since)
          .order('signal_date', { ascending: false, nullsFirst: false }).limit(8),
        db.from('outreach').select('*', { count: 'exact' }).eq('status', 'awaiting_approval').order('created_at', { ascending: false }).limit(7),
        db.from('outreach').select('*').eq('channel', 'call_task').eq('status', 'approved').is('sent_at', null).limit(10),
      ]);
      const sigRows = must(newSig, 'new signals') as Row[];
      const apRows = must(approvals, 'approvals') as Row[];
      const callRows = must(calls, 'call tasks') as Row[];
      const apns = [...new Set([...sigRows, ...apRows, ...callRows].map((r) => r.apn))];
      const [addr, scoreRows, team] = await Promise.all([
        addresses(apns),
        callRows.length ? db.from('latest_scores').select('apn,score,reason_text').in('apn', callRows.map((r) => r.apn)) : Promise.resolve({ data: [], error: null }),
        db.from('team_members').select('email,name'),
      ]);
      const scoreBy = new Map((must(scoreRows as any, 'scores') as Row[]).map((r) => [r.apn, r]));
      const names = new Map((must(team, 'team') as Row[]).map((r) => [String(r.email).toLowerCase(), r.name]));
      if (apRows.some((r) => r.uses_sample_data) || callRows.some((r) => r.uses_sample_data)) mark();
      return {
        as_of: new Date().toISOString(),
        coverage,
        top_leads: leads.items,
        new_signals: sigRows.map((s): FeedSignal => ({ ...(s as FeedSignal), situs_address: addr.get(s.apn)?.situs_address ?? null, neighborhood: addr.get(s.apn)?.neighborhood ?? null })),
        new_signals_total: count(newSig, 'new signals'),
        approvals_waiting: apRows.map((o) => ({ ...(o as Outreach), situs_address: addr.get(o.apn)?.situs_address ?? null })),
        approvals_total: count(approvals, 'approvals'),
        call_tasks_due: callRows.map((o) => ({
          ...(o as Outreach), situs_address: addr.get(o.apn)?.situs_address ?? null,
          score: scoreBy.get(o.apn)?.score ?? null, reason_text: scoreBy.get(o.apn)?.reason_text ?? null,
          assigned_agent: o.assigned_to ? (names.get(String(o.assigned_to).toLowerCase()) ?? o.assigned_to) : null,
        })),
      };
    },

    async getLead(apn): Promise<LeadDetail | null> {
      const [parcel, score, owner, sales, signals, outreach, events, links] = await Promise.all([
        db.from('parcels').select(PARCEL_COLS).eq('apn', apn).maybeSingle(),
        db.from('latest_scores').select('*').eq('apn', apn).maybeSingle(),
        db.from('latest_owners').select('*').eq('apn', apn).maybeSingle(),
        db.from('sales_history').select('*').eq('apn', apn).order('sale_date', { ascending: false }).limit(25),
        db.from('signals').select('*', { count: 'exact' }).eq('apn', apn).is('superseded_by', null).order('signal_date', { ascending: false, nullsFirst: false }).limit(25),
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
      const isSample = !!sc.uses_sample_data || !!o?.is_sample || sl.some((s) => s.is_sample);
      if (isSample) mark();
      return {
        parcel: { ...p, situs_address: titleAddress(p.situs_address) || null, geom: null, centroid: p.centroid ?? null } as LeadDetail['parcel'],
        score: sc as LeadDetail['score'],
        score_items: scoreItems(sc.components),
        owner: o as LeadDetail['owner'],
        years_owned: yearsSince(o?.last_sale_date, now()),
        sales: sl as LeadDetail['sales'],
        signals: must(signals, 'signals') as LeadDetail['signals'],
        signal_total: count(signals, 'signals'),
        outreach: out,
        stage_events: must(events, 'stage events') as LeadDetail['stage_events'],
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
      const [rec, agent, overall, team] = await Promise.all([
        db.from('funnel_by_recipe').select('*'), db.from('funnel_by_agent').select('*'),
        db.from('funnel_overall').select('*').maybeSingle(), db.from('team_members').select('email,name'),
      ]);
      const names = new Map((must(team, 'team') as Row[]).map((r) => [String(r.email).toLowerCase(), r.name]));
      const row = (label: string, r: Row): FunnelRow => ({
        label, stages: STAGES.filter((s) => ['signal', 'contacted', 'conversation', 'appointment', 'listing'].includes(s.key))
          .map((s) => ({ key: s.key as FunnelRow['stages'][number]['key'], label: s.label, count: Number(r?.[s.key] ?? 0) })),
      });
      const o = must(overall, 'funnel_overall') as Row | null;
      const hasEvents = Number(o?.signal ?? 0) > 0;
      if (Number(o?.sample_parcels ?? 0) > 0) mark();
      return {
        overall: row('All leads', o ?? {}), has_events: hasEvents, is_sample: Number(o?.sample_parcels ?? 0) > 0,
        by_recipe: (must(rec, 'funnel_by_recipe') as Row[]).map((r) => row(RECIPE_LABELS[r.recipe] ?? r.recipe, r)).sort((a, b) => b.stages[0]!.count - a.stages[0]!.count),
        by_agent: (must(agent, 'funnel_by_agent') as Row[]).map((r) => row(r.team_member_email === 'unassigned' ? 'Unassigned' : (names.get(String(r.team_member_email).toLowerCase()) ?? r.team_member_email), r)),
      };
    },

    // Real backtests need owner sale history (Phase 6). Never show fixture numbers as live.
    async getBacktest(): Promise<Backtest | null> { return null; },

    async getCoverage(): Promise<Coverage> {
      const since = new Date(Date.now() - 7 * DAY).toISOString();
      const [parcels, signals, runs, sample] = await Promise.all([
        db.from('parcels').select('apn', { count: 'exact', head: true }),
        db.from('signals').select('id', { count: 'exact', head: true }).is('superseded_by', null).gte('detected_at', since),
        db.from('source_runs').select('*').order('started_at', { ascending: false }).limit(500),
        anySample(),
      ]);
      const latest = new Map<string, Row>();
      for (const r of must(runs, 'source_runs') as Row[]) if (!latest.has(r.source_key)) latest.set(r.source_key, r);
      const finished = [...latest.values()].filter((r) => r.status === 'success' && r.finished_at).map((r) => r.finished_at as string).sort();
      return {
        parcels_monitored: count(parcels, 'parcels'), sources_live: [...latest.values()].filter((r) => r.status === 'success').length,
        sources_total: latest.size, last_pull: finished.at(-1) ?? null, signals_this_week: count(signals, 'signals'), is_sample: sample,
      };
    },

    async getConfig(): Promise<ClientConfig> { return loadClientConfig(); },

    async getSources(): Promise<CoverageSource[]> {
      const runs = must(await db.from('source_runs').select('*').order('started_at', { ascending: false }).limit(500), 'source_runs') as SourceRun[];
      const latest = new Map<string, SourceRun>();
      for (const r of runs) if (!latest.has(r.source_key)) latest.set(r.source_key, r);
      return [...latest.values()].map((r) => ({ source_key: r.source_key, label: SOURCE_LABEL(r.source_key), last_run: r, status: r.status }))
        .sort((a, b) => a.label.localeCompare(b.label));
    },
  };
  return provider;
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
