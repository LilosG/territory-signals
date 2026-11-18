import raw from '../../data/fixtures.json';
import { SIGNAL_GROUPS, SIGNAL_TYPES, SOURCES, bandOf } from './catalog';
import type { DataProvider } from './provider';
import type {
  Backtest, FixtureBundle, FunnelRow, FunnelStage, LeadDetail, LeadFilters, LeadStatus, LeadSummary, MapPoint,
  Outcome, Pipeline, Signal, TrendMetric, Trends,
} from './types';

const db = raw as unknown as FixtureBundle;
const TODAY = new Date(`${db.generated_for}T12:00:00Z`).getTime();
const DAY = 86_400_000;

const parcelBy = new Map(db.parcels.map((p) => [p.apn, p]));
const scoreBy = new Map(db.scores.map((s) => [s.apn, s]));
// owners are append-only per as_of: latest wins
const ownerBy = new Map(db.owners.map((o) => [o.apn, o]));
const signalsBy = new Map<string, Signal[]>();
for (const s of db.signals) (signalsBy.get(s.apn) ?? signalsBy.set(s.apn, []).get(s.apn)!).push(s);
const suppressed = new Set(db.suppressions.map((s) => s.apn));

const yearsOwned = (apn: string) => {
  const d = ownerBy.get(apn)?.last_sale_date;
  return d ? Math.round(((TODAY - new Date(d).getTime()) / (365.25 * DAY)) * 10) / 10 : null;
};

const STATUS_RANK: Record<string, number> = { draft: 1, approved: 2, awaiting_approval: 3, sent: 4 };
/** Most advanced outreach state wins; no outreach rows means the lead is new. Call tasks do not count as drafts. */
function leadStatus(apn: string): LeadStatus {
  const rows = db.outreach.filter((o) => o.apn === apn && o.channel !== 'call_task' && o.status in STATUS_RANK);
  const top = rows.sort((a, b) => STATUS_RANK[b.status]! - STATUS_RANK[a.status]!)[0];
  return !top ? 'new' : top.status === 'draft' ? 'draft_ready' : (top.status as LeadStatus);
}

function summary(apn: string): LeadSummary {
  const sigs = [...(signalsBy.get(apn) ?? [])].sort((a, b) => (b.signal_date ?? '').localeCompare(a.signal_date ?? ''));
  const owner = ownerBy.get(apn) ?? null;
  return {
    parcel: parcelBy.get(apn)!, score: scoreBy.get(apn)!, owner,
    signal_count: sigs.length,
    top_signal_types: [...new Set(sigs.map((s) => s.signal_type))],
    status: leadStatus(apn),
    latest_signal_date: sigs[0]?.signal_date ?? null,
    is_sample: !!owner?.is_sample || sigs.some((s) => s.is_sample),
  };
}

function matches(apn: string, f: LeadFilters): boolean {
  const p = parcelBy.get(apn)!; const sc = scoreBy.get(apn)!;
  if (f.neighborhood && p.neighborhood !== f.neighborhood) return false;
  if (f.recipe && !(sc.recipe_matches ?? []).includes(f.recipe)) return false;
  if (f.signalGroup && !(signalsBy.get(apn) ?? []).some((s) => s.signal_group === f.signalGroup)) return false;
  if (f.minScore !== undefined && sc.score < f.minScore) return false;
  if (f.maxScore !== undefined && sc.score > f.maxScore) return false;
  if (f.search) {
    const q = f.search.toLowerCase();
    if (!`${p.situs_address} ${p.apn}`.toLowerCase().includes(q)) return false;
  }
  return true;
}

const leadsSorted = () =>
  db.parcels.map((p) => p.apn).map(summary).sort((a, b) => b.score.score - a.score.score || a.parcel.apn.localeCompare(b.parcel.apn));

function coverage() {
  const latest = new Map<string, (typeof db.source_runs)[number]>();
  for (const r of db.source_runs) {
    const cur = latest.get(r.source_key);
    if (!cur || r.started_at > cur.started_at) latest.set(r.source_key, r);
  }
  const keys = Object.keys(SOURCES);
  const live = [...latest.values()].filter((r) => r.status === 'success').length;
  const finished = db.source_runs.map((r) => r.finished_at).filter((x): x is string => !!x).sort();
  return {
    parcels_monitored: db.parcels.length, sources_live: live, sources_total: keys.length,
    last_pull: finished.at(-1) ?? null,
    signals_this_week: db.signals.filter((s) => TODAY - new Date(s.detected_at).getTime() <= 7 * DAY).length,
    is_sample: true,
  };
}

/* ── funnel ── */
const STAGES: FunnelStage['key'][] = ['signals', 'contacted', 'conversation', 'appointment', 'listing'];
const STAGE_LABEL: Record<FunnelStage['key'], string> = { signals: 'Signals', contacted: 'Contacted', conversation: 'Conversation', appointment: 'Appointment', listing: 'Listing' };
const stageRank: Partial<Record<Outcome['status'], number>> = { contacted: 1, conversation: 2, appointment: 3, listing: 4 };
function funnel(label: string, apns: string[], outcomes: Outcome[]): FunnelRow {
  const reach = new Map<string, number>();
  for (const o of outcomes) { const r = stageRank[o.status]; if (r) reach.set(o.apn, Math.max(reach.get(o.apn) ?? 0, r)); }
  const stages = STAGES.map((key, i): FunnelStage => ({
    key, label: STAGE_LABEL[key],
    count: i === 0 ? apns.length : apns.filter((a) => (reach.get(a) ?? 0) >= i).length,
  }));
  return { label, stages };
}

/* ── trends: deterministic takeaways ── */
const META: Record<TrendMetric['key'], { title: string; unit: string; est?: boolean }> = {
  turnover: { title: 'Turnover', unit: 'sales per month' },
  permits: { title: 'Permits by signal group', unit: 'permits per month' },
  str_lost: { title: 'Short-term rental licenses lost', unit: 'licenses per month' },
  tax_default: { title: 'Tax-default count', unit: 'parcels' },
  upzoning: { title: 'Upzoning-eligible parcels (estimated)', unit: 'parcels', est: true },
  recipes: { title: 'Recipes matched this month', unit: 'parcels' },
};
const MONTHLY_KEYS = ['turnover', 'permits', 'str_lost', 'tax_default'] as const;
const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);
function takeaway(key: TrendMetric['key'], series: { label: string; points: { value: number }[] }[]): string {
  const total = series[0]!.points.map((_, i) => sum(series.map((s) => s.points[i]!.value)));
  const last3 = sum(total.slice(-3)), prev3 = sum(total.slice(-6, -3));
  const pct = prev3 ? Math.round(((last3 - prev3) / prev3) * 100) : 0;
  const dir = pct > 0 ? `up ${pct}%` : pct < 0 ? `down ${Math.abs(pct)}%` : 'flat';
  const lastV = total.at(-1)!, firstV = total[0]!;
  switch (key) {
    case 'turnover': return `Sales over the last 3 months are ${dir} versus the 3 months before (${last3} vs ${prev3}).`;
    case 'permits': {
      const lead = [...series].sort((a, b) => sum(b.points.map((p) => p.value)) - sum(a.points.map((p) => p.value)))[0]!;
      return `${lead.label} is the largest permit group; total permits are ${dir} over the last 3 months.`;
    }
    case 'str_lost': return `${last3} licenses lost in the last 3 months, ${dir} versus the prior 3.`;
    case 'tax_default': return `${lastV} tax-defaulted parcels this month, ${lastV <= firstV ? 'down' : 'up'} from ${firstV} twelve months ago.`;
    default: return '';
  }
}

/** Count distinct parcels per neighborhood that carry a signal matching `pred`. */
const parcelsWith = (hood: string, pred: (s: Signal) => boolean) =>
  new Set(db.signals.filter((s) => parcelBy.get(s.apn)?.neighborhood === hood && pred(s)).map((s) => s.apn)).size;
const dist = (s: Signal) => Number((s.details as { distance_miles?: number } | null)?.distance_miles ?? Infinity);
const grouped = (key: 'upzoning' | 'recipes', hoods: string[], defs: { label: string; count: (h: string) => number }[], takeawayText: string): TrendMetric => ({
  key, title: META[key].title, unit: META[key].unit, is_estimate: !!META[key].est, categories: hoods, takeaway: takeawayText,
  series: defs.map((d) => ({ key: d.label, label: d.label, points: hoods.map((h) => ({ month: h, value: d.count(h) })) })),
});

function upzoningBreakdown(hoods: string[]): TrendMetric {
  const defs = [
    { label: 'SB 9 estimate', count: (h: string) => parcelsWith(h, (s) => s.signal_type === 'upzoning_sb9') },
    { label: 'SB 79 within 1/4 mile', count: (h: string) => parcelsWith(h, (s) => s.signal_type === 'upzoning_sb79' && dist(s) <= 0.25) },
    // "within 1/2 mile" is cumulative: it includes everything within 1/4 mile
    { label: 'SB 79 within 1/2 mile', count: (h: string) => parcelsWith(h, (s) => s.signal_type === 'upzoning_sb79' && dist(s) <= 0.5) },
  ];
  const tot = defs.map((d) => sum(hoods.map(d.count)));
  const top = hoods.map((h) => ({ h, n: defs[0]!.count(h) })).sort((a, b) => b.n - a.n)[0]!;
  const where = hoods.length > 1 ? `${top.h} has the most SB 9 candidates (${top.n}). ` : '';
  return grouped('upzoning', hoods, defs,
    `${tot[0]} estimated SB 9 parcels; ${tot[2]} sit within 1/2 mile of transit, ${tot[1]} within 1/4 mile. ${where}In-house screen, unofficial.`.trim());
}

function recipesMatched(hoods: string[]): TrendMetric {
  const recipes = db.config.recipes.filter((r) => r.enabled);
  const count = (key: string, h: string) => db.parcels.filter((p) => p.neighborhood === h && (scoreBy.get(p.apn)?.recipe_matches ?? []).includes(key)).length;
  const ranked = recipes.map((r) => ({ r, total: sum(hoods.map((h) => count(r.key, h))) })).sort((a, b) => b.total - a.total);
  const shown = ranked.slice(0, 4), rest = ranked.slice(4);
  const defs = [
    ...shown.map(({ r }) => ({ label: r.name, count: (h: string) => count(r.key, h) })),
    ...(rest.length ? [{ label: 'Other recipes', count: (h: string) => sum(rest.map(({ r }) => count(r.key, h))) }] : []),
  ];
  const byHood = hoods.map((h) => ({ h, n: sum(recipes.map((r) => count(r.key, h))) })).sort((a, b) => b.n - a.n)[0]!;
  const lead = ranked[0]!;
  const tail = hoods.length > 1 ? ` ${byHood.h} has the most matches (${byHood.n}).` : '';
  return grouped('recipes', hoods, defs, `${lead.r.name} is the most-matched recipe (${lead.total} parcels).${tail}`);
}

function trendsFor(area: string): Trends {
  const names = Object.keys(db.trends);
  const sel = area === 'All' || !db.trends[area] ? names : [area];
  const months = db.trends[names[0]!]!.months;
  const monthly: TrendMetric[] = MONTHLY_KEYS.map((key) => {
    const labels = Object.keys(db.trends[names[0]!]!.raw[key]!);
    const series = labels.map((lab) => ({
      key: lab,
      label: key === 'permits' ? (SIGNAL_TYPES[lab]?.label.replace(' permit', '') ?? lab) : lab,
      points: months.map((m, i) => ({ month: m, value: sum(sel.map((n) => db.trends[n]!.raw[key]![lab]![i]!)) })),
    }));
    return { key, title: META[key].title, unit: META[key].unit, series, is_estimate: false, takeaway: takeaway(key, series) };
  });
  return { area: sel.length === names.length ? 'All' : area, months, metrics: [...monthly, upzoningBreakdown(sel), recipesMatched(sel)], is_sample: true };
}

/** Sample assignment: the agent who last logged an outcome on the lead, else a stable pick by APN. */
function assignedAgent(apn: string): string | null {
  const agents = db.team_members.filter((t) => t.role === 'agent');
  const last = db.outcomes.filter((o) => o.apn === apn && o.team_member_email).sort((a, b) => b.noted_at.localeCompare(a.noted_at))[0];
  const m = agents.find((a) => a.email === last?.team_member_email) ?? agents[Number(apn.slice(-4)) % Math.max(1, agents.length)];
  return m?.name ?? null;
}

export const fixturesProvider: DataProvider = {
  name: 'fixtures',
  isSample: true,

  async getTodayFeed() {
    const leads = leadsSorted().filter((l) => !suppressed.has(l.parcel.apn));
    const addr = (apn: string) => parcelBy.get(apn)?.situs_address ?? null;
    const since = TODAY - DAY * 1.5;
    return {
      as_of: new Date(TODAY).toISOString(),
      coverage: coverage(),
      top_leads: leads.slice(0, 10),
      new_signals: db.signals
        .filter((s) => new Date(s.detected_at).getTime() >= since)
        .sort((a, b) => b.detected_at.localeCompare(a.detected_at))
        .map((s) => ({ ...s, situs_address: addr(s.apn), neighborhood: parcelBy.get(s.apn)?.neighborhood ?? null })),
      approvals_waiting: db.outreach.filter((o) => o.status === 'awaiting_approval').map((o) => ({ ...o, situs_address: addr(o.apn) })),
      call_tasks_due: db.outreach.filter((o) => o.channel === 'call_task' && o.status === 'approved' && !o.sent_at)
        .map((o) => ({ ...o, situs_address: addr(o.apn), score: scoreBy.get(o.apn)?.score ?? null, reason_text: scoreBy.get(o.apn)?.reason_text ?? null, assigned_agent: assignedAgent(o.apn) })),
    };
  },

  async getLeads(filters = {}) {
    return leadsSorted().filter((l) => matches(l.parcel.apn, filters));
  },

  async getLead(apn) {
    if (!parcelBy.has(apn)) return null;
    const base = summary(apn);
    const detail: LeadDetail = {
      ...base,
      owners: db.owners.filter((o) => o.apn === apn),
      sales: db.sales_history.filter((s) => s.apn === apn).sort((a, b) => (b.sale_date ?? '').localeCompare(a.sale_date ?? '')),
      signals: [...(signalsBy.get(apn) ?? [])].sort((a, b) => (b.signal_date ?? '').localeCompare(a.signal_date ?? '')),
      outreach: db.outreach.filter((o) => o.apn === apn),
      outcomes: db.outcomes.filter((o) => o.apn === apn).sort((a, b) => b.noted_at.localeCompare(a.noted_at)),
      years_owned: yearsOwned(apn),
    };
    return detail;
  },

  async getMapPoints(filters = {}) {
    return db.parcels.filter((p) => matches(p.apn, filters)).map((p): MapPoint => {
      const sc = scoreBy.get(p.apn)!; const o = ownerBy.get(p.apn);
      const [lng, lat] = p.centroid!.coordinates as [number, number];
      return {
        apn: p.apn, lng, lat, score: sc.score, band: bandOf(sc.score), address: p.situs_address ?? p.apn,
        neighborhood: p.neighborhood ?? '', recipes: sc.recipe_matches ?? [],
        signalGroups: [...new Set((signalsBy.get(p.apn) ?? []).map((s) => s.signal_group))],
        reason_text: sc.reason_text, owner_name: o?.owner_name ?? null, est_equity: o?.est_equity ?? null,
        years_owned: yearsOwned(p.apn),
      };
    });
  },

  async getTrends(area) { return trendsFor(area); },

  async getPipeline(): Promise<Pipeline> {
    const apns = db.parcels.map((p) => p.apn);
    const flagged = apns.filter((a) => (scoreBy.get(a)?.score ?? 0) >= 60 && !suppressed.has(a));
    const agents = db.team_members.filter((t) => t.role === 'agent');
    const outcomesOf = (apnSet: Set<string>) => db.outcomes.filter((o) => apnSet.has(o.apn));
    return {
      overall: funnel('All leads', flagged, db.outcomes),
      // Sample assignment: leads the agent worked, plus an alternating share of the remaining flagged leads.
      by_agent: agents.map((a, idx) => {
        const mine = db.outcomes.filter((o) => o.team_member_email === a.email);
        const assigned = new Set(mine.map((o) => o.apn));
        const worked = new Set(db.outcomes.map((o) => o.apn));
        flagged.forEach((apn, i) => { if (!worked.has(apn) && i % agents.length === idx) assigned.add(apn); });
        return funnel(a.name ?? a.email, [...assigned], mine);
      }),
      by_recipe: db.config.recipes.filter((r) => r.enabled).map((r) => {
        const set = flagged.filter((a) => (scoreBy.get(a)?.recipe_matches ?? []).includes(r.key));
        return funnel(r.name, set, outcomesOf(new Set(set)));
      }),
      is_sample: true,
    };
  },

  async getBacktest(): Promise<Backtest> {
    const b = db.backtest;
    return { ...b, share_flagged: b.past_sales_considered ? b.flagged_before_listing / b.past_sales_considered : 0 };
  },

  async getCoverage() { return coverage(); },

  async getConfig() { return db.config; },

  async getSources() {
    return Object.entries(SOURCES).map(([key, s]) => {
      const runs = db.source_runs.filter((r) => r.source_key === key).sort((a, b) => b.started_at.localeCompare(a.started_at));
      const last = runs[0] ?? null;
      return { source_key: key, label: s.label, last_run: last, status: last?.status ?? ('never' as const), is_sample: !!s.is_sample };
    });
  },
};

export { SIGNAL_GROUPS };
