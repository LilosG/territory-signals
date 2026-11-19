/**
 * Deterministic sample-data generator. Output: src/data/fixtures.json
 * Every record is labeled sample (is_sample = true). Nothing here is real:
 * owners are "Sample Owner <last 4 of APN>", house numbers are fake, and
 * point locations are placed inside the official SANDAG planning areas.
 *
 * Run: npm run fixtures
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import type { Feature, FeatureCollection, MultiPolygon, Polygon, Position } from 'geojson';
import type {
  FixtureBundle, Neighborhood, Parcel, SourceRun, Signal, Owner, SaleHistory, Score,
  RawScoreComponent, Suppression, Outreach, StageEvent, TeamMember, TrendRows,
} from '../src/lib/data/types';
// Names come from the generated catalog only: the fixtures and live data share one vocabulary.
import { COMPONENTS, PERMIT_TYPES, RECIPES, SIGNAL_GROUPS, SIGNAL_TYPES } from '../src/lib/data/catalog';
import { MODEL_VERSION } from '../src/lib/data/catalog';

const here = dirname(fileURLToPath(import.meta.url));
const TODAY = new Date('2026-11-18T12:00:00Z');

/* ── seeded PRNG ── */
function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const rnd = mulberry32(20261118);
const between = (a: number, b: number) => a + (b - a) * rnd();
const int = (a: number, b: number) => Math.floor(between(a, b + 1));
const pick = <T,>(xs: readonly T[]): T => xs[Math.floor(rnd() * xs.length)] as T;
const chance = (p: number) => rnd() < p;
const hex = (n: number) => Array.from({ length: n }, () => Math.floor(rnd() * 16).toString(16)).join('');
const uuid = () => `${hex(8)}-${hex(4)}-4${hex(3)}-a${hex(3)}-${hex(12)}`;
const dayMs = 86_400_000;
const dateStr = (d: Date) => d.toISOString().slice(0, 10);
const daysAgo = (n: number) => new Date(TODAY.getTime() - n * dayMs);
const round = (n: number, step: number) => Math.round(n / step) * step;

/* ── planning areas ── */
const pa = JSON.parse(readFileSync(resolve(here, '../src/data/planning-areas.geojson'), 'utf8')) as FeatureCollection<Polygon>;
const areas = ['La Jolla', 'Pacific Beach', 'Mission Beach'] as const;
type Area = (typeof areas)[number];
const feat = (n: string) => pa.features.find((f) => f.properties?.name === n) as Feature<Polygon>;

function inRing(x: number, y: number, ring: Position[]) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i] as Position; const [xj, yj] = ring[j] as Position;
    if (yi! > y !== yj! > y && x < ((xj! - xi!) * (y - yi!)) / (yj! - yi!) + xi!) inside = !inside;
  }
  return inside;
}
function inPoly(x: number, y: number, poly: Polygon) {
  const [outer, ...holes] = poly.coordinates as Position[][];
  return inRing(x, y, outer!) && !holes.some((h) => inRing(x, y, h));
}
function randomPointIn(poly: Polygon): [number, number] {
  const pts = (poly.coordinates[0] as Position[]);
  const xs = pts.map((p) => p[0]!), ys = pts.map((p) => p[1]!);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  for (let i = 0; i < 10000; i++) {
    const x = between(x0, x1), y = between(y0, y1);
    if (inPoly(x, y, poly)) return [round(x, 1e-6), round(y, 1e-6)];
  }
  throw new Error('no point found');
}

const iso = (d: Date) => d.toISOString();
const created = '2026-11-18T05:00:00.000Z';

const neighborhoods: Neighborhood[] = areas.map((a) => {
  const g = feat(a).geometry;
  return {
    id: uuid(), name: a, planning_area: a,
    geom: { type: 'MultiPolygon', coordinates: [g.coordinates] } as MultiPolygon,
    is_official: true, created_at: created,
  };
});

/* ── parcels ── */
const COUNTS: Record<Area, number> = { 'La Jolla': 80, 'Pacific Beach': 70, 'Mission Beach': 30 };
const ZIP: Record<Area, string> = { 'La Jolla': '92037', 'Pacific Beach': '92109', 'Mission Beach': '92109' };
const PREFIX: Record<Area, string> = { 'La Jolla': '350', 'Pacific Beach': '423', 'Mission Beach': '424' };
const STREETS: Record<Area, string[]> = {
  'La Jolla': ['Sample Camino', 'Sample Way', 'Sample Court', 'Sample Lane', 'Sample Terrace'],
  'Pacific Beach': ['Sample Street', 'Sample Avenue', 'Sample Place', 'Sample Drive'],
  'Mission Beach': ['Sample Walk', 'Sample Court', 'Sample Place'],
};
const ZONES: Record<Area, string[]> = {
  'La Jolla': ['RS-1-7', 'RS-1-4', 'RS-1-5', 'RM-1-1', 'LJSPD-SF'],
  'Pacific Beach': ['RS-1-7', 'RM-1-1', 'RM-2-5', 'CC-3-4'],
  'Mission Beach': ['MBPD-R-S', 'MBPD-R-N', 'MBPD-C'],
};
// last-4 pool: unique across all parcels so "Sample Owner <last4>" is unique
const last4Pool = Array.from({ length: 9000 }, (_, i) => 1000 + i);
for (let i = last4Pool.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [last4Pool[i], last4Pool[j]] = [last4Pool[j]!, last4Pool[i]!]; }

const parcels: Parcel[] = [];
const meta = new Map<string, { area: Area; lot: number }>();
let houseSeed = 9001;
for (const area of areas) {
  const poly = feat(area).geometry;
  for (let i = 0; i < COUNTS[area]; i++) {
    const last4 = String(last4Pool.pop());
    const apn = `${PREFIX[area]}${String(int(100, 999))}${last4}`.slice(0, 10).padEnd(10, '0');
    const [lng, lat] = randomPointIn(poly);
    const d = 0.00006;
    const lot = round(between(2800, area === 'La Jolla' ? 14000 : 7500), 50);
    const zoning = pick(ZONES[area]);
    parcels.push({
      apn,
      situs_address: `${houseSeed++} ${pick(STREETS[area])}`,
      zip: ZIP[area], planning_area: area, neighborhood: area,
      geom: { type: 'MultiPolygon', coordinates: [[[[lng - d, lat - d], [lng + d, lat - d], [lng + d, lat + d], [lng - d, lat + d], [lng - d, lat - d]]]] },
      centroid: { type: 'Point', coordinates: [lng, lat] },
      lot_sqft: lot,
      land_use: zoning.startsWith('RS') || zoning.endsWith('-S') ? 'Single family residential' : zoning.startsWith('CC') || zoning.endsWith('-C') ? 'Commercial mixed use' : 'Multi-family residential',
      zoning, year_built: int(1925, 2016),
      last_recorded_doc_date: dateStr(daysAgo(int(20, 3600))),
      source_key: 'sangis_parcels', created_at: created, updated_at: created,
    });
    meta.set(apn, { area, lot });
  }
}

/* ── source runs: the same source keys the pipelines write ── */
const SRC_KEYS = ['planning_areas', 'parcels', 'zoning', 'stro_licenses', 'dev_permits', 'tax_default', 'upzoning_estimate', 'fire_zones'];
const source_runs: SourceRun[] = [];
const latestRun: Record<string, string> = {};
for (const key of SRC_KEYS) {
  for (const back of [6, 3, 0]) {
    const start = new Date(TODAY.getTime() - back * dayMs - 8 * 3600_000 + int(0, 50) * 60_000);
    const failed = key === 'fire_zones';
    const fetched = key === 'parcels' ? 180 : int(40, 600);
    const matched = failed ? null : Math.round(fetched * between(0.82, 0.97));
    const run: SourceRun = {
      id: uuid(), source_key: key, started_at: iso(start),
      finished_at: iso(new Date(start.getTime() + int(20, 400) * 1000)),
      status: failed ? 'failed' : 'success',
      rows_fetched: failed ? null : fetched, rows_matched: matched,
      rows_unmatched: failed ? null : fetched - matched!,
      error_message: failed ? 'awaiting manual download (sample)' : null,
      created_at: iso(start),
    };
    source_runs.push(run);
    if (!failed) latestRun[key] = run.id;
  }
}

/* ── owners + sales ── */
const owners: Owner[] = [];
const sales: SaleHistory[] = [];
const ownerBy = new Map<string, Owner>();
const yearsBy = new Map<string, number>();
for (const p of parcels) {
  const { area } = meta.get(p.apn)!;
  const last4 = p.apn.slice(-4);
  const years = Math.round(Math.pow(rnd(), 1.4) * 34 * 10) / 10 + 0.4;
  const sale = daysAgo(Math.round(years * 365));
  const base = area === 'La Jolla' ? between(1.7e6, 5.8e6) : area === 'Mission Beach' ? between(1.5e6, 3.6e6) : between(1.3e6, 3.2e6);
  const value = round(base, 5000);
  const growth = Math.pow(1.065, years);
  const price = round(value / growth, 1000);
  const mortgage = years < 12 ? chance(0.85) : years < 22 ? chance(0.4) : chance(0.12);
  const equity = mortgage ? round(value * between(0.2, 0.7), 5000) : value;
  const absentee = chance(0.22);
  const out = absentee && chance(0.55);
  const o: Owner = {
    id: uuid(), apn: p.apn, owner_name: `Sample Owner ${last4}`,
    mailing_address: absentee ? `${int(100, 999)} Sample Mailing Rd, ${out ? 'Sample City, AZ 85001' : 'Sample City, CA 92101'}` : p.situs_address,
    owner_occupied: !absentee, absentee, out_of_state: out,
    last_sale_date: dateStr(sale), last_sale_price: price, mortgage_open: mortgage,
    est_value: value, est_equity: equity, provider: 'sample', is_sample: true,
    as_of: '2026-11-01', created_at: created,
  };
  owners.push(o); ownerBy.set(p.apn, o); yearsBy.set(p.apn, years);
  // sales: prior sales then last sale
  const prior = years > 9 && chance(0.6) ? 1 : 0;
  if (prior) {
    const earlier = daysAgo(Math.round((years + between(4, 12)) * 365));
    sales.push({ id: uuid(), apn: p.apn, sale_date: dateStr(earlier), sale_price: round(price / Math.pow(1.065, 7), 1000), doc_type: 'grant deed', provider: 'sample', is_sample: true, created_at: created });
  }
  sales.push({ id: uuid(), apn: p.apn, sale_date: dateStr(sale), sale_price: price, doc_type: chance(0.1) ? 'trust transfer deed' : 'grant deed', provider: 'sample', is_sample: true, created_at: created });
}

/* ── signals (catalog types and groups only) ── */
const signals: Signal[] = [];
let recIdx = 1000;
const RECIDS: Record<string, () => string> = {
  stro_licenses: () => `STR-${String(int(1, 99999)).padStart(5, '0')}L`,
  dev_permits: () => `PMT-${String(++recIdx).padStart(7, '0')}`,
  tax_default: () => `${int(3000000000, 4299999999)}`,
  upzoning_estimate: () => `EST-${int(1, 99999)}`,
  sample_sales_history: () => `${int(3000000000, 4299999999)}:${dateStr(daysAgo(int(100, 4000)))}:trust transfer deed`,
};
const permitKeys = (re: RegExp) => { const ks = Object.entries(PERMIT_TYPES).filter(([, l]) => re.test(l)).map(([k]) => k); return ks.length ? ks : Object.keys(PERMIT_TYPES).slice(0, 5); };
const GROUP_PERMITS: Record<string, string[]> = {
  remodel_addition: permitKeys(/remodel|addition/i), adu: permitKeys(/ADU|accessory/i), demolition_lot_split: permitKeys(/demolition/i),
  solar_energy: permitKeys(/solar/i), pre_sale_prep: permitKeys(/plumbing|electrical|mechanical/i), other: permitKeys(/agreement|traffic|alternate/i),
};
function addSignal(apn: string, type: string, group: string, source_key: string, opts: { daysBack?: number; method?: Signal['match_method']; est?: boolean; details?: Record<string, unknown> } = {}) {
  if (!SIGNAL_TYPES[type] || !SIGNAL_GROUPS[group]) throw new Error(`not in catalog: ${type} / ${group}`);
  const method = opts.method ?? 'apn';
  const conf = method === 'apn' ? between(0.95, 1) : method === 'spatial' ? between(0.88, 0.95) : between(0.78, 0.9);
  const back = opts.daysBack ?? int(3, 320);
  const sd = daysAgo(back);
  const detected = back <= 1 ? new Date(TODAY.getTime() - int(1, 20) * 3600_000) : new Date(sd.getTime() + int(1, 3) * dayMs);
  signals.push({
    id: uuid(), apn, signal_type: type, signal_group: group, signal_date: dateStr(sd),
    detected_at: iso(detected > TODAY ? TODAY : detected), source_key, source_record_id: RECIDS[source_key]!(),
    run_id: latestRun[source_key] ?? null, confidence: Math.round(conf * 100) / 100, match_method: method,
    is_estimate: opts.est ?? false, is_sample: true, details: opts.details ?? null, created_at: iso(detected),
  });
}
const permit = (apn: string, group: string, daysBack?: number) =>
  addSignal(apn, 'permit_approved', group, 'dev_permits', { daysBack, method: chance(0.9) ? 'apn' : 'address', details: { approval_type: pick(GROUP_PERMITS[group]!) } });
const PERMIT_GROUPS = ['remodel_addition', 'remodel_addition', 'pre_sale_prep', 'pre_sale_prep', 'adu', 'demolition_lot_split', 'solar_energy', 'other'] as const;
const lastSale = new Map(sales.map((s) => [s.apn, s]));
for (const p of parcels) {
  const { area, lot } = meta.get(p.apn)!;
  if (area !== 'La Jolla' && chance(0.3)) addSignal(p.apn, chance(0.25) ? 'stro_license_removed' : 'stro_license_active', 'stro', 'stro_licenses', { method: 'spatial', daysBack: chance(0.5) ? 0 : int(10, 200), details: { tier: pick(['Tier 2', 'Tier 3', 'Tier 4']), status: 'sample' } });
  if (chance(0.32)) permit(p.apn, pick(PERMIT_GROUPS));
  if (chance(0.06)) addSignal(p.apn, 'permit_stalled', 'remodel_addition', 'dev_permits', { daysBack: int(100, 400), details: { approval_type: pick(GROUP_PERMITS.remodel_addition!) } });
  if (chance(0.06)) addSignal(p.apn, 'tax_default', 'distress', 'tax_default', { daysBack: int(20, 140), details: { list: 'Notice of Impending Power to Sell (sample)' } });
  if (lot >= 4500 && p.zoning?.startsWith('RS') && chance(0.4)) addSignal(p.apn, 'sb9_lot_split_estimate', 'upzoning', 'upzoning_estimate', { method: 'spatial', est: true, daysBack: 0, details: { label: 'estimated eligibility (in-house screen, not an official determination)' } });
  if (area === 'Pacific Beach' && chance(0.18)) addSignal(p.apn, 'sb79_transit_estimate', 'upzoning', 'upzoning_estimate', { method: 'spatial', est: true, daysBack: 0, details: { distance_band: chance(0.4) ? 'within_quarter_mile' : 'within_half_mile' } });
  const ls = lastSale.get(p.apn);
  if (ls?.doc_type === 'trust transfer deed') addSignal(p.apn, 'ownership_transfer', 'life_event', 'sample_sales_history', { daysBack: Math.round((TODAY.getTime() - new Date(ls.sale_date!).getTime()) / dayMs), details: { label: 'Trust transfer deed', doc_type: ls.doc_type, transfer_kind: 'trust' } });
}
// guarantee a few signals detected in the last 24 hours
([['permit_approved', 'adu'], ['stro_license_removed', 'stro'], ['tax_default', 'distress'], ['permit_approved', 'demolition_lot_split'], ['sb9_lot_split_estimate', 'upzoning']] as const).forEach(([t, g], i) => {
  const p = parcels[i * 23 + 5]!;
  if (t === 'permit_approved') permit(p.apn, g, 0);
  else addSignal(p.apn, t, g, t === 'stro_license_removed' ? 'stro_licenses' : t === 'tax_default' ? 'tax_default' : 'upzoning_estimate', { daysBack: 0, est: t === 'sb9_lot_split_estimate', method: t === 'sb9_lot_split_estimate' ? 'spatial' : 'apn' });
});

/* ── scoring: same component list shape the scorer writes; labels and max points come from the catalog ── */
const monthYear = (s: string | null) => s ? new Date(s + 'T00:00:00Z').toLocaleDateString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' }) : '';
const byApn = new Map<string, Signal[]>();
for (const s of signals) (byApn.get(s.apn) ?? byApn.set(s.apn, []).get(s.apn)!).push(s);
const SNAPSHOT = new Set(['stro_license_active', 'sb9_lot_split_estimate', 'sb79_transit_estimate', 'fire_hazard_zone']);
const equities = owners.map((o) => o.est_equity ?? 0).sort((a, b) => a - b);
const p75 = equities[Math.floor(equities.length * 0.75)]!;
const sampleSource = (k: string) => (k.startsWith('owner:') ? 'sample_owner' : undefined);

const scores: Score[] = [];
const phrase: string[][] = [];
for (const p of parcels) {
  const o = ownerBy.get(p.apn)!; const years = Math.floor(yearsBy.get(p.apn)!);
  const sigs = byApn.get(p.apn) ?? [];
  const comps: RawScoreComponent[] = [];
  for (const [key, info] of Object.entries(COMPONENTS)) {
    if (info.kind !== 'signal' || info.max <= 0) continue;
    const [type, group] = key.split(':') as [string, string | undefined];
    const s = sigs.filter((x) => x.signal_type === type && (!group || x.signal_group === group)).sort((a, b) => (b.signal_date ?? '').localeCompare(a.signal_date ?? ''))[0];
    if (!s) continue;
    const age = Math.round((TODAY.getTime() - new Date(s.signal_date!).getTime()) / dayMs);
    const decay = SNAPSHOT.has(type) ? 1 : Math.pow(0.5, age / 180);
    comps.push({
      key, kind: 'signal', family: info.family, contribution: Math.round(info.max * decay * s.confidence * 10) / 10, raw_weight: info.max,
      decay_factor: Math.round(decay * 1000) / 1000, is_sample: false, is_estimate: s.is_estimate, signal_id: s.id,
      source_key: s.source_key, source_record_id: s.source_record_id, confidence: s.confidence, facts: { signal_date: s.signal_date },
    });
  }
  const ownerComp = (key: string, pts: number, facts: Record<string, unknown>) => {
    const info = COMPONENTS[key]!;
    comps.push({ key, kind: 'owner', family: info.family, contribution: Math.round(pts * 10) / 10, raw_weight: info.max, is_sample: true, is_estimate: key.includes('equity'), facts, source_key: 'sample_owner', source_record_id: `owners:${o.id}` });
  };
  if (years >= 10) ownerComp('owner:years_owned', Math.min(15, years / 2), { years_owned: years });
  if (o.out_of_state) ownerComp('owner:out_of_state', 12, {}); else if (o.absentee) ownerComp('owner:absentee', 10, {});
  if (!o.mortgage_open) ownerComp('owner:mortgage_open_false', 10, {});
  if ((o.est_equity ?? 0) >= p75) ownerComp('owner:est_equity_top_quartile', 5, {});
  const fams = new Set(comps.filter((c) => c.contribution > 0).map((c) => c.family));
  const total = Math.min(100, Math.round(comps.reduce((a, c) => a + c.contribution, 0) * Math.min(1.3, 1 + 0.1 * Math.max(0, fams.size - 1))));

  const has = (k: string) => comps.some((c) => c.key === k && c.contribution > 0);
  const hasType = (t: string) => sigs.some((s) => s.signal_type === t);
  const matches: string[] = [];
  const want = (k: string, ok: boolean) => { if (ok && RECIPES.find((r) => r.key === k)?.enabled) matches.push(k); };
  want('str_exit', hasType('stro_license_removed'));
  want('tired_landlord', !!o.absentee && years >= 15 && (hasType('tax_default') || hasType('permit_stalled')));
  want('builder_bait', (hasType('sb9_lot_split_estimate') || hasType('sb79_transit_estimate')) && meta.get(p.apn)!.lot >= 6000 && years >= 20);
  want('pre_list_prep', sigs.some((s) => s.signal_group === 'pre_sale_prep') && years >= 10);
  want('stalled_project', hasType('permit_stalled'));
  want('downsizer', !!o.owner_occupied && years >= 20 && !o.mortgage_open);
  want('financial_pressure', hasType('tax_default'));
  want('insurance_squeeze', hasType('fire_hazard_zone'));
  void has;

  const ranked = [...comps].filter((c) => c.contribution > 0).sort((a, b) => b.contribution - a.contribution).slice(0, 3);
  const text = ranked.map((c) => {
    const lab = COMPONENTS[c.key]!.label.replace(/ \(estimated\)$/, '');
    if (c.key === 'owner:years_owned') return `owned ${years} years (sample data)`;
    if (c.kind === 'owner') return `${lab.toLowerCase()} (sample data${c.is_estimate ? ', estimated' : ''})`;
    const when = (c.facts as { signal_date?: string }).signal_date;
    return `${lab} (${monthYear(when ?? null)}${c.is_estimate ? ', estimated' : ''})`;
  });
  phrase.push(text);
  scores.push({
    id: uuid(), apn: p.apn, score: total, components: comps,
    reason_text: text.length ? text.join('; ').replace(/^./, (c) => c.toUpperCase()) + '.' : 'No strong signals yet.',
    recipe_matches: matches, primary_recipe: matches[0] ?? null, model_version: MODEL_VERSION, uses_sample_data: true,
    scored_at: '2026-11-18T05:30:00.000Z', created_at: '2026-11-18T05:30:00.000Z',
  });
}

/* ── team, suppressions, outreach, stage events ── */
const team_members: TeamMember[] = [
  { id: uuid(), email: 'owner@example.com', name: 'Sample Principal', role: 'owner', created_at: created },
  { id: uuid(), email: 'agent.one@example.com', name: 'Sample Agent One', role: 'agent', created_at: created },
  { id: uuid(), email: 'agent.two@example.com', name: 'Sample Agent Two', role: 'agent', created_at: created },
  { id: uuid(), email: 'assistant@example.com', name: 'Sample Assistant', role: 'assistant', created_at: created },
];
const agents = team_members.filter((t) => t.role === 'agent');
const ranked = [...scores].sort((a, b) => b.score - a.score || a.apn.localeCompare(b.apn));
const suppressions: Suppression[] = ranked.slice(3, 7).map((s, i) => ({
  id: uuid(), apn: s.apn, reason: ['Owner asked not to be contacted (sample)', 'Recently listed with another agent (sample)', 'Do-not-contact list (sample)', 'Under contract (sample)'][i]!,
  until_date: i % 2 ? dateStr(daysAgo(-90)) : null, created_at: created,
}));
const suppressed = new Set(suppressions.map((s) => s.apn));

const pBy = new Map(parcels.map((p) => [p.apn, p]));
const outreach: Outreach[] = [];
const stage_events: StageEvent[] = [];
const factsFor = (apn: string): NonNullable<Outreach['source_facts']> => {
  const sc = scores.find((x) => x.apn === apn)!;
  return [...(sc.components ?? [])].filter((c) => c.contribution > 0).sort((a, b) => b.contribution - a.contribution).slice(0, 3)
    .map((c) => ({ kind: 'component', key: c.key, is_estimate: c.is_estimate, is_sample: c.is_sample, source_key: c.source_key ?? 'sample_owner', source_record_id: c.source_record_id ?? '' }));
};
ranked.slice(0, 45).forEach((s, idx) => {
  if (suppressed.has(s.apn)) return;
  const p = pBy.get(s.apn)!; const facts = factsFor(s.apn);
  const yrs = Math.floor(yearsBy.get(s.apn)!);
  const agent = agents[idx % agents.length]!;
  const letter = `To the owners of ${p.situs_address},\n\nI focus on ${p.neighborhood}, and public records show your home has been in your hands for about ${yrs} years. If it would be useful, I can send a short, private market summary for your street. No obligation at all.\n\nWarm regards,\nThe Kaiser Team`;
  const email = `Subject: A quick note about ${p.situs_address}\n\nHello,\n\nI work with homeowners in ${p.neighborhood}. If it would be useful, I can send a short market snapshot for your street.\n\nBest,\nThe Kaiser Team`;
  const call = `CALL TASK (manual; no automated calls)\nWhy now: ${(s.reason_text ?? '').replace(/\.$/, '')}.\nOpen with: introduce yourself as a ${p.neighborhood} specialist; ask permission to share a market snapshot.\nRecord the result as an outcome after the call.`;
  const status: Outreach['status'] = idx < 8 ? 'awaiting_approval' : 'draft';
  const base = { recipe: s.primary_recipe, assigned_to: agent.email, blocked_reason: 'missing agent name or DRE license; sample data', uses_sample_data: true, approved_by: null, sent_at: null, original_content: null, edited_by: null, edited_at: null } as const;
  outreach.push({ id: uuid(), apn: s.apn, channel: 'mail', status, content: letter, source_facts: facts, created_at: iso(daysAgo(int(1, 40))), ...base });
  if (idx % 3 === 0) outreach.push({ id: uuid(), apn: s.apn, channel: 'email', status: 'draft', content: email, source_facts: facts, created_at: iso(daysAgo(int(1, 20))), ...base });
  if (idx % 4 === 0) outreach.push({ id: uuid(), apn: s.apn, channel: 'call_task', status: 'approved', content: call, source_facts: facts, created_at: iso(daysAgo(int(0, 10))), ...base, approved_by: 'assistant@example.com' });
  if (idx >= 8 && idx < 38) {
    const seq = ['signal', 'contacted'];
    if (chance(0.62)) seq.push('conversation');
    if (seq.length > 2 && chance(0.5)) seq.push('appointment');
    if (seq.length > 3 && chance(0.4)) seq.push('listing');
    if (chance(0.12)) seq.push(chance(0.5) ? 'not_interested' : 'bad_data');
    let back = int(20, 90);
    for (const st of seq) {
      stage_events.push({ id: uuid(), apn: s.apn, stage: st, team_member_email: agent.email, occurred_at: iso(daysAgo(back)), note: st === 'bad_data' ? 'Mailing address returned (sample)' : null, source: st === 'signal' ? 'system' : 'dashboard' });
      back = Math.max(1, back - int(3, 15));
    }
  }
});

/* ── trend rows: monthly aggregates shaped like the SQL views (sample) ── */
const monthStarts: string[] = [];
for (let i = 11; i >= 0; i--) monthStarts.push(new Date(Date.UTC(2026, 10 - i, 1)).toISOString().slice(0, 10));
const scale: Record<Area, number> = { 'La Jolla': 1, 'Pacific Beach': 0.9, 'Mission Beach': 0.35 };
const trend_rows: TrendRows = { turnover: [], signals: [], upzoning: [], recipes: [] };
for (const a of areas) {
  const k = scale[a];
  monthStarts.forEach((m, i) => {
    const sales = Math.max(0, Math.round(14 * k + (a === 'Pacific Beach' ? 0.3 : -0.1) * i + (rnd() - 0.5) * 8 * k));
    trend_rows.turnover.push({ month: m, neighborhood: a, sales, sample_rows: sales });
    for (const [g, base, drift] of [['remodel_addition', 11, 0.15], ['adu', 4, 0.2], ['demolition_lot_split', 2, 0], ['pre_sale_prep', 6, 0.1]] as const) {
      const n = Math.max(0, Math.round(base * k + drift * i + (rnd() - 0.5) * 6 * k));
      trend_rows.signals.push({ month: m, neighborhood: a, signal_type: 'permit_approved', signal_group: g, signals: n, sample_rows: n });
    }
    const lost = Math.max(0, Math.round((a === 'La Jolla' ? 1 : 5 * k) + (a === 'La Jolla' ? 0 : 0.35) * i + (rnd() - 0.5) * 4 * k));
    trend_rows.signals.push({ month: m, neighborhood: a, signal_type: 'stro_license_removed', signal_group: 'stro', signals: lost, sample_rows: lost });
    const tax = Math.max(0, Math.round((a === 'La Jolla' ? 3 : 5 * k) - 0.05 * i + (rnd() - 0.5) * 2));
    trend_rows.signals.push({ month: m, neighborhood: a, signal_type: 'tax_default', signal_group: 'distress', signals: tax, sample_rows: tax });
  });
  const inHood = (apn: string) => pBy.get(apn)!.neighborhood === a;
  const parcelsWith = (f: (s: Signal) => boolean) => new Set(signals.filter((s) => inHood(s.apn) && f(s)).map((s) => s.apn)).size;
  const sb9 = parcelsWith((s) => s.signal_type === 'sb9_lot_split_estimate');
  const q = parcelsWith((s) => s.signal_type === 'sb79_transit_estimate' && s.details?.distance_band === 'within_quarter_mile');
  const h = parcelsWith((s) => s.signal_type === 'sb79_transit_estimate');
  trend_rows.upzoning.push({ neighborhood: a, sb9, sb79_quarter_mile: q, sb79_half_mile: h, sample_rows: sb9 + h });
  const cnt = new Map<string, number>();
  for (const sc of scores) if (inHood(sc.apn)) for (const r of sc.recipe_matches ?? []) cnt.set(r, (cnt.get(r) ?? 0) + 1);
  for (const [recipe, parcelsN] of cnt) trend_rows.recipes.push({ neighborhood: a, recipe, parcels: parcelsN, sample_rows: parcelsN });
}

const bundle: FixtureBundle = {
  generated_for: '2026-11-18', neighborhoods, parcels, source_runs, signals, owners, sales_history: sales, scores,
  suppressions, outreach, stage_events, team_members, share_links: [], trend_rows,
  backtest: {
    past_sales_considered: 64, flagged_before_listing: 38, avg_days_early: 74, median_days_early: 61,
    window: { from: '2025-11-01', to: '2026-10-31' }, is_sample: true,
    note: 'Illustrative sample numbers. The real backtest runs on ATTOM sales history in Phase 6.',
  },
};
writeFileSync(resolve(here, '../src/data/fixtures.json'), JSON.stringify(bundle));
const dist = [0, 40, 60, 80].map((t, i, a) => `${t}+:${scores.filter((s) => s.score >= t && s.score < (a[i + 1] ?? 101)).length}`);
console.log(`parcels ${parcels.length}, signals ${signals.length}, outreach ${outreach.length}, stage events ${stage_events.length}; score bands ${dist.join(' ')}; types ${new Set(signals.map((s) => s.signal_type)).size}/${Object.keys(SIGNAL_TYPES).length}; recipes matched ${new Set(scores.flatMap((s) => s.recipe_matches ?? [])).size}/${RECIPES.length}`);
void sampleSource; void phrase;
