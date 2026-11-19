/** Logic both providers share: deterministic derivations, no AI. */
import { COMPONENTS, RECIPES, SIGNAL_GROUPS, SIGNAL_TYPES, bandOf } from './catalog';
import type {
  LeadStatus, RawScoreComponent, ScoreItem, TrendMetric, TrendRows, Trends, UpzoningRow,
} from './types';
export type { TrendRows } from './types';

const DAY = 86_400_000;

/** Whole years since `date` (tenure start). */
export function yearsSince(date: string | null | undefined, now: Date): number | null {
  if (!date) return null;
  const y = Math.floor((now.getTime() - new Date(`${date.slice(0, 10)}T12:00:00Z`).getTime()) / (365.25 * DAY));
  return y < 0 ? null : y;
}

const STATUS_RANK: Record<string, number> = { draft: 1, approved: 2, awaiting_approval: 3, sent: 4 };
/** Most advanced outreach state wins; no rows means the lead is new. Call tasks do not count as drafts. */
export function leadStatus(rows: { channel: string; status: string }[]): LeadStatus {
  const top = rows.filter((o) => o.channel !== 'call_task' && o.status in STATUS_RANK)
    .sort((a, b) => STATUS_RANK[b.status]! - STATUS_RANK[a.status]!)[0];
  return !top ? 'new' : top.status === 'draft' ? 'draft_ready' : (top.status as LeadStatus);
}

/** Stored components -> display items (labels and max points from the catalog). Largest contribution first. */
export function scoreItems(components: RawScoreComponent[] | null | undefined): ScoreItem[] {
  return (components ?? [])
    .map((c) => ({ c, info: COMPONENTS[c.key] }))
    .filter((x) => x.info && x.info.max > 0)
    .map(({ c, info }) => ({
      key: c.key, label: info!.label, points: Math.round(c.contribution * 10) / 10, max: info!.max,
      is_sample: !!c.is_sample, is_estimate: !!c.is_estimate,
    }))
    .sort((a, b) => b.points - a.points || b.max - a.max);
}

/* ── trends: shared builder over rows shaped like the SQL views ── */
/** The 12 month keys ("YYYY-MM") ending with the month of `now`. */
export function monthKeys(now: Date, n = 12): string[] {
  const out: string[] = [];
  for (let i = n - 1; i >= 0; i--) {
    const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - i, 1));
    out.push(`${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`);
  }
  return out;
}

const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);
const META = {
  turnover: { title: 'Turnover', unit: 'sales per month' },
  permits: { title: 'Permits approved, by group', unit: 'permits per month' },
  str_lost: { title: 'Short-term rental licenses removed', unit: 'licenses per month' },
  tax_default: { title: 'Tax-default notices', unit: 'parcels per month' },
  upzoning: { title: 'Upzoning-eligible parcels (estimated)', unit: 'parcels' },
  recipes: { title: 'Recipes matched', unit: 'parcels' },
} as const;

function direction(last3: number, prev3: number) {
  const pct = prev3 ? Math.round(((last3 - prev3) / prev3) * 100) : 0;
  return { pct, dir: !prev3 ? (last3 ? 'new' : 'flat') : pct > 0 ? `up ${pct}%` : pct < 0 ? `down ${Math.abs(pct)}%` : 'flat' };
}

export function buildTrends(area: string, hoods: string[], now: Date, rows: TrendRows): Trends {
  const months = monthKeys(now);
  const inArea = <T extends { neighborhood: string }>(xs: T[]) => xs.filter((r) => hoods.includes(r.neighborhood));
  const monthly = (xs: { month: string; n: number }[]) => months.map((m) => sum(xs.filter((x) => x.month.slice(0, 7) === m).map((x) => x.n)));
  const sampleIn = (xs: { sample_rows: number }[]) => xs.some((x) => x.sample_rows > 0);

  const turnover = inArea(rows.turnover);
  const tSeries = monthly(turnover.map((r) => ({ month: r.month, n: r.sales })));
  const sigs = inArea(rows.signals);
  const ofType = (t: string) => sigs.filter((r) => r.signal_type === t);
  const permits = ofType('permit_approved');
  const groups = [...new Set(permits.map((r) => r.signal_group))];
  const groupTotals = groups.map((g) => ({ g, n: sum(permits.filter((r) => r.signal_group === g).map((r) => r.signals)) })).sort((a, b) => b.n - a.n);
  const str = ofType('stro_license_removed');
  const tax = ofType('tax_default');

  const mk = (key: TrendMetric['key'], series: TrendMetric['series'], takeaway: string, is_sample: boolean, extra: Partial<TrendMetric> = {}): TrendMetric =>
    ({ key, ...META[key], series, takeaway, is_sample, is_estimate: false, ...extra });
  const line = (key: string, label: string, vals: number[]) => ({ key, label, points: months.map((m, i) => ({ month: m, value: vals[i]! })) });
  const last3 = (v: number[]) => sum(v.slice(-3)), prev3 = (v: number[]) => sum(v.slice(-6, -3));

  const tDir = direction(last3(tSeries), prev3(tSeries));
  const metrics: TrendMetric[] = [];
  metrics.push(mk('turnover', [line('sales', 'Sales', tSeries)],
    turnover.length === 0 ? 'No sales on record for this period.'
      : `Sales over the last 3 months are ${tDir.dir} versus the 3 months before (${last3(tSeries)} vs ${prev3(tSeries)}).`, sampleIn(turnover)));

  const pSeries = groupTotals.map(({ g }) => line(g, SIGNAL_GROUPS[g] ?? g, monthly(permits.filter((r) => r.signal_group === g).map((r) => ({ month: r.month, n: r.signals })))));
  const pTotal = months.map((_, i) => sum(pSeries.map((s) => s.points[i]!.value)));
  const pDir = direction(last3(pTotal), prev3(pTotal));
  const pLead = pSeries.map((s) => ({ s, n: sum(s.points.map((p) => p.value)) })).sort((a, b) => b.n - a.n)[0];
  metrics.push(mk('permits', pSeries.length ? pSeries : [line('none', 'Permits', months.map(() => 0))],
    pLead && pLead.n ? `${pLead.s.label} is the largest permit group; total permits are ${pDir.dir} over the last 3 months.` : 'No permits were approved in this period.',
    sampleIn(permits)));

  const sSeries = monthly(str.map((r) => ({ month: r.month, n: r.signals })));
  metrics.push(mk('str_lost', [line('removed', 'Licenses removed', sSeries)],
    sum(sSeries) === 0 ? 'No short-term rental licenses have been removed in this period. Removals appear once a second license snapshot exists.'
      : `${last3(sSeries)} licenses removed in the last 3 months, ${direction(last3(sSeries), prev3(sSeries)).dir} versus the prior 3.`, sampleIn(str)));

  const xSeries = monthly(tax.map((r) => ({ month: r.month, n: r.signals })));
  metrics.push(mk('tax_default', [line('tax', 'Parcels', xSeries)],
    sum(xSeries) === 0 ? 'No tax-default notices in this period.' : `${sum(xSeries)} parcels appeared on the county tax-default list in the last 12 months.`, sampleIn(tax)));

  const up = hoods.map((h) => rows.upzoning.find((r) => r.neighborhood === h) ?? { neighborhood: h, sb9: 0, sb79_quarter_mile: 0, sb79_half_mile: 0, sample_rows: 0 });
  const upDefs: [string, (r: UpzoningRow) => number][] = [['SB 9 estimate', (r) => r.sb9], ['SB 79 within 1/4 mile', (r) => r.sb79_quarter_mile], ['SB 79 within 1/2 mile', (r) => r.sb79_half_mile]];
  const upTot = upDefs.map(([, f]) => sum(up.map(f)));
  const upTop = [...up].sort((a, b) => b.sb9 - a.sb9)[0]!;
  metrics.push(mk('upzoning', upDefs.map(([label, f]) => ({ key: label, label, points: up.map((r) => ({ month: r.neighborhood, value: f(r) })) })),
    `${upTot[0]} estimated SB 9 parcels; ${upTot[2]} sit within 1/2 mile of transit, ${upTot[1]} within 1/4 mile. ${hoods.length > 1 ? `${upTop.neighborhood} has the most SB 9 candidates (${upTop.sb9}). ` : ''}In-house screen, unofficial.`.trim(),
    sampleIn(up), { categories: hoods, is_estimate: true }));

  const enabled = RECIPES.filter((r) => r.enabled);
  const rr = inArea(rows.recipes);
  const rcount = (key: string, h: string) => rr.find((r) => r.recipe === key && r.neighborhood === h)?.parcels ?? 0;
  const ranked = enabled.map((r) => ({ r, total: sum(hoods.map((h) => rcount(r.key, h))) })).sort((a, b) => b.total - a.total);
  const shown = ranked.slice(0, 4), rest = ranked.slice(4);
  const rDefs = [
    ...shown.map(({ r }) => ({ label: r.label, count: (h: string) => rcount(r.key, h) })),
    ...(rest.length ? [{ label: 'Other recipes', count: (h: string) => sum(rest.map(({ r }) => rcount(r.key, h))) }] : []),
  ];
  const byHood = hoods.map((h) => ({ h, n: sum(enabled.map((r) => rcount(r.key, h))) })).sort((a, b) => b.n - a.n)[0]!;
  metrics.push(mk('recipes', rDefs.map((d) => ({ key: d.label, label: d.label, points: hoods.map((h) => ({ month: h, value: d.count(h) })) })),
    ranked[0] && ranked[0].total ? `${ranked[0].r.label} is the most-matched recipe (${ranked[0].total} parcels).${hoods.length > 1 ? ` ${byHood.h} has the most matches (${byHood.n}).` : ''}` : 'No parcels match a recipe yet.',
    sampleIn(rr), { categories: hoods }));

  return { area, months, metrics, is_sample: metrics.some((m) => m.is_sample) };
}

export { bandOf, SIGNAL_TYPES };
