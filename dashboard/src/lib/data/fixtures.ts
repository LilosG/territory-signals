import raw from '../../data/fixtures.json';
import { loadClientConfig } from '../config';
import { RECIPE_LABELS, SOURCE_LABEL, STAGES, bandOf } from './catalog';
import type { DataProvider, MarkSample, SharePageReader } from './provider';
import { buildTrends, leadStatus, scoreItems, yearsSince } from './shared';
import type {
  Backtest, FixtureBundle, FunnelRow, LeadDetail, LeadFilters, LeadPage, LeadSummary, MapData, Pipeline, Signal, SharePage, StageEvent,
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
    owner: o ? { owner_name: o.owner_name, is_sample: o.is_sample, last_sale_date: o.last_sale_date, est_equity: o.est_equity } : null,
    years_owned: yearsSince(o?.last_sale_date, NOW),
    signal_count: sigs.length, top_signal_types: [...new Set(sigs.map((s) => s.signal_type))],
    latest_signal_date: sigs[0]?.signal_date ?? null,
    status: leadStatus(db.outreach.filter((x) => x.apn === apn)),
    is_sample: sc.uses_sample_data || !!o?.is_sample,
  };
}

function matches(apn: string, f: LeadFilters): boolean {
  const p = parcelBy.get(apn)!; const sc = scoreBy.get(apn)!;
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

export function fixturesProvider(mark: MarkSample): DataProvider {
  mark(); // every record in the fixture bundle is sample data
  const provider: DataProvider = {
    name: 'fixtures',
    async getLeads(filters = {}, page = 1, pageSize = 25): Promise<LeadPage> {
      const all = ranked(filters);
      return { items: all.slice((page - 1) * pageSize, page * pageSize).map(summary), total: all.length, page, pageSize };
    },
    async getTodayFeed() {
      const since = NOW.getTime() - DAY * 1.5;
      const fresh = db.signals.filter((s) => new Date(s.detected_at).getTime() >= since).sort((a, b) => b.detected_at.localeCompare(a.detected_at));
      const addr = (apn: string) => parcelBy.get(apn);
      const waiting = db.outreach.filter((o) => o.status === 'awaiting_approval');
      return {
        as_of: NOW.toISOString(), coverage: coverage(), top_leads: (await provider.getLeads({}, 1, 10)).items,
        new_signals: fresh.slice(0, 8).map((s) => ({ ...s, situs_address: addr(s.apn)?.situs_address ?? null, neighborhood: addr(s.apn)?.neighborhood ?? null })), new_signals_total: fresh.length,
        approvals_waiting: waiting.slice(0, 7).map((o) => ({ ...o, situs_address: addr(o.apn)?.situs_address ?? null })), approvals_total: waiting.length,
        call_tasks_due: db.outreach.filter((o) => o.channel === 'call_task' && o.status === 'approved' && !o.sent_at).slice(0, 10).map((o) => ({
          ...o, situs_address: addr(o.apn)?.situs_address ?? null, score: scoreBy.get(o.apn)?.score ?? null, reason_text: scoreBy.get(o.apn)?.reason_text ?? null,
          assigned_agent: db.team_members.find((t) => t.email === o.assigned_to)?.name ?? null,
        })),
      };
    },
    async getLead(apn): Promise<LeadDetail | null> {
      const p = parcelBy.get(apn); const sc = scoreBy.get(apn);
      if (!p || !sc) return null;
      const o = ownerBy.get(apn) ?? null; const out = db.outreach.filter((x) => x.apn === apn);
      return {
        parcel: p, score: sc, score_items: scoreItems(sc.components), owner: o, years_owned: yearsSince(o?.last_sale_date, NOW),
        sales: db.sales_history.filter((s) => s.apn === apn).sort((a, b) => (b.sale_date ?? '').localeCompare(a.sale_date ?? '')),
        signals: [...(signalsBy.get(apn) ?? [])].sort((a, b) => (b.signal_date ?? '').localeCompare(a.signal_date ?? '')).slice(0, 25),
        signal_total: (signalsBy.get(apn) ?? []).length,
        outreach: out, stage_events: db.stage_events.filter((e) => e.apn === apn).sort((a, b) => b.occurred_at.localeCompare(a.occurred_at)),
        share_links: db.share_links.filter((l) => l.apn === apn && !l.revoked_at), status: leadStatus(out), is_sample: true,
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
      const events = db.stage_events;
      const recipeOf = (apn: string) => scoreBy.get(apn)?.primary_recipe ?? null;
      const recipes = [...new Set(events.map((e) => recipeOf(e.apn)).filter((r): r is string => !!r))];
      const emails = [...new Set(events.map((e) => e.team_member_email ?? 'unassigned'))];
      return {
        overall: funnel('All leads', events), has_events: events.length > 0, is_sample: true,
        by_recipe: recipes.map((r) => funnel(RECIPE_LABELS[r] ?? r, events.filter((e) => recipeOf(e.apn) === r))),
        by_agent: emails.map((m) => funnel(db.team_members.find((t) => t.email === m)?.name ?? 'Unassigned', events.filter((e) => (e.team_member_email ?? 'unassigned') === m))),
      };
    },
    async getBacktest(): Promise<Backtest> {
      const b = db.backtest;
      return { ...b, share_flagged: b.past_sales_considered ? b.flagged_before_listing / b.past_sales_considered : 0 };
    },
    async getCoverage() { return coverage(); },
    async getConfig() { return loadClientConfig(); },
    async getSources() {
      const latest = new Map<string, (typeof db.source_runs)[number]>();
      for (const r of db.source_runs) { const c = latest.get(r.source_key); if (!c || r.started_at > c.started_at) latest.set(r.source_key, r); }
      return [...latest.values()].map((r) => ({ source_key: r.source_key, label: SOURCE_LABEL(r.source_key), last_run: r, status: r.status })).sort((a, b) => a.label.localeCompare(b.label));
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
