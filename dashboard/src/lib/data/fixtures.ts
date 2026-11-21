import raw from '../../data/fixtures.json';
import { leadHeadline, recipeSignalLine } from '../present';
import { loadClientConfig } from '../config';
import { EVENT_TYPES, RECIPE_LABELS, SENSITIVE_TYPES, SOURCE_CATALOG, STAGES, TRAIT_TYPES, bandOf } from './catalog';
import type { DataProvider, MarkSample, SharePageReader } from './provider';
import { buildTrends, leadStatus, scoreItems, yearsSince } from './shared';
import type {
  Backtest, FixtureBundle, FunnelRow, LeadDetail, LeadFilters, LeadPage, LeadSummary, MapData, NavCounts, OffMarketPage, OutreachItem,
  OutreachTab, Performance, Pipeline, RecipeCard, SearchHit, Signal, SharePage, SignalEvent, SourceCard, StageEvent, StageValue, StatSeries, TodayFeed,
} from './types';

const db = raw as unknown as FixtureBundle;
const NOW = new Date(`${db.generated_for}T12:00:00Z`);
const DAY = 86_400_000;

const parcelBy = new Map(db.parcels.map((p) => [p.apn, p]));
const scoreBy = new Map(db.scores.map((s) => [s.apn, s]));
const ownerBy = new Map(db.owners.map((o) => [o.apn, o]));
const signalsBy = new Map<string, Signal[]>();
for (const s of db.signals) (signalsBy.get(s.apn) ?? signalsBy.set(s.apn, []).get(s.apn)!).push(s);
const suppressed = new Set(db.suppressions.map((s) => s.apn));

function summary(apn: string): LeadSummary {
  const sigs = [...(signalsBy.get(apn) ?? [])].sort((a, b) => (b.signal_date ?? '').localeCompare(a.signal_date ?? ''));
  const o = ownerBy.get(apn) ?? null; const sc = scoreBy.get(apn)!; const p = parcelBy.get(apn)!;
  return {
    parcel: { apn, situs_address: p.situs_address, neighborhood: p.neighborhood },
    score: { score: sc.score, reason_text: sc.reason_text, recipe_matches: sc.recipe_matches ?? [], primary_recipe: sc.primary_recipe, model_version: sc.model_version, scored_at: sc.scored_at, uses_sample_data: sc.uses_sample_data },
    owner: o ? { owner_name: o.owner_name, is_sample: o.is_sample, last_sale_date: o.last_sale_date, est_equity: o.est_equity, est_value: o.est_value ?? null, absentee: o.absentee, out_of_state: o.out_of_state } : null,
    years_owned: yearsSince(o?.last_sale_date, NOW),
    lot_sqft: p.lot_sqft, zoning: p.zoning,
    latest_signal_date: sigs.find((s) => (EVENT_TYPES as readonly string[]).includes(s.signal_type) && s.signal_group !== 'other')?.signal_date ?? null,
    top_components: (sc.components ?? []).filter((c) => c.kind === 'signal').sort((a, b) => b.contribution - a.contribution).slice(0, 3)
      .map((c) => ({ key: c.key, facts: (c.facts ?? null) as Record<string, unknown> | null, points: c.contribution, signal_date: ((c as unknown as { signal_date?: string }).signal_date ?? null), is_sample: c.is_sample, is_estimate: c.is_estimate })),
    status: leadStatus(db.outreach.filter((x) => x.apn === apn)),
    is_sample: sc.uses_sample_data || !!o?.is_sample,
  };
}

let TERRITORY: string | null = null;
function matches(apn: string, f: LeadFilters): boolean {
  const p = parcelBy.get(apn)!; const sc = scoreBy.get(apn)!;
  if (TERRITORY && p.neighborhood !== TERRITORY) return false;
  if (f.status && leadStatus(db.outreach.filter((x) => x.apn === apn)) !== f.status) return false;
  if (f.isNew && !(summary(apn).latest_signal_date && NOW.getTime() - new Date(summary(apn).latest_signal_date!).getTime() <= 7 * DAY)) return false;
  if (suppressed.has(apn)) return false;
  if (f.neighborhood && p.neighborhood !== f.neighborhood) return false;
  if (f.recipe && !(sc.recipe_matches ?? []).includes(f.recipe)) return false;
  if (f.signalGroup && !(signalsBy.get(apn) ?? []).some((s) => s.signal_group === f.signalGroup)) return false;
  if (f.minScore !== undefined && sc.score < f.minScore) return false;
  if (f.maxScore !== undefined && sc.score > f.maxScore) return false;
  if (f.search && !`${p.situs_address} ${p.apn}`.toLowerCase().includes(f.search.toLowerCase())) return false;
  return true;
}
const ranked = (f: LeadFilters) =>
  db.parcels.map((p) => p.apn).filter((a) => matches(a, f)).sort((a, b) => scoreBy.get(b)!.score - scoreBy.get(a)!.score || a.localeCompare(b));

function coverage() {
  const latest = new Map<string, (typeof db.source_runs)[number]>();
  for (const r of db.source_runs) { const c = latest.get(r.source_key); if (!c || r.started_at > c.started_at) latest.set(r.source_key, r); }
  const finished = [...latest.values()].filter((r) => r.status === 'success').map((r) => r.finished_at).filter((x): x is string => !!x).sort();
  return {
    parcels_monitored: db.parcels.length, sources_live: [...latest.values()].filter((r) => r.status === 'success').length, sources_total: latest.size,
    last_pull: finished.at(-1) ?? null,
    signals_this_week: db.signals.filter((s) => NOW.getTime() - new Date(s.detected_at).getTime() <= 7 * DAY).length, is_sample: true,
  };
}

const FUNNEL = ['signal', 'contacted', 'conversation', 'appointment', 'listing'] as const;
function funnel(label: string, events: StageEvent[]): FunnelRow {
  return { label, stages: FUNNEL.map((key) => ({ key, label: STAGES.find((s) => s.key === key)!.label, count: new Set(events.filter((e) => e.stage === key).map((e) => e.apn)).size })) };
}

const toItem = (o: (typeof db.outreach)[number]): OutreachItem => ({
  id: o.id, apn: o.apn, channel: o.channel, status: o.status, recipe: o.recipe, content: o.content, blocked_reason: o.blocked_reason,
  blocked: (o.blocked_reason ?? '').split(';').map((x) => x.trim()).filter(Boolean), uses_sample_data: o.uses_sample_data,
  situs_address: parcelBy.get(o.apn)?.situs_address ?? null, neighborhood: parcelBy.get(o.apn)?.neighborhood ?? null, score: scoreBy.get(o.apn)?.score ?? null,
  assigned_name: db.team_members.find((t) => t.email === o.assigned_to)?.name ?? null, created_at: o.created_at, due_date: null, approved_by: o.approved_by,
});

export function fixturesProvider(mark: MarkSample, territory: string | null = null): DataProvider {
  mark(); // every record in the fixture bundle is sample data
  TERRITORY = territory;
  const inHood = (apn: string) => !territory || parcelBy.get(apn)?.neighborhood === territory;
  const counts = (): NavCounts => {
    const o = db.outreach.filter((x) => inHood(x.apn));
    const n = (st: string) => o.filter((x) => x.channel !== 'call_task' && x.status === st).length;
    return { leads: ranked({ minScore: 30 }).length, drafts: n('draft'), awaiting_approval: n('awaiting_approval'), approved: n('approved'),
      call_tasks: o.filter((x) => x.channel === 'call_task').length, off_market: ranked({}).filter((a) => (scoreBy.get(a)!.recipe_matches ?? []).some((r) => r === 'builder_bait' || r === 'tired_landlord')).length };
  };
  const flat = (): StatSeries[] => (['signals', 'active_leads', 'drafts', 'outcomes'] as const).map((metric) => ({ metric, days: [], this_week: 0, last_week: 0 }));
  const provider: DataProvider = {
    name: 'fixtures',
    territory,
    async getNavCounts() { return counts(); },
    async getLeads(filters = {}, page = 1, pageSize = 25): Promise<LeadPage> {
      const all = ranked(filters);
      return { items: all.slice((page - 1) * pageSize, page * pageSize).map(summary), total: all.length, page, pageSize };
    },
    async getTodayFeed(): Promise<TodayFeed> {
      const cfg = loadClientConfig();
      const rec = await provider.getRecipes();
      const waiting = db.outreach.filter((o) => o.status === 'awaiting_approval' && o.channel !== 'call_task' && inHood(o.apn));
      const calls = db.outreach.filter((o) => o.channel === 'call_task' && inHood(o.apn));
      const events: SignalEvent[] = db.signals.filter((s) => (EVENT_TYPES as readonly string[]).includes(s.signal_type) && s.signal_group !== 'other' && s.signal_date && inHood(s.apn))
        .sort((a, b) => b.signal_date!.localeCompare(a.signal_date!)).slice(0, 5).map((s) => ({
          apn: s.apn, situs_address: parcelBy.get(s.apn)?.situs_address ?? null, neighborhood: parcelBy.get(s.apn)?.neighborhood ?? null, type: s.signal_type, group: s.signal_group,
          date: s.signal_date!, count: 1, is_sample: s.is_sample, is_estimate: s.is_estimate, source_key: s.source_key, source_record_id: s.source_record_id, details: s.details }));
      return {
        as_of: NOW.toISOString(), territory, coverage: coverage(), stats: flat(), leads_total: counts().leads,
        top_leads: (await provider.getLeads({ minScore: 30 }, 1, 8)).items,
        recipe_strip: cfg.recipes.filter((r) => r.enabled).map((r) => { const c = rec.find((x) => x.key === r.key)!; return { key: r.key, label: r.name, parcels: c.parcels, new_this_week: c.new_this_week }; }),
        approvals: waiting.slice(0, 5).map(toItem), approvals_total: waiting.length, call_tasks: calls.slice(0, 5).map(toItem), call_tasks_total: calls.length,
        new_signals: events, new_signals_total: events.length, weekly: null,
      };
    },
    async getLead(apn): Promise<LeadDetail | null> {
      const p = parcelBy.get(apn); const sc = scoreBy.get(apn);
      if (!p || !sc) return null;
      const o = ownerBy.get(apn) ?? null; const out = db.outreach.filter((x) => x.apn === apn);
      return {
        parcel: p, score: sc, score_items: scoreItems(sc.components), owner: o, years_owned: yearsSince(o?.last_sale_date, NOW),
        sales: db.sales_history.filter((s) => s.apn === apn).sort((a, b) => (b.sale_date ?? '').localeCompare(a.sale_date ?? '')),
        signals: [...(signalsBy.get(apn) ?? [])].filter((s) => (EVENT_TYPES as readonly string[]).includes(s.signal_type) && s.signal_group !== 'other').sort((a, b) => (b.signal_date ?? '').localeCompare(a.signal_date ?? '')).slice(0, 80),
        signal_total: (signalsBy.get(apn) ?? []).filter((s) => (EVENT_TYPES as readonly string[]).includes(s.signal_type) && s.signal_group !== 'other').length,
        sensitive_signals: (signalsBy.get(apn) ?? []).filter((s) => (SENSITIVE_TYPES as readonly string[]).includes(s.signal_type)),
        trait_signals: (signalsBy.get(apn) ?? []).filter((s) => (TRAIT_TYPES as readonly string[]).includes(s.signal_type)),
        outreach: out, stage_events: db.stage_events.filter((e) => e.apn === apn).sort((a, b) => b.occurred_at.localeCompare(a.occurred_at)),
        share_links: db.share_links.filter((l) => l.apn === apn && !l.revoked_at), status: leadStatus(out), is_sample: true, ai_brief: null,
      };
    },
    async getMapData(filters = {}): Promise<MapData> {
      return {
        is_sample: true,
        points: ranked(filters).map((apn) => {
          const p = parcelBy.get(apn)!; const sc = scoreBy.get(apn)!; const [lng, lat] = p.centroid!.coordinates as [number, number];
          return { apn, score: sc.score, band: bandOf(sc.score), recipe: sc.primary_recipe, neighborhood: p.neighborhood ?? '', lng, lat };
        }),
      };
    },
    async getTrends(area) {
      const cfg = loadClientConfig();
      const hoods = area === 'All' || !cfg.territory.neighborhoods.includes(area) ? cfg.territory.neighborhoods : [area];
      return buildTrends(area === 'All' ? 'All' : area, hoods, NOW, db.trend_rows);
    },
    async getPipeline(): Promise<Pipeline> {
      const events = db.stage_events.filter((e) => inHood(e.apn));
      const stage_values: StageValue[] = FUNNEL.map((key) => {
        const apns = [...new Set(events.filter((e) => e.stage === key).map((e) => e.apn))];
        const owners = apns.map((a) => ownerBy.get(a)).filter((o) => o?.est_value != null);
        return { key, parcels: apns.length, valued_parcels: owners.length, est_value: owners.reduce((t, o) => t + Number(o!.est_value), 0), sample_parcels: owners.filter((o) => o!.is_sample).length };
      });
      return { overall: funnel('All leads', events), stage_values, has_events: events.length > 0, is_sample: true, by_recipe: [], by_agent: [],
        recent: events.filter((e) => e.source === 'dashboard').slice(0, 10).map((e) => ({ apn: e.apn, situs_address: parcelBy.get(e.apn)?.situs_address ?? null, neighborhood: parcelBy.get(e.apn)?.neighborhood ?? null, stage: e.stage, by: e.team_member_email, note: e.note, occurred_at: e.occurred_at })) };
    },
    async getAiStatus(): Promise<null> { return null; },
    async getBriefings() { return []; },
    async getPerformance(): Promise<Performance> {
      const events = db.stage_events.filter((e) => inHood(e.apn));
      const recipeOf = (apn: string) => scoreBy.get(apn)?.primary_recipe ?? null;
      const recipes = [...new Set(events.map((e) => recipeOf(e.apn)).filter((r): r is string => !!r))];
      const emails = [...new Set(events.map((e) => e.team_member_email ?? 'unassigned'))];
      return {
        overall: funnel('All leads', events), has_events: events.length > 0, is_sample: true, backtest: await provider.getBacktest(),
        by_recipe: recipes.map((r) => funnel(RECIPE_LABELS[r] ?? r, events.filter((e) => recipeOf(e.apn) === r))),
        by_agent: emails.map((m) => funnel(db.team_members.find((t) => t.email === m)?.name ?? 'Unassigned', events.filter((e) => (e.team_member_email ?? 'unassigned') === m))),
        coverage: [],
      };
    },
    async getBacktest(): Promise<Backtest> {
      const b = db.backtest;
      return { ...b, share_flagged: b.past_sales_considered ? b.flagged_before_listing / b.past_sales_considered : 0 };
    },
    async getCoverage() { return coverage(); },
    async getConfig() { return loadClientConfig(); },
    async getSources(): Promise<SourceCard[]> {
      return SOURCE_CATALOG.map((c) => ({ key: c.key, label: c.label, description: c.description, state: 'sample' as const, last_run: null, rows_fetched: null, rows_matched: null, note: 'Sample data.' }));
    },
    async getTeam() { return db.team_members; },
    async getOutreach(tab: OutreachTab, page = 1, pageSize = 25) {
      const rows = db.outreach.filter((o) => inHood(o.apn) && (tab === 'call_tasks' ? o.channel === 'call_task' : o.channel !== 'call_task' && o.status === (tab === 'drafts' ? 'draft' : tab)));
      return { tab, items: rows.slice((page - 1) * pageSize, page * pageSize).map(toItem), total: rows.length, page, pageSize, counts: counts() };
    },
    async getRecipes(): Promise<RecipeCard[]> {
      return loadClientConfig().recipes.map((r) => {
        const apns = ranked({}).filter((a) => (scoreBy.get(a)!.recipe_matches ?? []).includes(r.key));
        return { key: r.key, name: r.name, description: r.description, enabled: r.enabled, parcels: apns.length, new_this_week: 0, strong: apns.filter((a) => scoreBy.get(a)!.score >= 60).length,
          top: apns.slice(0, 5).map((a) => ({ apn: a, score: scoreBy.get(a)!.score, situs_address: parcelBy.get(a)!.situs_address, neighborhood: parcelBy.get(a)!.neighborhood, top_signal: recipeSignalLine(r.key, scoreBy.get(a)!.components) })),
          idle_reason: apns.length ? null : 'No matching properties yet', is_sample: true };
      });
    },
    async getOffMarket(filters = {}, page = 1, pageSize = 25): Promise<OffMarketPage> {
      const kinds = filters.kind ? [filters.kind] : ['builder_bait', 'tired_landlord'];
      const apns = ranked({}).filter((a) => (scoreBy.get(a)!.recipe_matches ?? []).some((r) => kinds.includes(r)));
      return { total: apns.length, page, pageSize, links: [], items: apns.slice((page - 1) * pageSize, page * pageSize).map((a) => { const p = parcelBy.get(a)!;
        return { apn: a, situs_address: p.situs_address, neighborhood: p.neighborhood, lot_sqft: p.lot_sqft, zoning: p.zoning, year_built: p.year_built, land_use: p.land_use,
          kinds: (scoreBy.get(a)!.recipe_matches ?? []).filter((r) => kinds.includes(r)), upzoning: (signalsBy.get(a) ?? []).filter((s) => s.is_estimate).map((s) => s.signal_type), has_share_link: db.share_links.some((l) => l.apn === a && !l.revoked_at), top_signal: leadHeadline(summary(a)) }; }) };
    },
    async searchLeads(q): Promise<SearchHit[]> {
      const t = q.trim().toLowerCase(); if (t.length < 2) return [];
      return ranked({ search: t }).slice(0, 8).map((a) => ({ apn: a, situs_address: parcelBy.get(a)!.situs_address, neighborhood: parcelBy.get(a)!.neighborhood, score: scoreBy.get(a)!.score }));
    },
  };
  return provider;
}

export const fixturesShareReader: SharePageReader = {
  async getSharePage(token): Promise<SharePage | null> {
    const l = db.share_links.find((x) => x.token === token && !x.revoked_at);
    const p = l && parcelBy.get(l.apn);
    if (!l || !p) return null;
    const up = (signalsBy.get(l.apn) ?? []).filter((s) => s.is_estimate).map((s) => s.signal_type);
    return { neighborhood: p.neighborhood, lot_sqft: p.lot_sqft, zoning: p.zoning, year_built: p.year_built, upzoning_estimates: [...new Set(up)], agent_name: null, agent_email: l.created_by, agent_phone: null };
  },
};
