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
  ScoreComponent, Suppression, Outreach, Outcome, TeamMember, ClientConfig,
} from '../src/lib/data/types';
import { SIGNAL_TYPES, SIGNAL_GROUPS } from '../src/lib/data/catalog';

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

/* ── source runs ── */
const SRC_KEYS = ['sangis_parcels', 'stro_licenses', 'dsd_permits', 'treasurer_tax_defaults', 'sandag_zoning', 'sandag_transit', 'sandag_planning_areas', 'attom_recorder', 'attom_owner'];
const source_runs: SourceRun[] = [];
const latestRun: Record<string, string> = {};
for (const key of SRC_KEYS) {
  for (const back of [6, 3, 0]) {
    const start = new Date(TODAY.getTime() - back * dayMs - 8 * 3600_000 + int(0, 50) * 60_000);
    const failed = (key === 'sandag_transit' && back === 0) || (key === 'treasurer_tax_defaults' && back === 6);
    const fetched = key === 'sangis_parcels' ? 180 : int(40, 600);
    const matched = failed ? null : Math.round(fetched * between(0.82, 0.97));
    const run: SourceRun = {
      id: uuid(), source_key: key, started_at: iso(start),
      finished_at: iso(new Date(start.getTime() + int(20, 400) * 1000)),
      status: failed ? 'failed' : 'success',
      rows_fetched: failed ? null : fetched, rows_matched: matched,
      rows_unmatched: failed ? null : fetched - matched!,
      error_message: failed ? 'HTTP 503 from upstream host (sample error)' : null,
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
    sales.push({ id: uuid(), apn: p.apn, sale_date: dateStr(earlier), sale_price: round(price / Math.pow(1.065, 7), 1000), doc_type: 'Grant deed', provider: 'sample', is_sample: true, created_at: created });
  }
  sales.push({ id: uuid(), apn: p.apn, sale_date: dateStr(sale), sale_price: price, doc_type: chance(0.1) ? 'Trust transfer deed' : 'Grant deed', provider: 'sample', is_sample: true, created_at: created });
}

/* ── signals ── */
const signals: Signal[] = [];
let recIdx = 1000;
const RECIDS: Record<string, () => string> = {
  stro_licenses: () => `STRO-${int(2019, 2026)}-${String(int(1, 99999)).padStart(5, '0')}`,
  dsd_permits: () => `PMT-${int(2024, 2026)}-${String(++recIdx).padStart(6, '0')}`,
  treasurer_tax_defaults: () => `TTC-2026-${String(int(1, 9999)).padStart(4, '0')}`,
  sandag_zoning: () => `ZONE-${int(1, 3706)}`,
  sandag_transit: () => `STOP-${int(10000, 99999)}`,
  sangis_parcels: () => `PARCEL-${int(100000, 999999)}`,
  attom_recorder: () => `ATTOM-REC-${hex(10).toUpperCase()}`,
  attom_owner: () => `ATTOM-OWN-${hex(10).toUpperCase()}`,
  fire_hazard_zones: () => `FHSZ-${int(1, 999)}`,
};
const fresh = new Set<string>(); // ensure a handful of just-detected signals
function addSignal(apn: string, type: string, source_key: string, opts: { daysBack?: number; method?: Signal['match_method']; est?: boolean; details?: Record<string, unknown> } = {}) {
  const t = SIGNAL_TYPES[type]!;
  const method = opts.method ?? 'apn';
  const conf = method === 'apn' ? between(0.96, 1) : method === 'spatial' ? between(0.88, 0.95) : method === 'address' ? between(0.78, 0.9) : between(0.55, 0.75);
  const back = opts.daysBack ?? int(3, 320);
  const sd = daysAgo(back);
  const detected = back <= 1 ? new Date(TODAY.getTime() - int(1, 20) * 3600_000) : new Date(sd.getTime() + int(1, 3) * dayMs);
  signals.push({
    id: uuid(), apn, signal_type: type, signal_group: t.group, signal_date: dateStr(sd),
    detected_at: iso(detected > TODAY ? TODAY : detected), source_key, source_record_id: RECIDS[source_key]!(),
    run_id: latestRun[source_key] ?? null, confidence: Math.round(conf * 100) / 100, match_method: method,
    is_estimate: opts.est ?? false, is_sample: true, details: opts.details ?? null, created_at: iso(detected),
  });
}
/** Sample distance to the nearest transit stop (0.10 to 0.49 mi). Hash-based so the seeded random sequence is untouched. */
const sb79Distance = (apn: string) => Math.round((0.1 + (Number(apn.slice(-4)) % 40) / 100) * 100) / 100;
const PERMIT_TYPES = ['permit_addition_remodel', 'permit_addition_remodel', 'permit_adu', 'permit_new_construction', 'permit_demolition'] as const;
for (const p of parcels) {
  const { area, lot } = meta.get(p.apn)!;
  const o = ownerBy.get(p.apn)!; const years = yearsBy.get(p.apn)!;
  if (area !== 'La Jolla' && chance(0.3)) {
    addSignal(p.apn, chance(0.3) ? 'stro_license_lapsed' : 'stro_license_active', 'stro_licenses', { method: 'spatial', details: { tier: pick(['Tier 2', 'Tier 3', 'Tier 4']), status: 'sample' } });
  }
  if (chance(0.3)) { const pt = pick(PERMIT_TYPES); addSignal(p.apn, pt, 'dsd_permits', { method: chance(0.9) ? 'apn' : 'address', details: { approval_type: pt.replace('permit_', '').replace('_', ' ') } }); }
  if (chance(0.05)) addSignal(p.apn, 'tax_default', 'treasurer_tax_defaults', { details: { list: '2026 Impending Power to Sell (sample)' } });
  if (lot >= 4500 && p.zoning?.startsWith('RS') && chance(0.4)) addSignal(p.apn, 'upzoning_sb9', 'sandag_zoning', { method: 'spatial', est: true, details: { screen: 'zoning + lot size (in-house, unofficial)' } });
  if (area === 'Pacific Beach' && chance(0.18)) addSignal(p.apn, 'upzoning_sb79', 'sandag_transit', { method: 'spatial', est: true, details: { screen: 'stop proximity (in-house, unofficial)', distance_miles: sb79Distance(p.apn) } });
  if (area === 'La Jolla' && chance(0.1)) addSignal(p.apn, 'fire_hazard_zone', 'fire_hazard_zones', { method: 'spatial', daysBack: int(60, 300) });
  if (chance(0.15)) addSignal(p.apn, 'recorded_document', 'sangis_parcels', { details: { note: 'Last recorded document date, not a purchase date' } });
  // Phase 6 (owner-data-derived) signals
  if (years >= 15) addSignal(p.apn, 'long_tenure', 'attom_owner', { daysBack: int(6, 60), details: { years_owned: Math.round(years) } });
  if (o.absentee) addSignal(p.apn, 'absentee_owner', 'attom_owner', { daysBack: int(6, 60) });
  if ((o.est_equity ?? 0) / (o.est_value ?? 1) >= 0.75) addSignal(p.apn, 'high_equity', 'attom_owner', { daysBack: int(6, 60) });
  if (chance(0.05)) addSignal(p.apn, 'inheritance_transfer', 'attom_recorder', { daysBack: int(10, 200) });
  if (chance(0.06)) addSignal(p.apn, 'trust_transfer', 'attom_recorder', { daysBack: int(10, 300) });
  if (chance(0.025)) addSignal(p.apn, 'notice_of_default', 'attom_recorder', { daysBack: int(5, 120) });
}
// guarantee a few signals detected in the last 24 hours
const freshTypes = ['permit_adu', 'stro_license_lapsed', 'tax_default', 'inheritance_transfer', 'permit_demolition', 'upzoning_sb9'];
freshTypes.forEach((t, i) => {
  const p = parcels[i * 23 + 5]!;
  const src = SIGNAL_TYPES[t]!.phase === 6 ? 'attom_recorder' : t.startsWith('stro') ? 'stro_licenses' : t.startsWith('permit') ? 'dsd_permits' : t.startsWith('tax') ? 'treasurer_tax_defaults' : 'sandag_zoning';
  addSignal(p.apn, t, src, { daysBack: 0, method: 'apn', est: t.startsWith('upzoning') });
  fresh.add(p.apn);
});

/* ── scoring (deterministic) ── */
const RECIPES = [
  { key: 'long-tenure-equity', name: 'Long tenure, high equity', description: 'Owned 15+ years with 60%+ estimated equity.', enabled: true },
  { key: 'absentee-owner', name: 'Absentee owner', description: 'Mailing address differs from the property; owned 7+ years.', enabled: true },
  { key: 'redevelopment', name: 'Redevelopment candidate', description: 'Estimated upzoning eligibility on an older building, or a demolition permit.', enabled: true },
  { key: 'str-exit', name: 'Short-term rental exit', description: 'A short-term rental license was lost.', enabled: true },
  { key: 'life-event', name: 'Life event', description: 'Inheritance or trust transfer on record (ATTOM recorder data).', enabled: true },
  { key: 'financial-stress', name: 'Financial stress', description: 'Tax-defaulted or a notice of default.', enabled: true },
  { key: 'permit-momentum', name: 'Permit momentum', description: 'Recent permit activity on a property owned 10+ years.', enabled: false },
];
const monthYear = (s: string | null) => s ? new Date(s + 'T00:00:00Z').toLocaleDateString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' }) : '';
const byApn = new Map<string, Signal[]>();
for (const s of signals) (byApn.get(s.apn) ?? byApn.set(s.apn, []).get(s.apn)!).push(s);

const scores: Score[] = [];
for (const p of parcels) {
  const o = ownerBy.get(p.apn)!; const years = yearsBy.get(p.apn)!;
  const sigs = byApn.get(p.apn) ?? [];
  const has = (t: string) => sigs.filter((s) => s.signal_type === t);
  const ids = (xs: Signal[]) => xs.map((s) => s.id);
  const ratio = (o.est_equity ?? 0) / (o.est_value ?? 1);
  const items: ScoreComponent[] = [];
  const W = 1.4; // component weight scale; total is clamped to 100
  const add = (key: string, label: string, points: number, max: number, evidence: string[]) => items.push({ key, label, points: Math.round(points * W), max: Math.round(max * W), evidence });
  add('tenure', 'Years owned', years >= 25 ? 20 : years >= 15 ? 14 : years >= 10 ? 8 : 0, 20, [`owners:${o.id}`]);
  add('equity', 'Estimated equity', ratio >= 0.8 ? 15 : ratio >= 0.6 ? 10 : ratio >= 0.4 ? 5 : 0, 15, [`owners:${o.id}`]);
  add('ownership', 'Absentee / out of state', (o.absentee ? 6 : 0) + (o.out_of_state ? 4 : 0), 10, [`owners:${o.id}`]);
  const permits = sigs.filter((s) => s.signal_group === 'permits');
  add('permits', 'Permit activity', permits.some((s) => ['permit_demolition', 'permit_new_construction'].includes(s.signal_type)) ? 15 : permits.some((s) => s.signal_type === 'permit_adu') ? 10 : permits.length ? 8 : 0, 15, ids(permits));
  const stro = has('stro_license_lapsed');
  add('str', 'Short-term rental change', stro.length ? 10 : has('stro_license_active').length ? 3 : 0, 10, ids([...stro, ...has('stro_license_active')]));
  const up = sigs.filter((s) => s.signal_group === 'upzoning');
  add('upzoning', 'Upzoning (estimated)', Math.min(10, up.length * 5), 10, ids(up));
  const dist = [...has('tax_default'), ...has('notice_of_default')];
  add('distress', 'Financial distress', has('notice_of_default').length ? 15 : has('tax_default').length ? 10 : 0, 15, ids(dist));
  const life = [...has('inheritance_transfer'), ...has('trust_transfer')];
  add('life_event', 'Life event', has('inheritance_transfer').length ? 15 : has('trust_transfer').length ? 8 : 0, 15, ids(life));
  const recent = sigs.some((s) => (TODAY.getTime() - new Date(s.signal_date!).getTime()) / dayMs <= 30);
  const recent90 = sigs.some((s) => (TODAY.getTime() - new Date(s.signal_date!).getTime()) / dayMs <= 90);
  add('recency', 'Recent activity', recent ? 5 : recent90 ? 3 : 0, 5, []);
  const total = Math.min(100, items.reduce((a, c) => a + c.points, 0));

  const matches: string[] = [];
  const anyUp = up.length > 0;
  if (years >= 15 && ratio >= 0.6) matches.push('long-tenure-equity');
  if (o.absentee && years >= 7) matches.push('absentee-owner');
  if ((anyUp && (p.year_built ?? 2000) < 1980) || has('permit_demolition').length) matches.push('redevelopment');
  if (stro.length) matches.push('str-exit');
  if (life.length) matches.push('life-event');
  if (dist.length) matches.push('financial-stress');
  if (permits.length && years >= 10) matches.push('permit-momentum');

  // reason_text: deterministic, built only from stored facts
  const parts: string[] = [];
  const top = [...items].sort((a, b) => b.points - a.points).filter((i) => i.points > 0).slice(0, 3);
  for (const c of top) {
    if (c.key === 'tenure') parts.push(`owned ${Math.round(years)} years`);
    else if (c.key === 'equity') parts.push(ratio >= 0.99 ? 'no open mortgage (estimated free and clear)' : `about ${Math.round(ratio * 100)}% estimated equity`);
    else if (c.key === 'ownership') parts.push(o.out_of_state ? 'out-of-state owner' : 'absentee owner');
    else if (c.key === 'permits') parts.push(`${permits[0]!.signal_type.replace('permit_', '').replace('_', ' ')} permit (${monthYear(permits[0]!.signal_date)})`);
    else if (c.key === 'str') parts.push(stro.length ? `short-term rental license lost (${monthYear(stro[0]!.signal_date)})` : 'active short-term rental');
    else if (c.key === 'upzoning') parts.push('estimated upzoning eligibility');
    else if (c.key === 'distress') parts.push(has('notice_of_default').length ? 'notice of default on record' : 'on the tax-default list');
    else if (c.key === 'life_event') parts.push(has('inheritance_transfer').length ? 'inheritance transfer on record' : 'trust transfer on record');
    else if (c.key === 'recency') parts.push('new activity in the last 30 days');
  }
  const reason = parts.length ? parts.join('; ').replace(/^./, (c) => c.toUpperCase()) + '.' : 'No strong signals yet.';
  scores.push({
    id: uuid(), apn: p.apn, score: total, components: { items }, reason_text: reason,
    recipe_matches: matches, model_version: 'sample-v0', scored_at: '2026-11-18T05:30:00.000Z', created_at: '2026-11-18T05:30:00.000Z',
  });
}

/* ── team, suppressions, outreach, outcomes ── */
const team_members: TeamMember[] = [
  { id: uuid(), email: 'owner@example.com', name: 'Sample Principal', role: 'owner', created_at: created },
  { id: uuid(), email: 'agent.one@example.com', name: 'Sample Agent One', role: 'agent', created_at: created },
  { id: uuid(), email: 'agent.two@example.com', name: 'Sample Agent Two', role: 'agent', created_at: created },
  { id: uuid(), email: 'assistant@example.com', name: 'Sample Assistant', role: 'assistant', created_at: created },
];
const ranked = [...scores].sort((a, b) => b.score - a.score || a.apn.localeCompare(b.apn));
const suppressions: Suppression[] = ranked.slice(3, 7).map((s, i) => ({
  id: uuid(), apn: s.apn, reason: ['Owner asked not to be contacted (sample)', 'Recently listed with another agent (sample)', 'Do-not-contact list (sample)', 'Under contract (sample)'][i]!,
  until_date: i % 2 ? dateStr(daysAgo(-90)) : null, created_at: created,
}));
const suppressed = new Set(suppressions.map((s) => s.apn));

const pBy = new Map(parcels.map((p) => [p.apn, p]));
const outreach: Outreach[] = [];
const outcomes: Outcome[] = [];
const sigBy = (apn: string) => byApn.get(apn) ?? [];
const factsFor = (apn: string) => {
  const o = ownerBy.get(apn)!; const facts: NonNullable<Outreach['source_facts']>['facts'] = [];
  facts.push({ text: `Owned about ${Math.round(yearsBy.get(apn)!)} years (last sale ${o.last_sale_date})`, source_key: 'attom_owner', source_record_id: `owners:${o.id}` });
  for (const s of sigBy(apn).slice(0, 3)) facts.push({ text: SIGNAL_TYPES[s.signal_type]!.label + (s.signal_date ? ` (${monthYear(s.signal_date)})` : ''), source_key: s.source_key, source_record_id: s.source_record_id });
  return facts;
};
ranked.slice(0, 45).forEach((s, idx) => {
  if (suppressed.has(s.apn)) return;
  const p = pBy.get(s.apn)!; const facts = factsFor(s.apn);
  const yrs = Math.round(yearsBy.get(s.apn)!);
  const hook = (s.reason_text ?? '').replace(/\.$/, '');
  const letter = `Dear Sample Owner ${s.apn.slice(-4)},\n\n[SAMPLE DRAFT. Not sent. Requires human approval.]\n\nI'm writing as a neighbor and local specialist. Public records show you have owned ${p.situs_address} for about ${yrs} years, and homes in ${p.neighborhood} have been in steady demand. I'd be glad to share a no-obligation view of what your property might achieve in today's market, whenever the timing suits you.\n\nWarm regards,\nThe Kaiser Team`;
  const email = `Subject: A quick note about ${p.situs_address}\n\nHello,\n\n[SAMPLE DRAFT. Not sent. Requires human approval.]\n\nI work with homeowners in ${p.neighborhood} and noticed your home has been in your family for about ${yrs} years. If it would be useful, I can send a short, private market snapshot for your street. No obligation at all.\n\nBest,\nThe Kaiser Team`;
  const call = `CALL TASK (manual; no automated calls)\nWhy now: ${hook}.\nOpen with: introduce yourself as a ${p.neighborhood} specialist; ask permission to share a market snapshot.\nDo not mention: equity figures or private records.\nRecord the result as an outcome after the call.`;
  const mkStatus = (): Outreach['status'] => idx < 8 ? 'awaiting_approval' : idx < 14 ? 'approved' : idx < 20 ? 'sent' : 'draft';
  const mailStatus = mkStatus();
  outreach.push({ id: uuid(), apn: s.apn, channel: 'mail', status: mailStatus, content: letter, source_facts: { facts }, approved_by: mailStatus === 'approved' || mailStatus === 'sent' ? 'owner@example.com' : null, sent_at: mailStatus === 'sent' ? iso(daysAgo(int(3, 30))) : null, created_at: iso(daysAgo(int(1, 40))) });
  outreach.push({ id: uuid(), apn: s.apn, channel: 'email', status: idx % 3 === 0 && idx < 14 ? 'awaiting_approval' : 'draft', content: email, source_facts: { facts }, approved_by: null, sent_at: null, created_at: iso(daysAgo(int(1, 20))) });
  outreach.push({ id: uuid(), apn: s.apn, channel: 'call_task', status: idx % 4 === 0 ? 'approved' : 'draft', content: call, source_facts: { facts }, approved_by: idx % 4 === 0 ? 'assistant@example.com' : null, sent_at: null, created_at: iso(daysAgo(int(0, 10))) });
  // outcomes (cumulative stages)
  const agent = pick(team_members.filter((t) => t.role === 'agent'));
  if (idx >= 8 && idx < 38) {
    const seq: Outcome['status'][] = ['contacted'];
    if (chance(0.62)) seq.push('conversation');
    if (seq.length > 1 && chance(0.5)) seq.push('appointment');
    if (seq.length > 2 && chance(0.4)) seq.push('listing');
    if (chance(0.12)) seq.push(chance(0.5) ? 'not_interested' : 'bad_data');
    let back = int(20, 90);
    for (const st of seq) {
      outcomes.push({ id: uuid(), apn: s.apn, team_member_email: agent.email, status: st, noted_at: iso(daysAgo(back)), note: st === 'bad_data' ? 'Mailing address returned (sample)' : null, created_at: iso(daysAgo(back)) });
      back = Math.max(1, back - int(3, 15));
    }
  }
});

/* ── trends (territory-level monthly aggregates, sample) ── */
const months: string[] = [];
for (let i = 11; i >= 0; i--) { const d = new Date(Date.UTC(2026, 10 - i, 1)); months.push(d.toISOString().slice(0, 7)); }
const series = (base: number, amp: number, drift: number) => months.map((_, i) => Math.max(0, Math.round(base + drift * i + (rnd() - 0.5) * 2 * amp)));
const trends: FixtureBundle['trends'] = {};
const scale: Record<Area, number> = { 'La Jolla': 1, 'Pacific Beach': 0.9, 'Mission Beach': 0.35 };
for (const a of areas) {
  const k = scale[a];
  const cum = (xs: number[]) => { let t = int(20, 40) * k; return xs.map((x) => (t = Math.round(t + x))); };
  trends[a] = {
    months,
    raw: {
      turnover: { Sales: series(14 * k, 4 * k, a === 'Pacific Beach' ? 0.3 : -0.1) },
      permits: {
        permit_new_construction: series(3 * k, 1.5 * k, 0.05), permit_addition_remodel: series(11 * k, 3 * k, 0.15),
        permit_adu: series(4 * k, 1.5 * k, 0.2), permit_demolition: series(2 * k, 1.2 * k, 0),
      },
      str_lost: { 'Licenses lost': series(a === 'La Jolla' ? 1 : 5 * k, 2 * k, a === 'La Jolla' ? 0 : 0.35) },
      tax_default: { 'Tax-defaulted parcels': series(a === 'La Jolla' ? 15 : 24 * k, 2, -0.2) },
      upzoning: { 'Eligible parcels (estimated)': cum(series(3 * k, 1.5 * k, 0.1)) },
    },
  };
}

const config: ClientConfig = {
  client_id: 'kaiser-team', display_name: 'The Kaiser Team',
  territory: { planning_areas: [...areas], zips: ['92037', '92109'], neighborhoods: [...areas] },
  owner_data_provider: 'sample',
  outreach: { mode: 'preview', weekly_send_cap: 40, daily_send_cap: 10 },
  recipes: RECIPES, team_members: team_members.map(({ email, name, role }) => ({ email, name, role })),
  is_sample: true,
};

const bundle: FixtureBundle = {
  generated_for: '2026-11-18', neighborhoods, parcels, source_runs, signals, owners, sales_history: sales, scores,
  suppressions, outreach, outcomes, team_members, trends,
  backtest: {
    past_sales_considered: 64, flagged_before_listing: 38, avg_days_early: 74, median_days_early: 61,
    window: { from: '2025-11-01', to: '2026-10-31' }, is_sample: true,
    note: 'Illustrative sample numbers. The real backtest runs on ATTOM sales history in Phase 6.',
  },
  config,
};
writeFileSync(resolve(here, '../src/data/fixtures.json'), JSON.stringify(bundle));
const dist = [0, 40, 60, 80].map((t, i, a) => `${t}+:${scores.filter((s) => s.score >= t && s.score < (a[i + 1] ?? 101)).length}`);
console.log(`parcels ${parcels.length}, signals ${signals.length}, outreach ${outreach.length}, outcomes ${outcomes.length}; score bands ${dist.join(' ')}; types ${new Set(signals.map((s) => s.signal_type)).size}/${Object.keys(SIGNAL_TYPES).length}; groups ${Object.keys(SIGNAL_GROUPS).length}`);
