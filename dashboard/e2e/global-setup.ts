import { chromium, type FullConfig } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { refreshAggregates, rest, stack, SECRET_OWNER, TEST_APN, TEST_APN2, TEST_EMAIL } from './env';
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
  await rest('/rest/v1/signals', { method: 'POST', json: [
    { apn: TEST_APN, signal_type: 'tax_default', signal_group: 'distress', signal_date: '2026-07-01', source_key: 'tax_default', source_record_id: TEST_APN, confidence: 0.95, match_method: 'apn', is_estimate: false, details: { list: 'e2e' } },
    ...['A', 'B', 'C'].map((k) => ({ apn: TEST_APN, signal_type: 'permit_approved', signal_group: 'remodel_addition', signal_date: '2026-11-10', source_key: 'dev_permits', source_record_id: `E2E-PMT-${k}`, confidence: 0.95, match_method: 'apn', is_estimate: false, details: { approval_id: `E2E-PMT-${k}`, scope: 'E2E kitchen remodel', issue_date: '2026-11-10' } })),
    { apn: TEST_APN, signal_type: 'sb9_lot_split_estimate', signal_group: 'upzoning', signal_date: '2026-11-18', source_key: 'upzoning_estimate', source_record_id: `${TEST_APN}-sb9`, confidence: 0.9, match_method: 'spatial', is_estimate: true, details: {} },
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
