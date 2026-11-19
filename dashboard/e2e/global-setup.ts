import { chromium, type FullConfig } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { refreshAggregates, rest, stack, SECRET_OWNER, TEST_APN, TEST_APN2, TEST_EMAIL, TEST_WEEK } from './env';
import { cleanup } from './global-teardown';

/**
 * Seeds one test team member and one synthetic test parcel (with an unblocked and a blocked draft), then signs in
 * once and saves the session. Everything is removed again in global-teardown. Real data is never modified.
 */
export default async function globalSetup(config: FullConfig) {
  const s = stack();
  await cleanup(); // leftovers from an interrupted run

  await rest('/rest/v1/team_members', { method: 'POST', json: { email: TEST_EMAIL, name: 'E2E Tester', role: 'agent' } });
  await rest('/auth/v1/admin/users', { method: 'POST', json: { email: TEST_EMAIL, email_confirm: true } });

  await rest('/rest/v1/parcels', { method: 'POST', json: { apn: TEST_APN, situs_address: '1 E2E Test Way', zip: '92037', planning_area: 'La Jolla', neighborhood: 'La Jolla', lot_sqft: 6400, land_use: '11', zoning: 'RS-1-7', year_built: 1962 } });
  await rest('/rest/v1/scores', { method: 'POST', json: { apn: TEST_APN, score: 55, components: [], reason_text: 'Tax default (Jul 2026)', recipe_matches: ['builder_bait', 'financial_pressure'], primary_recipe: 'financial_pressure', model_version: 'v0.3-handset', uses_sample_data: true } });
  await rest('/rest/v1/owners', { method: 'POST', json: { apn: TEST_APN, owner_name: SECRET_OWNER, mailing_address: '9 Secret Mailing Ln, Seattle, WA 98101', owner_occupied: false, absentee: true, out_of_state: true, last_sale_date: '2012-05-01', last_sale_price: 777777, mortgage_open: true, est_value: 3100000, est_equity: 2000000, provider: 'sample', is_sample: true, as_of: '2026-11-18' } });
  await rest('/rest/v1/sales_history', { method: 'POST', json: { apn: TEST_APN, sale_date: '2012-05-01', sale_price: 777777, doc_type: 'grant deed', provider: 'sample', is_sample: true } });
  const seeded = await rest('/rest/v1/signals', { method: 'POST', json: [
    { apn: TEST_APN, signal_type: 'tax_default', signal_group: 'distress', signal_date: '2026-07-01', source_key: 'tax_default', source_record_id: TEST_APN, confidence: 0.95, match_method: 'apn', is_estimate: false, details: { list: 'e2e' } },
    ...['A', 'B', 'C'].map((k) => ({ apn: TEST_APN, signal_type: 'permit_approved', signal_group: 'remodel_addition', signal_date: '2026-11-10', source_key: 'dev_permits', source_record_id: `E2E-PMT-${k}`, confidence: 0.95, match_method: 'apn', is_estimate: false, details: { approval_id: `E2E-PMT-${k}`, scope: 'E2E kitchen remodel', issue_date: '2026-11-10' } })),
    { apn: TEST_APN, signal_type: 'sb9_lot_split_estimate', signal_group: 'upzoning', signal_date: '2026-11-18', source_key: 'upzoning_estimate', source_record_id: `${TEST_APN}-sb9`, confidence: 0.9, match_method: 'spatial', is_estimate: true, details: {} },
  ] });
  const permitId = (seeded as { id: string; signal_type: string }[]).find((x) => x.signal_type === 'permit_approved')!.id;
  // AI rows (Phase 5F): one valid lead brief citing a real signal and a sample owner fact, and one weekly briefing.
  const ai = { client_id: 'kaiser-team', input_hash: 'e2e', prompt_version: 'v1', provider: 'fake', model: 'e2e-model', status: 'valid' };
  await rest('/rest/v1/ai_outputs', { method: 'POST', json: [
    { ...ai, task: 'lead_brief', subject_type: 'parcel', subject_id: TEST_APN, uses_sample: true, cited_record_ids: [permitId, 'owner:years_owned'],
      output: { headline: 'E2E recent remodel permits and long ownership', summary: 'E2E: three remodel permits were approved in November. The owner has held the home for many years (sample data).',
        claims: [{ text: 'Three remodel permits were approved on Nov 10, 2026.', record_ids: [permitId] }, { text: 'Long ownership (sample data).', record_ids: ['owner:years_owned'] }],
        suggested_angle: 'E2E: offer a neighborhood market update.' } },
    { ...ai, task: 'weekly_brief', subject_type: 'territory', subject_id: TEST_WEEK, uses_sample: false, cited_record_ids: [`week:${TEST_WEEK}`],
      output: { title: 'E2E week in review', intro: 'E2E intro: activity held steady across the territory. Permits led the week.',
        sections: [{ neighborhood: 'La Jolla', bullets: ['E2E bullet for La Jolla.'] }], newsletter_paragraph: 'E2E newsletter paragraph for homeowners, friendly and without addresses.', facts: {} } },
  ] });
  await rest('/rest/v1/ai_task_runs', { method: 'POST', json: [
    { client_id: 'kaiser-team', task: 'lead_brief', status: 'success', calls: 3, cached: 1, valid: 3, invalid: 0, rejected: 1, input_tokens: 1000, output_tokens: 500, cost_usd: 0.0123, model: 'e2e-model', warnings: ['E2E warning: budget check'] },
  ] });
  const draft = { apn: TEST_APN, recipe: 'financial_pressure', uses_sample_data: false };
  await rest('/rest/v1/outreach', { method: 'POST', json: [
    { ...draft, channel: 'mail', status: 'draft', content: 'Hello neighbor,\n\nE2E unblocked letter.', source_facts: [{ kind: 'parcel_field', parcel_field: 'neighborhood', value: 'La Jolla', apn: TEST_APN }], blocked_reason: null },
    { ...draft, channel: 'email', status: 'draft', content: 'Subject: E2E blocked email', blocked_reason: 'missing agent name or DRE license; missing office address', source_facts: [] },
  ] });

  // A second parcel in Pacific Beach, with its own unblocked draft (bulk approve) and owner data (share link must not leak it).
  await rest('/rest/v1/parcels', { method: 'POST', json: { apn: TEST_APN2, situs_address: '2 E2E Beach Walk', zip: '92109', planning_area: 'Pacific Beach', neighborhood: 'Pacific Beach', lot_sqft: 5200, land_use: '11', zoning: 'RS-1-7', year_built: 1958 } });
  await rest('/rest/v1/scores', { method: 'POST', json: { apn: TEST_APN2, score: 45, components: [], reason_text: 'Older home on a large lot', recipe_matches: ['builder_bait'], primary_recipe: 'builder_bait', model_version: 'v0.3-handset', uses_sample_data: false } });
  await rest('/rest/v1/owners', { method: 'POST', json: { apn: TEST_APN2, owner_name: SECRET_OWNER, mailing_address: '9 Secret Mailing Ln, Seattle, WA 98101', owner_occupied: false, absentee: true, out_of_state: true, mortgage_open: true, est_value: 3100000, est_equity: 2000000, provider: 'sample', is_sample: true, as_of: '2026-11-18' } });
  await rest('/rest/v1/outreach', { method: 'POST', json: { apn: TEST_APN2, recipe: 'builder_bait', uses_sample_data: false, channel: 'mail', status: 'draft', content: 'Hello neighbor,\n\nE2E bulk letter.', source_facts: [{ kind: 'parcel_field', parcel_field: 'neighborhood', value: 'Pacific Beach', apn: TEST_APN2 }], blocked_reason: null } });
  refreshAggregates(); // lists, search and counts read the materialized view

  // Sign in once: an admin-generated magic link, redeemed through the app's own callback.
  const link = await rest('/auth/v1/admin/generate_link', { method: 'POST', json: { type: 'magiclink', email: TEST_EMAIL } });
  mkdirSync('e2e/.auth', { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ baseURL: config.projects[0]!.use.baseURL! });
  await page.goto(`/auth/callback?token_hash=${link.hashed_token}&type=magiclink`);
  await page.waitForURL((u) => u.pathname === '/', { timeout: 30_000 });
  await page.context().storageState({ path: 'e2e/.auth/state.json' });
  await browser.close();
  void s;
}
