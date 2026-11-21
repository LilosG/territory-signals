/**
 * Unit tests for the deterministic presentation rules in present.ts. Run: npm run test:unit  (node:test through tsx).
 * Phase 5G: the Today stat tiles must never show a week-over-week % against the initial data load.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { isInitialLoadWeek, statDelta, weekDelta, claimLabel, recipeSignalLine, pipelineSteps, estGci } from './present.ts';

const TODAY = '2026-11-25';

// weeks: index 0 = this week (last 7 days), 1 = the comparison week, 2.. older
test('the first week a source delivered data is the initial load: no %, "First full week"', () => {
  // first pull on 2026-11-18, the 7-day comparison week is 2026-11-12..2026-11-18
  const s = { this_week: 6, last_week: 54, weeks: [6, 54, 0, 0, 0], first_day: '2026-11-18' };
  assert.equal(isInitialLoadWeek(s.weeks, s.first_day, TODAY), true);
  const d = statDelta(s, TODAY);
  assert.deepEqual(d, { dir: 'flat', label: 'First full week', firstFull: true });
  assert.doesNotMatch(d.label, /%/);
});

test('a comparison week more than 5x the median of the later weeks is the initial load', () => {
  assert.equal(isInitialLoadWeek([20, 120, 30, 28], '2026-01-01', TODAY), true);       // 120 > 5 x 20
  assert.equal(statDelta({ this_week: 20, last_week: 120, weeks: [20, 120, 30], first_day: '2026-01-01' }, TODAY).label, 'First full week');
  assert.equal(isInitialLoadWeek([20, 100, 30], '2026-01-01', TODAY), false);          // 100 is exactly 5x, not more than
  assert.equal(isInitialLoadWeek([20, 101, 30], '2026-01-01', TODAY), true);
});

test('an ordinary week-over-week change keeps its percentage', () => {
  const s = { this_week: 66, last_week: 60, weeks: [66, 60, 58, 51], first_day: '2026-05-01' };
  assert.equal(isInitialLoadWeek(s.weeks, s.first_day, TODAY), false);
  assert.deepEqual(statDelta(s, TODAY), { dir: 'up', label: '+10% vs last week', firstFull: false });
  assert.equal(statDelta({ this_week: 5, last_week: 10, weeks: [5, 10, 9], first_day: null }, TODAY).label, '-50% vs last week');
  assert.equal(statDelta({ this_week: 7, last_week: 7 }, TODAY).label, 'No change');
});

test('a quiet week after a busy one is not mistaken for an initial load (the median must be above zero)', () => {
  assert.equal(isInitialLoadWeek([0, 90, 80], '2026-01-01', TODAY), false);
  assert.equal(statDelta({ this_week: 0, last_week: 90, weeks: [0, 90, 80], first_day: '2026-01-01' }, TODAY).label, '-100% vs last week');
});

test('nothing in the comparison week, no history, or a first day that is not in the comparison week: nothing to hide', () => {
  assert.equal(isInitialLoadWeek([50, 0, 0], '2026-11-25', TODAY), false);             // data started this week: existing "+N" label
  assert.equal(statDelta({ this_week: 50, last_week: 0, weeks: [50, 0, 0], first_day: '2026-11-25' }, TODAY).label, '+50 vs last week');
  assert.equal(isInitialLoadWeek(undefined, null, TODAY), false);
  assert.equal(isInitialLoadWeek([5], null, TODAY), false);
  assert.equal(isInitialLoadWeek([6, 20, 50], '2026-10-01', TODAY), false);            // first data was long before the comparison week, 20 is not > 5 x 6
});

test('week boundaries: the first day counts when it falls anywhere in the 7 days before this week', () => {
  assert.equal(isInitialLoadWeek([5, 9, 0], '2026-11-18', '2026-11-25'), true);        // 7 days ago: comparison week
  assert.equal(isInitialLoadWeek([5, 9, 0], '2026-11-12', '2026-11-25'), true);        // 13 days ago: comparison week
  assert.equal(isInitialLoadWeek([5, 9, 0], '2026-11-11', '2026-11-25'), false);       // 14 days ago: older
  assert.equal(isInitialLoadWeek([5, 9, 0], '2026-11-19', '2026-11-25'), false);       // 6 days ago: this week
});

test('weekDelta is unchanged', () => {
  assert.equal(weekDelta(3, 3).label, 'No change');
  assert.equal(weekDelta(4, 0).label, '+4 vs last week');
});

test('AI claim labels for the new explanation records', () => {
  assert.equal(claimLabel('meaning:permit_approved:pre_sale_prep'), 'What it means');
  assert.equal(claimLabel('recipe:builder_bait'), 'Why it matches');
  assert.equal(claimLabel('owner:years_owned'), 'Owner record');
});

/* ── Phase 5H: top signal line ── */
import { detailHeadline, leadHeadline, pluralPermitLabel, topSignal, topSignalLine } from './present.ts';
import type { LeadSummary, TopComponent } from './data/types.ts';

const BLDG = 'Building permit (remodel, addition or new construction)';
const comp = (key: string, points: number, date: string | null, facts: Record<string, unknown> = {}): TopComponent =>
  ({ key, facts, points, signal_date: date, is_sample: false, is_estimate: false });
const lead = (top_components: TopComponent[]) => ({ top_components, score: { reason_text: 'Heating, cooling or mechanical work approved Nov 10, 2026' } }) as unknown as LeadSummary;

test('1505 Felspar St: the line is the building permits, never the heating, cooling or mechanical permit', () => {
  // v0.4.1 components of 1505 Felspar St (the mechanical permits are ADU work now, grouped with the building permits)
  const felspar = [
    comp('permit_approved:adu', 9.1411, '2026-11-10', { permit_label: BLDG, permit_count: 2, issue_date: '2026-11-10' }),
    comp('permit_approved:remodel_addition', 7.3129, '2026-11-10', { permit_label: BLDG, permit_count: 1 }),
  ];
  const h = leadHeadline(lead(felspar))!;
  assert.equal(h.text, '2 building permits approved Nov 10');
  assert.doesNotMatch(h.text, /heating|mechanical/i);
});

test('the highest contribution wins, whatever the order of the list', () => {
  const a = comp('stro_license_active', 12, '2026-11-01'); const b = comp('permit_approved:adu', 15, '2026-10-01', { permit_label: 'Demolition', permit_count: 1 });
  assert.equal(topSignal([a, b])!.key, 'permit_approved:adu');
  assert.equal(topSignal([b, a])!.key, 'permit_approved:adu');
});

test('a zero-weight signal is never shown, even when it is the only one', () => {
  const maint = comp('permit_approved:maintenance', 0, '2026-11-10', { permit_label: 'Heating, cooling or mechanical work', permit_count: 1 });
  assert.equal(topSignal([maint]), null);
  const h = leadHeadline(lead([maint, comp('sb9_lot_split_estimate', 5, '2026-11-01')]))!;
  assert.equal(h.text, 'SB 9 lot-split eligibility');
});

test('a tie goes to the most recent signal', () => {
  const older = comp('stro_license_active', 10, '2026-09-01'); const newer = comp('sb9_lot_split_estimate', 10, '2026-11-01');
  assert.equal(topSignal([older, newer])!.key, 'sb9_lot_split_estimate');
  assert.equal(topSignal([newer, older])!.key, 'sb9_lot_split_estimate');
});

test('sensitive components never headline', () => {
  assert.equal(topSignal([comp('tax_default', 30, '2026-11-01'), comp('owner:ownership_transfer', 25, null)]), null);
});

test('plural permit wording', () => {
  assert.equal(pluralPermitLabel(BLDG, 2), '2 building permits');
  assert.equal(pluralPermitLabel('Electrical, plumbing and mechanical work', 3), '3 electrical, plumbing and mechanical work permits');
  assert.equal(leadHeadline(lead([comp('permit_approved:adu', 9, '2026-11-10', { permit_label: BLDG, permit_count: 1 })]))!.text, `${BLDG} approved Nov 10`);
});

test('the lead page header uses the same pick (raw score components, zero-weight dropped)', () => {
  const components = [
    { key: 'permit_approved:maintenance', kind: 'signal', contribution: 0, facts: { permit_label: 'Heating, cooling or mechanical work', permit_count: 1 }, signal_id: 'x', is_sample: false, is_estimate: false },
    { key: 'permit_approved:adu', kind: 'signal', contribution: 9.1, facts: { permit_label: BLDG, permit_count: 2 }, signal_id: 'y', signal_date: '2026-11-10', is_sample: false, is_estimate: false },
  ];
  const d = detailHeadline({ signals: [{ id: 'y', signal_date: '2026-11-10' }], score: { components, reason_text: null } } as never)!;
  assert.equal(d.text, '2 building permits approved Nov 10');
  assert.equal(topSignalLine(components)!.text, d.text);
});

test('a scoring-model change shows "Scoring updated" instead of a percentage', () => {
  const s = { this_week: 40, last_week: 10, weeks: [40, 10, 9], first_day: '2026-01-01', scoring_updated: true };
  const d = statDelta(s, TODAY);
  assert.equal(d.label, 'Scoring updated');
  assert.doesNotMatch(d.label, /%/);
  assert.equal(statDelta({ ...s, scoring_updated: false }, TODAY).label, '+300% vs last week');
});

test('a scoring-model change wins over the initial-load rule and never shows a percentage, even for a big drop', () => {
  const d = statDelta({ this_week: 10, last_week: 50, weeks: [10, 50, 48], first_day: '2026-01-01', scoring_updated: true }, TODAY);   // would be -80%
  assert.equal(d.label, 'Scoring updated');
  assert.equal(d.scoringUpdated, true);
  assert.equal(d.firstFull, false);
  assert.equal(statDelta({ this_week: 10, last_week: 50, weeks: [10, 50, 48], first_day: '2026-01-01' }, TODAY).label, '-80% vs last week');
});

// ── recipe-scoped headline (Phase 5I) ──
const sig = (key: string, contribution: number, facts: Record<string, unknown> = {}, extra: Record<string, unknown> = {}) =>
  ({ key, kind: 'signal', contribution, facts, signal_date: '2026-10-01', is_sample: false, is_estimate: false, ...extra });
const own = (key: string, contribution: number, facts: Record<string, unknown> = {}) =>
  ({ key, kind: 'owner', contribution, facts, is_sample: true, is_estimate: false });
const STRO = sig('stro_license_active', 5, { tier: 'Tier 3' });          // the global-highest on these parcels

test('Builder bait shows the upzoning or lot-split fact, not the active STR license', () => {
  const comps = [STRO, sig('sb9_lot_split_estimate', 4, {}, { is_estimate: true }), own('owner:years_owned', 10, { years_owned: 26 })];
  assert.equal(recipeSignalLine('builder_bait', comps)!.text, 'SB 9 lot-split eligibility');
  assert.equal(recipeSignalLine('builder_bait', comps)!.estimate, true);
  assert.equal(recipeSignalLine('builder_bait', [STRO, sig('sb79_transit_estimate', 6), sig('sb9_lot_split_estimate', 4)])!.text, 'Near transit (SB 79)');   // higher contribution wins
  assert.equal(recipeSignalLine('builder_bait', [STRO, sig('permit_approved:demolition_lot_split', 0, { permit_label: 'Parcel map waiver (lot split)', permit_count: 1 })])!.text, 'Parcel map waiver (lot split) approved Oct 1');
});

test('Downsizer shows tenure and free-and-clear, never the STR license', () => {
  const comps = [STRO, own('owner:years_owned', 10, { years_owned: 26 }), own('owner:mortgage_open_false', 10, { mortgage_open: false })];
  const line = recipeSignalLine('downsizer', comps)!;
  assert.equal(line.text, '26 years owned · No open mortgage');
  assert.equal(line.sample, true);                                          // owner facts keep the sample flag
  assert.equal(recipeSignalLine('downsizer', [STRO, own('owner:mortgage_open_false', 10)])!.text, 'No open mortgage');
});

test('Stalled project shows the expired permit; Tired landlord shows the owner fact plus the permit/friction fact', () => {
  const stalled = sig('permit_stalled', 3.4, { permit_count: 1 });
  assert.equal(recipeSignalLine('stalled_project', [STRO, stalled])!.text, 'Permit expired with no close date');
  assert.equal(recipeSignalLine('tired_landlord', [STRO, stalled, own('owner:out_of_state', 12), own('owner:absentee', 10)])!.text, 'Out-of-state owner · Permit expired with no close date');
  assert.equal(recipeSignalLine('tired_landlord', [STRO, own('owner:absentee', 10)])!.text, 'Absentee owner');
});

test('a recipe line never shows another recipe\'s fact, a sensitive fact, or an unrelated signal', () => {
  assert.equal(recipeSignalLine('downsizer', [STRO]), null);                // nothing of its own stored: show nothing, not the STR license
  assert.equal(recipeSignalLine('builder_bait', [STRO, own('owner:years_owned', 10, { years_owned: 30 })]), null);
  const taxOnly = [sig('tax_default', 30, { notice: 'x' }), own('owner:ownership_transfer', 8)];
  for (const k of ['tired_landlord', 'financial_pressure', 'downsizer']) assert.equal(recipeSignalLine(k, taxOnly), null, k);
  assert.doesNotMatch(recipeSignalLine('tired_landlord', [sig('tax_default', 30), own('owner:absentee', 10)])!.text, /tax/i);
  assert.equal(recipeSignalLine('str_exit', [STRO]), null);                 // an active license is not an exit
  assert.equal(recipeSignalLine('str_exit', [STRO, sig('stro_license_removed', 9)])!.text, 'Short-term rental license removed');
  assert.equal(recipeSignalLine('some_future_recipe', [STRO])!.text, 'Active short-term rental license (Tier 3)');   // unknown key: global top signal
});

// ── pipeline (Phase 5I) ──
test('pipeline steps: conversion from the previous stage and GCI at 2.5% of estimated value', () => {
  const overall = { label: 'All', stages: [['signal', 40], ['contacted', 20], ['conversation', 5], ['appointment', 2], ['listing', 0]].map(([key, count]) => ({ key, label: String(key), count })) } as never;
  const values = [{ key: 'signal', parcels: 40, valued_parcels: 40, est_value: 80_000_000, sample_parcels: 40 }, { key: 'contacted', parcels: 20, valued_parcels: 18, est_value: 40_000_000, sample_parcels: 0 }] as never;
  const steps = pipelineSteps(overall, values);
  assert.deepEqual(steps.map((x) => x.label), ['Flagged', 'Contacted', 'Conversation', 'Appointment', 'Listing']);
  assert.equal(steps[0]!.rate, null);
  assert.equal(steps[1]!.rate, 0.5);
  assert.equal(steps[2]!.rate, 0.25);
  assert.equal(steps[4]!.rate, 0);
  assert.equal(steps[0]!.gci, 2_000_000);  assert.equal(steps[0]!.sample, true);
  assert.equal(steps[1]!.gci, 1_000_000);  assert.equal(steps[1]!.unvalued, 2);  assert.equal(steps[1]!.sample, false);
  assert.equal(steps[2]!.gci, null);
  assert.equal(estGci(1_000_000), 25_000);
});
