/**
 * Unit tests for the deterministic presentation rules in present.ts. Run: npm run test:unit  (node:test through tsx).
 * Phase 5G: the Today stat tiles must never show a week-over-week % against the initial data load.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { isInitialLoadWeek, statDelta, weekDelta, claimLabel } from './present.ts';

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
