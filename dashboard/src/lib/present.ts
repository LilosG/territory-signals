/**
 * Presentation rules shared by every page (CLAUDE.md data rules): what a card may say, how sample and estimated facts
 * are marked, how same-day permits collapse, plain labels for codes. Pure functions, no AI: only facts already in the
 * database are rephrased.
 */
import { COMPONENTS, SENSITIVE_RECIPES, SIGNAL_TYPES, signalLabel } from './data/catalog';
import type { FunnelRow, LeadDetail, LeadSummary, Signal, SignalEvent, StageValue, TopComponent } from './data/types';
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
/** Category icon for a fact chip (Icon names). */
export type ChipIcon = 'upzone' | 'permit' | 'rental' | 'tenure' | 'equity' | 'lot';
export interface Marked { text: string; sample?: boolean; estimate?: boolean; icon?: ChipIcon }

const shortDate = (s: string | null | undefined) => (s ? new Date(`${s.slice(0, 10)}T12:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' }) : '');

const isSensitiveKey = (key: string) => key.startsWith('tax_default') || key === 'owner:ownership_transfer';

/**
 * The signal that earned the parcel the most score: highest contribution, never one with zero (or less) weight, never a
 * sensitive one. Ties go to the most recent signal date. Deterministic; the same pick feeds every list and the lead header.
 */
export function topSignal(components: TopComponent[]): TopComponent | null {
  const ranked = components
    .filter((c) => c.points > 0 && !isSensitiveKey(c.key))
    .sort((a, b) => b.points - a.points || (b.signal_date ?? '').localeCompare(a.signal_date ?? ''));
  return ranked[0] ?? null;
}

/** The top-signal line for a parcel from its stored score components (raw `scores.components` JSON), or null. */
export function topSignalLine(components: unknown): Marked | null {
  const top = topSignal(((components ?? []) as Record<string, unknown>[]).filter((c) => c.kind === 'signal').map((c) => ({
    key: String(c.key), facts: (c.facts ?? null) as Record<string, unknown> | null, points: Number(c.contribution ?? 0),
    signal_date: (c.signal_date as string | null | undefined) ?? null, is_sample: !!c.is_sample, is_estimate: !!c.is_estimate })));
  return top ? componentLine(top) : null;
}

/** One line from the top-contribution signal, built only from that component's stored facts. */
export function leadHeadline(l: LeadSummary): Marked | null {
  const top = topSignal(l.top_components);
  if (top) return componentLine(top);
  const first = reasonParts(publicReason(l.score.reason_text))[0];
  return first ? { text: first.text.replace(/[.,]$/, ''), sample: first.sample, estimate: first.estimate } : null;
}

/** "2 building permits approved": the label without its parenthetical, lowercased and pluralized. */
export function pluralPermitLabel(label: string, n: number): string {
  const base = label.replace(/\s*\([^)]*\)/g, '').trim();
  const lc = base.charAt(0).toLowerCase() + base.slice(1);
  return `${n} ${/permit$/i.test(lc) ? `${lc}s` : `${lc} permits`}`;
}

function componentLine(c: TopComponent): Marked {
  const f = (c.facts ?? {}) as Record<string, unknown>;
  const date = shortDate((c.signal_date ?? (f.issue_date as string | undefined)) ?? null);
  const base = { sample: c.is_sample, estimate: c.is_estimate };
  if (c.key.startsWith('permit_approved')) {
    const n = Number(f.permit_count ?? 1);
    const label = String(f.permit_label ?? 'Permit');
    return { ...base, text: `${n > 1 ? pluralPermitLabel(label, n) : label} approved${date ? ` ${date}` : ''}` };
  }
  if (c.key === 'permit_stalled') return { ...base, text: 'Permit expired with no close date' };
  if (c.key === 'stro_license_active') return { ...base, text: `Active short-term rental license${f.tier ? ` (${f.tier})` : ''}` };
  if (c.key === 'stro_license_removed') return { ...base, text: 'Short-term rental license removed' };
  if (c.key === 'sb9_lot_split_estimate') return { ...base, text: 'SB 9 lot-split eligibility' };
  if (c.key === 'sb79_transit_estimate') return { ...base, text: 'Near transit (SB 79)' };
  if (c.key === 'fire_hazard_zone') return { ...base, text: 'In a fire hazard severity zone' };
  return { ...base, text: sentenceCase(COMPONENTS[c.key]?.label ?? c.key) };
}

/* ── recipe-scoped headline (Phase 5I) ── */
/**
 * Which stored score components belong to each recipe's qualifying criteria, in the order they are tried when contributions tie.
 * A recipe card shows only these, never the parcel's global top signal (an active STR license under "Downsizer" says nothing about
 * why the parcel is in that recipe). Tax default and ownership transfer are never listed: they are sensitive (isSensitiveKey).
 */
const RECIPE_FACT_KEYS: Record<string, { primary: string[]; secondary?: string[] }> = {
  str_exit: { primary: ['stro_license_removed'] },
  tired_landlord: { primary: ['owner:out_of_state', 'owner:absentee'], secondary: ['permit_stalled', 'stro_license_removed'] },
  builder_bait: { primary: ['sb9_lot_split_estimate', 'sb79_transit_estimate', 'permit_approved:demolition_lot_split'] },
  pre_list_prep: { primary: ['permit_approved:pre_sale_prep'] },
  stalled_project: { primary: ['permit_stalled'] },
  downsizer: { primary: ['owner:years_owned'], secondary: ['owner:mortgage_open_false'] },
  insurance_squeeze: { primary: ['fire_hazard_zone'] },
  financial_pressure: { primary: ['stro_license_removed'] },     // its other qualifier (tax default) is sensitive and never shown on a card
};

/** Any stored score component (signal or owner), as read from `scores.components`. */
function toTop(c: Record<string, unknown>): TopComponent {
  return { key: String(c.key), facts: (c.facts ?? null) as Record<string, unknown> | null, points: Number(c.contribution ?? 0),
    signal_date: (c.signal_date as string | null | undefined) ?? null, is_sample: !!c.is_sample, is_estimate: !!c.is_estimate };
}

function ownerLine(c: TopComponent): Marked {
  const f = (c.facts ?? {}) as Record<string, unknown>;
  const base = { sample: c.is_sample, estimate: c.is_estimate };
  if (c.key === 'owner:years_owned') { const n = Number(f.years_owned ?? 0); return { ...base, text: `${n} ${n === 1 ? 'year' : 'years'} owned` }; }
  if (c.key === 'owner:mortgage_open_false') return { ...base, text: 'No open mortgage' };
  if (c.key === 'owner:out_of_state') return { ...base, text: 'Out-of-state owner' };
  if (c.key === 'owner:absentee') return { ...base, text: 'Absentee owner' };
  return componentLine(c);
}
const factLine = (c: TopComponent): Marked => (c.key.startsWith('owner:') ? ownerLine(c) : componentLine(c));

/**
 * The line a lead shows inside a recipe card: the strongest stored fact that belongs to THAT recipe, from the parcel's score
 * components (raw `scores.components` JSON, signals and owner facts). Downsizer reads "26 years owned · No open mortgage" and
 * Tired landlord reads "Out-of-state owner · Permit expired with no close date". Null when the parcel stores none of the
 * recipe's facts (nothing is shown rather than an unrelated signal). Unknown recipe keys fall back to the global top signal.
 */
export function recipeSignalLine(recipeKey: string, components: unknown): Marked | null {
  const all = ((components ?? []) as Record<string, unknown>[]).map(toTop).filter((c) => !isSensitiveKey(c.key));
  const rule = RECIPE_FACT_KEYS[recipeKey];
  if (!rule) return topSignalLine(components);
  const best = (keys: string[]) => all.filter((c) => keys.includes(c.key))
    .sort((a, b) => b.points - a.points || (b.signal_date ?? '').localeCompare(a.signal_date ?? '') || keys.indexOf(a.key) - keys.indexOf(b.key))[0] ?? null;
  const first = best(rule.primary);
  const second = rule.secondary ? best(rule.secondary) : null;
  const picked = [first, second].filter((c): c is TopComponent => !!c);
  if (picked.length === 0) return null;
  if (picked.length === 1) return factLine(picked[0]!);
  const lines = picked.map(factLine);
  return { text: lines.map((l) => l.text).join(' · '), sample: lines.some((l) => l.sample), estimate: lines.some((l) => l.estimate) };
}

/** Words that mark a distress or life-event fact. A chip containing any of them is dropped, whatever built it. */
const DISTRESS_WORDS = /tax|default|transfer|probate|inherit|death|deceas|financial|pressure|foreclos|lien|divorce|trust/i;

/**
 * Up to three key facts for a card, each with a category icon. Built only from the whitelisted categories below (upzoning,
 * permit, rental, equity, tenure, owner status, lot), in that priority; owner-derived facts carry the sample flag and
 * estimates are flagged. Distress and life-event facts can never appear here (see DISTRESS_WORDS and isSensitiveKey).
 */
export function leadChips(l: LeadSummary): Marked[] {
  const sample = !!l.owner?.is_sample;
  const comps = l.top_components.filter((c) => c.points > 0 && !isSensitiveKey(c.key));
  const chips: Marked[] = [];
  const sb9 = comps.find((c) => c.key === 'sb9_lot_split_estimate');
  const sb79 = comps.find((c) => c.key === 'sb79_transit_estimate');
  if (sb9) chips.push({ text: 'SB 9 eligible', estimate: true, sample: sb9.is_sample, icon: 'upzone' });
  else if (sb79) chips.push({ text: 'SB 79 transit', estimate: true, sample: sb79.is_sample, icon: 'upzone' });
  const permit = comps.find((c) => c.key.startsWith('permit_approved'));
  if (permit) {
    const n = Number((permit.facts as Record<string, unknown> | null)?.permit_count ?? 1);
    chips.push({ text: `${n} ${n === 1 ? 'permit' : 'permits'}`, sample: permit.is_sample, icon: 'permit' });
  }
  const stro = comps.find((c) => c.key === 'stro_license_active');
  if (stro) chips.push({ text: 'STR licensed', sample: stro.is_sample, icon: 'rental' });
  if (l.owner?.est_equity != null) chips.push({ text: `${fmtUsdCompact(l.owner.est_equity)} equity`, estimate: true, sample, icon: 'equity' });
  if (l.years_owned != null) chips.push({ text: `${l.years_owned} ${l.years_owned === 1 ? 'year' : 'years'} owned`, sample, icon: 'tenure' });
  if (l.owner?.out_of_state) chips.push({ text: 'Out-of-state owner', sample, icon: 'rental' });
  else if (l.owner?.absentee) chips.push({ text: 'Absentee owner', sample, icon: 'rental' });
  if (l.lot_sqft) chips.push({ text: `${fmtNum(Math.round(l.lot_sqft))} sq ft lot`, icon: 'lot' });
  return chips.filter((c) => !DISTRESS_WORDS.test(c.text)).slice(0, 3);
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

/* ── "new" and trends ── */
/** True when the lead's latest selling-relevant event is within the last 7 days of `now`. */
export function isNewLead(l: LeadSummary, now: Date = new Date()): boolean {
  if (!l.latest_signal_date) return false;
  const days = (now.getTime() - new Date(l.latest_signal_date).getTime()) / 86_400_000;
  return days >= 0 && days <= 7;
}

/** Week-over-week change as a computed number and short label ("+12%", "new", "no change"). Deterministic, no AI. */
export function weekDelta(thisWeek: number, lastWeek: number): { dir: 'up' | 'down' | 'flat'; label: string } {
  if (thisWeek === lastWeek) return { dir: 'flat', label: 'No change' };
  if (lastWeek === 0) return { dir: 'up', label: `+${fmtNum(thisWeek)} vs last week` };
  const pct = Math.round(((thisWeek - lastWeek) / lastWeek) * 100);
  return { dir: pct > 0 ? 'up' : 'down', label: `${pct > 0 ? '+' : ''}${pct}% vs last week` };
}

/** Weeks of history needed to judge the comparison week: this week, the comparison week, and older ones. */
const median = (xs: number[]): number => { if (!xs.length) return 0; const s = [...xs].sort((a, b) => a - b); const m = s.length >> 1; return s.length % 2 ? s[m]! : (s[m - 1]! + s[m]!) / 2; };

/**
 * Does the comparison week (the 7 days before this week) contain the initial data load for this metric? Then a week-over-week
 * percentage compares a real week with a one-off import and means nothing. Two tests, both deterministic:
 *  1. the metric's first data day (first pull of its sources, first draft or outcome) falls in the comparison week, or
 *  2. the comparison week is more than 5x the median of the weeks after it (the weeks since; needs a non-zero median,
 *     otherwise a quiet week after any busy one would count as an initial load).
 * `weeks` is index 0 = this week, 1 = comparison week; `firstDay` and `today` are ISO dates (YYYY-MM-DD).
 */
export function isInitialLoadWeek(weeks: number[] | undefined, firstDay: string | null | undefined, today: string): boolean {
  if (!weeks || weeks.length < 2 || !(weeks[1]! > 0)) return false;
  if (firstDay) {
    const ago = Math.floor((Date.parse(today) - Date.parse(firstDay)) / 86_400_000 / 7);
    if (ago === 1) return true;
  }
  const later = median(weeks.slice(0, 1));
  return later > 0 && weeks[1]! > 5 * later;
}

/** The Today tile's change line: "First full week" instead of a percentage when the comparison week holds the initial load. */
export function statDelta(s: { this_week: number; last_week: number; weeks?: number[]; first_day?: string | null; scoring_updated?: boolean }, today: string): { dir: 'up' | 'down' | 'flat'; label: string; firstFull: boolean; scoringUpdated?: boolean } {
  // A different scoring model in the two weeks makes the two counts incomparable: say so instead of showing a %.
  if (s.scoring_updated) return { dir: 'flat', label: 'Scoring updated', firstFull: false, scoringUpdated: true };
  if (isInitialLoadWeek(s.weeks, s.first_day, today)) return { dir: 'flat', label: 'First full week', firstFull: true };
  return { ...weekDelta(s.this_week, s.last_week), firstFull: false };
}

/** SVG polyline points for a sparkline in a w x h box. */
export function sparkPoints(values: number[], w: number, h: number, pad = 2): string {
  if (values.length === 0) return '';
  const max = Math.max(1, ...values);
  const step = values.length > 1 ? (w - pad * 2) / (values.length - 1) : 0;
  return values.map((v, i) => `${(pad + i * step).toFixed(1)},${(h - pad - (v / max) * (h - pad * 2)).toFixed(1)}`).join(' ');
}

/* ── blocked drafts ── */
/** What is missing, in words a person can act on. Reasons come from the draft generator. */
export function blockedHelp(reason: string): string {
  return reason === 'missing agent name or DRE license' ? 'Add the agent’s name and DRE license number to the team profile (ask your administrator), then prepare the drafts again.'
    : reason === 'missing office address' ? 'Add the office address to the team profile (ask your administrator), then prepare the drafts again.'
    : reason === 'sample data' ? 'This draft uses sample owner data. It can be approved once real owner data is connected (Phase 6).'
    : 'Resolve this with your administrator, then prepare the drafts again.';
}

/** The same reasons as a short label, for banners, chips and tooltips. */
export function blockedLabel(reason: string): string {
  return reason === 'missing agent name or DRE license' ? 'agent name and DRE license number missing from the team profile'
    : reason === 'missing office address' ? 'office address missing from the team profile'
    : reason === 'sample data' ? 'uses sample owner data'
    : reason;
}

/* ── lead brief ── */
/** One-line headline for the brief hero: the top-contribution signal (same pick as the lists), from its stored facts only. */
export function detailHeadline(lead: LeadDetail): Marked | null {
  const date = (id: string | null | undefined) => lead.signals.find((s) => s.id === id)?.signal_date ?? null;
  const top = topSignal((lead.score.components ?? []).filter((c) => c.kind === 'signal')
    .map((c) => ({ key: c.key, facts: c.facts ?? null, points: c.contribution, signal_date: date(c.signal_id), is_sample: c.is_sample, is_estimate: c.is_estimate })));
  if (top) return componentLine(top);
  const first = reasonParts(publicReason(lead.score.reason_text))[0];
  return first ? { text: first.text.replace(/[.,]$/, ''), sample: first.sample, estimate: first.estimate } : null;
}

/** Score components that describe tax default or ownership transfer: shown only in the brief's labeled sensitive section. */
export const isSensitiveComponent = (key: string) => key.startsWith('tax_default') || key === 'owner:ownership_transfer';

/* ── AI claims (Phase 5F) ── */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
/** Where a cited record id lives on the lead page: a signal is an entry on the Signals tab, owner and parcel facts are on the Owner tab. */
export function claimHref(id: string): string {
  if (UUID.test(id)) return `#rec-${id}`;
  if (id.startsWith('owner:')) return '#owner-h';
  if (id.startsWith('parcel:')) return '#prop-h';
  return '#why-h';
}
export function claimLabel(id: string): string {
  if (UUID.test(id)) return 'Signal record';
  if (id.startsWith('owner:')) return 'Owner record';
  if (id.startsWith('parcel:')) return 'Parcel record';
  if (id.startsWith('meaning:')) return 'What it means';
  if (id.startsWith('recipe:')) return 'Why it matches';
  return 'Score detail';
}

/* ── pipeline (Phase 5I) ── */
/** Gross commission income is estimated at 2.5% of a property's estimated value. It is an estimate everywhere it is shown. */
export const GCI_RATE = 0.025;
export const estGci = (estValue: number) => Math.round(estValue * GCI_RATE);

/** "$38k" / "$1.2M": whole thousands below a million, one decimal above. */
export function fmtGci(gci: number): string {
  if (gci >= 1_000_000) return `$${(Math.round(gci / 100_000) / 10).toString()}M`;
  return `$${Math.round(gci / 1000)}k`;
}

/**
 * The lead-card badge: "Est. $38k GCI" from the parcel's estimated value (2.5%). Null when the parcel has no estimated value,
 * so nothing is invented. `sample` is true when that value comes from sample owner data.
 */
export function gciBadge(l: Pick<LeadSummary, 'owner'>): { text: string; sample: boolean; value: number } | null {
  const v = l.owner?.est_value;
  if (v == null || !(v > 0)) return null;
  const value = estGci(v);
  return { text: `Est. ${fmtGci(value)} GCI`, sample: !!l.owner?.is_sample, value };
}

/** The sales stages in the order a lead moves through them. The data key `signal` is shown to agents as "Flagged". */
export const PIPELINE_LABELS: Record<string, string> = { signal: 'Flagged', contacted: 'Contacted', conversation: 'Conversation', appointment: 'Appointment', listing: 'Listing' };

export interface PipelineStep {
  key: string; label: string; count: number;
  /** Share of the previous stage that reached this one (0..1); null for the first stage or when the previous stage is empty. */
  rate: number | null;
  /** Estimated GCI of the parcels that reached this stage; null when none of them has an estimated value. */
  gci: number | null;
  /** Parcels at this stage with no estimated value (excluded from the GCI). */
  unvalued: number;
  sample: boolean;
}
/** Stage counts, step-to-step conversion and estimated GCI for the executive pipeline. Pure arithmetic over stored counts. */
export function pipelineSteps(overall: FunnelRow, values: StageValue[]): PipelineStep[] {
  return overall.stages.map((s, i) => {
    const v = values.find((x) => x.key === s.key);
    const prev = i > 0 ? overall.stages[i - 1]!.count : 0;
    return {
      key: s.key, label: PIPELINE_LABELS[s.key] ?? s.label, count: s.count,
      rate: i > 0 && prev > 0 ? s.count / prev : null,
      gci: v && v.valued_parcels > 0 ? estGci(v.est_value) : null,
      unvalued: v ? Math.max(0, v.parcels - v.valued_parcels) : 0,
      sample: !!v && v.sample_parcels > 0,
    };
  });
}

/* ── seller consultation dossier (Phase 5J) ── */
/** Selling costs (commissions, closing, transfer tax) as a share of estimated value: the low and high end used for the net-proceeds range. An assumption, shown on the page. */
export const SELLING_COST_RANGE = { low: 0.05, high: 0.07 } as const;

/** Estimated seller net proceeds: estimated equity less selling costs, as a low-high range. Null without both figures; never below zero. */
export function netProceedsRange(estValue: number | null | undefined, estEquity: number | null | undefined): { low: number; high: number } | null {
  if (estValue == null || estEquity == null || !(estValue > 0)) return null;
  return { low: Math.max(0, Math.round(estEquity - estValue * SELLING_COST_RANGE.high)), high: Math.max(0, Math.round(estEquity - estValue * SELLING_COST_RANGE.low)) };
}

/**
 * Neighborhood momentum for one trend metric: the sum over its (non-optional) series for the last 3 full months against the 3 before.
 * The partial current month never counts. Null when the metric is missing, empty or has an empty-state notice.
 */
export function momentum(metric: { series: { points: { month: string; value: number }[] }[]; empty_state?: string } | undefined, months: string[], partialMonth: string): { recent: number; prior: number; pct: number | null } | null {
  if (!metric || metric.empty_state) return null;
  const full = months.filter((m) => m !== partialMonth);
  const last3 = full.slice(-3); const prev3 = full.slice(-6, -3);
  const total = (ms: string[]) => metric.series.reduce((t, s) => t + s.points.filter((p) => ms.includes(p.month)).reduce((u, p) => u + p.value, 0), 0);
  const recent = total(last3); const prior = total(prev3);
  return { recent, prior, pct: prior > 0 ? Math.round(((recent - prior) / prior) * 100) : null };
}
