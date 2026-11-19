/**
 * Presentation rules shared by every page (CLAUDE.md data rules): what a card may say, how sample and estimated facts
 * are marked, how same-day permits collapse, plain labels for codes. Pure functions, no AI: only facts already in the
 * database are rephrased.
 */
import { COMPONENTS, SENSITIVE_RECIPES, SIGNAL_TYPES, signalLabel } from './data/catalog';
import type { LeadSummary, Signal, SignalEvent, TopComponent } from './data/types';
import { fmtDate, fmtNum, fmtUsdCompact, sentenceCase } from './format';

/* ── reason text ── */
export interface ReasonPart { text: string; sample?: boolean; estimate?: boolean }
const SUFFIX = / \((sample data, estimated|sample data|estimated)\)/g;

/**
 * Splits reason text into plain parts and marked parts. The scorer ends a sample-derived fact with "(sample data)" and an
 * estimate with "(estimated)"; those suffixes are removed and the fact they close is returned flagged instead.
 */
export function reasonParts(text: string | null | undefined): ReasonPart[] {
  const t = sentenceCase(text ?? '');
  const out: ReasonPart[] = [];
  let prev = 0;
  for (const m of t.matchAll(SUFFIX)) {
    const i = m.index!;
    const comma = t.lastIndexOf(', ', i - 1);
    const start = comma >= prev ? comma + 2 : prev;
    if (start > prev) out.push({ text: t.slice(prev, start) });
    out.push({ text: t.slice(start, i), sample: m[1]!.startsWith('sample'), estimate: m[1]!.endsWith('estimated') });
    prev = i + m[0].length;
  }
  if (prev < t.length) out.push({ text: t.slice(prev) });
  return out;
}

const SENSITIVE_PHRASES = [
  /,?\s*on the [^,.]*power-to-sell notice/gi,
  /(?:^|,\s*)[^,.]*tax[- ]default(?:ed)?[^,.]*/gi,
  /(?:^|,\s*)[^,.]*(?:ownership transfer|transfer of ownership|probate|inherit|death)[^,.]*/gi,
  /(?:^|,\s*)[^,.]*financial pressure[^,.]*/gi,
];
/** Reason text without anything about tax default, ownership transfer or financial pressure (for lead cards and lists). */
export function publicReason(text: string | null | undefined): string {
  let t = text ?? '';
  for (const re of SENSITIVE_PHRASES) t = t.replace(re, '');
  t = t.replace(/^\s*,\s*/, '').replace(/,\s*,/g, ',').replace(/\s+,/g, ',').replace(/,\s*\./g, '.').trim();
  return t ? sentenceCase(t.charAt(0).toUpperCase() + t.slice(1)) : '';
}

/* ── lead card pieces ── */
export interface Marked { text: string; sample?: boolean; estimate?: boolean }

const shortDate = (s: string | null | undefined) => (s ? new Date(`${s.slice(0, 10)}T12:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' }) : '');

/** One line from the largest non-sensitive signal component, built only from that component's stored facts. */
export function leadHeadline(l: LeadSummary): Marked | null {
  const top = l.top_components.find((c) => !c.key.startsWith('tax_default') && c.key !== 'owner:ownership_transfer');
  if (top) return componentLine(top);
  const first = reasonParts(publicReason(l.score.reason_text))[0];
  return first ? { text: first.text.replace(/[.,]$/, ''), sample: first.sample, estimate: first.estimate } : null;
}

function componentLine(c: TopComponent): Marked {
  const f = (c.facts ?? {}) as Record<string, unknown>;
  const date = shortDate((c.signal_date ?? (f.issue_date as string | undefined)) ?? null);
  const base = { sample: c.is_sample, estimate: c.is_estimate };
  if (c.key.startsWith('permit_approved')) {
    const n = Number(f.permit_count ?? 1);
    return { ...base, text: `${n > 1 ? `${n} ` : ''}${String(f.permit_label ?? 'Permit')}${n > 1 ? ' permits' : ''} approved${date ? ` ${date}` : ''}` };
  }
  if (c.key === 'permit_stalled') return { ...base, text: 'Permit expired with no close date' };
  if (c.key === 'stro_license_active') return { ...base, text: `Active short-term rental license${f.tier ? ` (${f.tier})` : ''}` };
  if (c.key === 'stro_license_removed') return { ...base, text: 'Short-term rental license removed' };
  if (c.key === 'sb9_lot_split_estimate') return { ...base, text: 'SB 9 lot-split eligibility' };
  if (c.key === 'sb79_transit_estimate') return { ...base, text: 'Near transit (SB 79)' };
  if (c.key === 'fire_hazard_zone') return { ...base, text: 'In a fire hazard severity zone' };
  return { ...base, text: sentenceCase(COMPONENTS[c.key]?.label ?? c.key) };
}

/** Up to three key facts for a card. Owner-derived facts carry the sample flag; equity is always an estimate. */
export function leadChips(l: LeadSummary): Marked[] {
  const sample = !!l.owner?.is_sample;
  const chips: Marked[] = [];
  if (l.years_owned != null) chips.push({ text: `${l.years_owned} ${l.years_owned === 1 ? 'year' : 'years'} owned`, sample });
  if (l.lot_sqft) chips.push({ text: `${fmtNum(Math.round(l.lot_sqft))} sq ft lot` });
  if (l.owner?.est_equity != null) chips.push({ text: `${fmtUsdCompact(l.owner.est_equity)} equity`, estimate: true, sample });
  if (l.owner?.out_of_state) chips.push({ text: 'Out-of-state owner', sample });
  else if (l.owner?.absentee) chips.push({ text: 'Absentee owner', sample });
  return chips.slice(0, 3);
}

/** Recipe keys a card or list may show (distress recipes are hidden). */
export const publicRecipes = (keys: string[]) => keys.filter((k) => !SENSITIVE_RECIPES.has(k));

/* ── signals ── */
/** Same-day signals of one kind on a parcel become one event with a count. Input order (newest first) is kept. */
export function collapseSignals(signals: Signal[]): { event: SignalEvent; items: Signal[] }[] {
  const groups = new Map<string, Signal[]>();
  for (const s of signals) {
    if (!s.signal_date) continue;
    const k = `${s.apn}|${s.signal_type}|${s.signal_group}|${s.signal_date}`;
    (groups.get(k) ?? groups.set(k, []).get(k)!).push(s);
  }
  return [...groups.values()].map((items) => {
    const f = items[0]!;
    return {
      items,
      event: {
        apn: f.apn, situs_address: null, neighborhood: null, type: f.signal_type, group: f.signal_group, date: f.signal_date!,
        count: items.length, is_sample: items.some((i) => i.is_sample), is_estimate: items.some((i) => i.is_estimate),
        source_key: f.source_key, source_record_id: f.source_record_id, details: f.details,
      },
    };
  });
}

/** Title of an event: "6 permits approved Nov 10, 2026" for a merged one, otherwise the plain signal label. */
export function eventTitle(e: SignalEvent, withDate = true): string {
  if (e.count > 1 && (e.type === 'permit_approved' || e.type === 'permit_stalled')) {
    return `${e.count} permits ${e.type === 'permit_approved' ? 'approved' : 'expired'}${withDate ? ` ${fmtDate(e.date)}` : ''}`;
  }
  return sentenceCase(signalLabel(e.type, e.details)).replace(/ \(estimated\)$/, '');
}

export const signalTypeLabel = (t: string) => sentenceCase(SIGNAL_TYPES[t] ?? t).replace(/ \(estimated\)$/, '');

/* ── transfers ── */
const TRANSFER_DOCS = new Set([
  'transfer on death deed', 'deed of distribution', "executor's deed", 'affidavit of death of joint tenant',
  'certificate of death', 'trust transfer deed', "trustee's deed", 'certification of trust',
]);
/** A recorded document type for display: transfers by death, trust or inheritance read "Ownership transfer" (no death wording). */
export function docTypeLabel(t: string | null | undefined): string | null {
  const k = (t ?? '').toLowerCase().replace(/\s+/g, ' ').trim();
  if (!k) return null;
  if (TRANSFER_DOCS.has(k)) return 'Ownership transfer';
  return sentenceCase(k);
}
export const isTransferDoc = (t: string | null | undefined) => TRANSFER_DOCS.has((t ?? '').toLowerCase().replace(/\s+/g, ' ').trim());

/* ── money and equity ── */
export const fmtUsdOrNull = (n: number | null | undefined) => (n == null ? null : fmtUsdCompact(n));
