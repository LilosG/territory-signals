import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { parse } from 'yaml';
import { holdAiRows, releaseAiRows, SECRET_OWNER, stack, TEST_APN, TEST_APN2, TEST_EMAIL, TEST_WEEK } from './env';

const brief = `/leads/${TEST_APN}`;
const noConsoleErrors = (page: Page) => {
  const errors: string[] = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(e.message));
  return errors;
};

test.describe('signed out', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('pages redirect to the login page', async ({ page }) => {
    for (const path of ['/', '/map', '/pipeline', `/leads/${TEST_APN}`, '/api/map']) {
      await page.goto(path);
      await expect(page).toHaveURL(/\/login$/);
    }
    await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
  });

  /** Requests a sign-in email from the login page and returns the link and 6-digit code from the local mail viewer. */
  async function requestEmail(page: Page, request: APIRequestContext): Promise<{ link: string; code: string } | null> {
    const mail = stack().mail;
    await request.delete(`${mail}/api/v1/search?query=${encodeURIComponent(`to:${TEST_EMAIL}`)}`); // start from an empty inbox
    await page.goto('/login');
    await page.getByLabel('Email').fill(TEST_EMAIL);
    await page.getByRole('button', { name: 'Email me a sign-in link' }).click();
    if (await page.getByText('Too many sign-in emails').isVisible()) return null;
    await expect(page.getByText('Check your email.')).toBeVisible();
    let out = { link: '', code: '' };
    await expect.poll(async () => {
      const list = await (await request.get(`${mail}/api/v1/search?query=${encodeURIComponent(`to:${TEST_EMAIL}`)}`)).json() as { messages?: { ID: string }[] };
      const id = list.messages?.[0]?.ID; if (!id) return '';
      const msg = await (await request.get(`${mail}/api/v1/message/${id}`)).json() as { HTML: string; Text: string };
      const link = (msg.HTML.match(/href="([^"]+\/auth\/callback\?token_hash=[^"]+)"/)?.[1] ?? '').replace(/&amp;/g, '&');
      const code = msg.Text.match(/\b(\d{6})\b/)?.[1] ?? msg.HTML.match(/>\s*(\d{6})\s*</)?.[1] ?? '';
      out = { link, code };
      return link && code ? 'ok' : '';
    }, { timeout: 20_000 }).toBe('ok');
    return out;
  }

  test('login with the emailed link (token_hash flow, no browser-bound verifier)', async ({ page, request }) => {
    const mail = await requestEmail(page, request);
    test.skip(!mail, 'Local Supabase limits sign-in emails per hour; rerun later');
    expect(mail!.link).toMatch(/\/auth\/callback\?token_hash=.+&type=email$/);
    // Open it in a brand-new browser context: the link must not depend on cookies from the requesting browser.
    const other = await page.context().browser()!.newContext({ baseURL: 'http://127.0.0.1:3000' });
    const page2 = await other.newPage();
    await page2.goto(mail!.link);
    await expect(page2).toHaveURL(/127\.0\.0\.1:3000\/$/);
    await expect(page2.getByRole('heading', { name: /^Good (morning|afternoon|evening)/ })).toBeVisible();
    await other.close();
  });

  test('login with the 6-digit code from the email', async ({ page, request }) => {
    const mail = await requestEmail(page, request);
    test.skip(!mail, 'Local Supabase limits sign-in emails per hour; rerun later');
    await page.getByLabel('Enter your 6-digit code').fill('000000');
    await page.getByRole('button', { name: 'Sign in with code' }).click();
    await expect(page.getByText('That code is wrong or has expired.')).toBeVisible();
    await page.getByLabel('Enter your 6-digit code').fill(mail!.code);
    await page.getByRole('button', { name: 'Sign in with code' }).click();
    await expect(page).toHaveURL(/127\.0\.0\.1:3000\/$/);
    await expect(page.getByRole('heading', { name: /^Good (morning|afternoon|evening)/ })).toBeVisible();
  });

  test('an invalid or reused link redirects to /login with a friendly message, never a 500', async ({ page }) => {
    for (const path of ['/auth/callback?token_hash=not-a-real-token&type=email', '/auth/callback?code=not-a-real-code', '/auth/callback']) {
      const res = await page.goto(path);
      expect(res!.status(), path).toBeLessThan(500);
      await expect(page).toHaveURL(/\/login\?error=link$/);
      await expect(page.getByText('That link expired or was opened in a different browser. Request a new one or use your code.')).toBeVisible();
    }
  });

  test('an email that is not on the team gets no account and no email', async ({ page, request }) => {
    const stranger = `stranger-${Date.now()}@example.test`;
    await page.goto('/login');
    await page.getByLabel('Email').fill(stranger);
    await page.getByRole('button', { name: 'Email me a sign-in link' }).click();
    await expect(page.getByText(/Check your email|Too many sign-in emails/)).toBeVisible();
    const s = stack();
    const users = await (await request.get(`${s.url}/auth/v1/admin/users?per_page=1000`, { headers: { apikey: s.service, authorization: `Bearer ${s.service}` } })).json() as { users: { email: string }[] };
    expect(users.users.some((u) => u.email === stranger)).toBe(false);
    const list = await (await request.get(`${s.mail}/api/v1/search?query=${encodeURIComponent(`to:${stranger}`)}`)).json() as { messages?: unknown[] };
    expect(list.messages?.length ?? 0).toBe(0);
  });
});

const GREETING = /^Good (morning|afternoon|evening)/;
const IGNORED_ERRORS = /tiles\.openfreemap|net::ERR|Failed to load resource/;

/** Switches territory through the sidebar select (it submits itself) and waits for the page to reload. */
async function setTerritory(page: Page, value: string) {
  const done = page.waitForResponse((r) => r.url().includes('/actions/territory') && r.request().method() === 'POST');
  await page.locator('#territory').selectOption(value);
  await done;
  await page.waitForLoadState('load');
}

test('Today loads live data', async ({ page }) => {
  const errors = noConsoleErrors(page);
  await page.goto('/');
  await expect(page.getByRole('heading', { name: GREETING })).toBeVisible();
  const cards = await page.locator('article').count();
  expect(cards).toBeGreaterThan(0);
  expect(cards).toBeLessThanOrEqual(10);
  await expect(page.getByText('New signals').first()).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Active territory strategies' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Approvals' })).toBeVisible();
  await expect(page.locator('[data-sample-banner]')).toBeVisible();      // live scores still rest on sample owner data
  await expect(page.locator('[data-user-email]')).toHaveText(TEST_EMAIL);
  expect(errors.filter((e) => !IGNORED_ERRORS.test(e))).toEqual([]);
});

test('the sidebar has the grouped navigation with every page', async ({ page }) => {
  await page.goto('/');
  const nav = page.getByRole('navigation', { name: 'Primary', exact: true });
  for (const label of ['Today', 'Leads', 'Outreach', 'Pipeline', 'Map', 'Recipes', 'Off-market', 'Trends', 'Reports', 'Performance', 'Data sources', 'Team', 'Settings']) {
    await expect(nav.getByRole('link', { name: new RegExp(`^${label}`) }), label).toBeVisible();
  }
});

test('the map endpoint returns compact GeoJSON, 30+ by default and every parcel with all=1', async ({ request }) => {
  const res = await request.get('/api/map?all=1');
  expect(res.status(), await res.text().then((t) => t.slice(0, 300))).toBe(200);
  const all = await res.json();
  expect(all.type).toBe('FeatureCollection');
  expect(all.features.length).toBeGreaterThan(20_000);
  expect(Object.keys(all.features[0].properties).sort()).toEqual(['apn', 'neighborhood', 'primary_recipe', 'score']);
  const dflt = await (await request.get('/api/map')).json();
  expect(dflt.features.length).toBeLessThan(all.features.length);
  expect(dflt.features.every((f: { properties: { score: number } }) => f.properties.score >= 30)).toBe(true);
  const lj = await (await request.get('/api/map?all=1&hood=Mission%20Beach&range=60-100')).json();
  expect(lj.features.length).toBeLessThan(all.features.length);
  expect(lj.features.every((f: { properties: { neighborhood: string; score: number } }) => f.properties.neighborhood === 'Mission Beach' && f.properties.score >= 60)).toBe(true);
});

test('lead brief shows the data, labels from the catalog and the owner panel', async ({ page }) => {
  await page.goto(brief);
  await expect(page.getByRole('heading', { name: '1 E2E Test Way' })).toBeVisible();
  await expect(page.locator('[data-hero]')).toBeVisible();
  await expect(page.locator('[data-split-workspace]')).toBeVisible();                         // one workspace, no tabs for the brief itself
  await expect(page.getByRole('tab', { name: 'Overview' })).toHaveCount(0);
  await expect(page.locator('[data-model-version]')).toHaveText('Model v0.4.1-handset');
  const owner = page.locator('section[aria-labelledby=owner-h]');
  await expect(owner.getByText(SECRET_OWNER)).toBeVisible();
  await expect(owner.locator('h3').getByText('Sample', { exact: true })).toHaveCount(1);   // one badge, in the header
  await expect(owner.getByText('14 years')).toBeVisible();                                  // whole years
  await expect(owner.getByText('Open mortgage')).toBeVisible();
  const portfolio = owner.locator('[data-portfolio]');
  await expect(portfolio).toContainText('Territory Portfolio');
  await expect(portfolio).toContainText('Holds 2 parcels in territory');
  await expect(portfolio).toContainText('est.');
  await expect(page.getByRole('heading', { name: 'Sensitive records' })).toBeVisible();     // tax default only appears here, labeled
  await expect(page.locator('[data-sensitive]')).toContainText('Open code enforcement case');
  const timeline = page.locator('[data-timeline] ol').first();
  await expect(timeline.locator('[data-event]')).toHaveCount(1);                              // same-day permits collapse into one event
  await expect(timeline).toContainText('3 permits approved');
  await expect(timeline).toContainText('Nov 10, 2026');
  await timeline.getByText('Show all 3').click();
  await expect(timeline.locator('details li')).toHaveCount(3);
  await expect(timeline).toContainText('Matched by parcel number · 95%');
  await expect(timeline).not.toContainText(/years owned|absentee|equity|mortgage|tax default|death|deceased|code enforcement/i);   // owner traits and distress are not timeline events
  await expect(page.getByRole('region', { name: 'Property traits' })).toContainText('SB 9 lot-split eligibility');
});

test('lead cards and lists never show distress or life-event chips', async ({ page }) => {
  await page.goto('/leads');
  const text = (await page.locator('main').innerText()).toLowerCase();
  for (const word of ['tax default', 'ownership transfer', 'financial pressure', 'death', 'deceased', 'probate', 'code enforcement', 'code violation']) expect(text, word).not.toContain(word);
});

test('a blocked draft cannot be approved; an unblocked one can, after an edit', async ({ page }) => {
  await page.goto(`${brief}#drafts`);
  // blocked email draft
  await page.getByRole('tab', { name: 'Email' }).click();
  const emailPanel = page.getByRole('region', { name: 'Email' });
  await expect(emailPanel.locator('[data-blocked]')).toContainText('missing agent name or DRE license');
  await expect(emailPanel.getByRole('button', { name: 'Approve draft' })).toBeDisabled();
  // unblocked letter: edit, then approve
  await page.getByRole('tab', { name: 'Letter' }).click();
  const letter = page.getByRole('region', { name: 'Letter' });
  await expect(letter.locator('[data-blocked]')).toHaveCount(0);
  await letter.locator('textarea').fill('Hello neighbor,\n\nE2E edited letter.');
  await letter.getByRole('button', { name: 'Save edit' }).click();
  await expect(page.locator('[data-flash=ok]')).toContainText('Edit saved');
  await expect(page.getByRole('region', { name: 'Letter' }).locator('[data-edited]')).toContainText(`Edited by ${TEST_EMAIL}`);
  await page.getByRole('region', { name: 'Letter' }).getByRole('button', { name: 'Approve draft' }).click();
  await expect(page.locator('[data-flash=ok]')).toContainText('Draft approved');
  const done = page.getByRole('region', { name: 'Letter' });
  await expect(done.locator('[data-draft-status]')).toHaveText('Approved');
  await expect(done).toContainText(`Approved by ${TEST_EMAIL}`);
  await expect(done.getByText('E2E edited letter.')).toBeVisible();
  const history = page.getByRole('table', { name: 'Outreach history' });
  await expect(history).toContainText('Approved');
  await expect(history.locator('tbody td').last()).toHaveText('Not sent');
});

/** Finds the queue row for an address, walking the pages of an Outreach tab. */
async function findQueueRow(page: Page, tab: string, address: string) {
  for (let n = 1; n <= 40; n++) {
    await page.goto(`/outreach?tab=${tab}&page=${n}`);
    const row = page.locator('[data-outreach-row]', { hasText: address });
    if (await row.count()) return row.first();
    if (!(await page.getByRole('link', { name: 'Next' }).count())) break;
  }
  throw new Error(`no ${tab} row for ${address}`);
}

test('Outreach: tabs show counts, blocked drafts explain themselves, and bulk approve works', async ({ page }) => {
  await page.goto('/outreach');
  const tabs = page.getByRole('navigation', { name: 'Outreach' });
  for (const label of ['Drafts', 'Awaiting approval', 'Approved', 'Call tasks']) await expect(tabs.getByRole('link', { name: new RegExp(label) })).toBeVisible();

  // The blocked email draft is listed, cannot be selected, and says in plain words what is missing.
  const blockedRow = await findQueueRow(page, 'drafts', '1 E2E Test Way');
  await expect(blockedRow.locator('[data-blocked]')).toHaveText('Blocked');
  await expect(blockedRow.locator('[data-blocked]')).toHaveAttribute('title', /DRE license/);
  // The reasons are stated once in the tab banner when every draft on the page shares them; otherwise the row says why.
  const stated = (await page.locator('[data-blocked-banner]').allInnerTexts()).join(' ') + (await blockedRow.locator('[data-blocked-extra]').allInnerTexts()).join(' ');
  expect(stated).toContain('DRE license');
  expect(stated).not.toMatch(/blocked_reason|rpc|_/);
  await expect(blockedRow.locator('input[data-bulk-item]')).toBeDisabled();

  // Bulk approve exactly one ready draft (never "select all": other drafts belong to real data).
  const row = await findQueueRow(page, 'drafts', '2 E2E Beach Walk');
  await row.locator('input[data-bulk-item]').check();
  await expect(page.locator('[data-bulk-label]')).toHaveText('1 selected');
  await page.locator('#approve-selected').click();
  await expect(page.locator('[data-flash=ok]')).toContainText('1 draft approved');
  const approved = await findQueueRow(page, 'approved', '2 E2E Beach Walk');
  await expect(approved).toBeVisible();
  const db = await (await page.request.get(`${stack().url}/rest/v1/outreach?apn=eq.${TEST_APN2}&select=status,approved_by`, { headers: { apikey: stack().service, authorization: `Bearer ${stack().service}` } })).json();
  expect(db).toEqual([{ status: 'approved', approved_by: TEST_EMAIL }]);
});

test('Recipes: every enabled recipe is shown, the header count equals the nav badge, and links open the filtered Leads list', async ({ page }) => {
  const errors = noConsoleErrors(page);
  await page.goto('/recipes');
  const cfg = parse(readFileSync(resolve(import.meta.dirname, '../../config/clients/kaiser-team.yaml'), 'utf8')) as { recipes: Record<string, { enabled: boolean }> };
  const enabled = Object.entries(cfg.recipes).filter(([, v]) => v.enabled).map(([k]) => k);
  // Each enabled recipe is a card (it has matches) or a row under "Waiting on data"; never missing.
  for (const key of enabled) await expect(page.locator(`article[data-recipe=${key}], [data-waiting-recipe=${key}]`), key).toHaveCount(1);
  await expect(page.locator('article[data-recipe=financial_pressure]')).toBeVisible();           // the e2e parcel matches it
  await expect(page.locator('article[data-recipe=financial_pressure] [data-approval-chip]')).toHaveText('Approval required');
  await expect(page.locator('article[data-recipe=quiet_inheritance]')).toHaveCount(0);
  // Cards hold no placeholder bodies; waiting recipes are one line each.
  await expect(page.locator('article[data-recipe] [data-idle]')).toHaveCount(0);
  const header = Number((await page.locator('main .eyebrow').first().innerText()).match(/^(\d+) switched on/i)![1]);
  const badge = Number((await page.getByRole('navigation', { name: 'Primary', exact: true }).getByRole('link', { name: /^Recipes/ }).innerText()).match(/(\d+)/)![1]);
  expect(header).toBe(enabled.length);
  expect(badge).toBe(header);
  // Active cards run strongest first.
  const strong = await page.locator('article[data-recipe]').evaluateAll((els) => els.map((e) => Number(e.querySelectorAll('dd')[2]!.textContent!.replace(/,/g, ''))));
  expect(strong).toEqual([...strong].sort((x, y) => y - x));
  const bait = page.locator('article[data-recipe=builder_bait]');
  await expect(bait).toBeVisible();
  await expect(bait.getByText('New this week')).toBeVisible();
  await bait.getByRole('link', { name: /View all/ }).click();
  await expect(page).toHaveURL(/\/leads\?recipe=builder_bait$/);
  await expect(page.getByRole('heading', { name: 'Leads' }).first()).toBeVisible();
  await expect(page.locator('article').first()).toBeVisible();
  // The Today strip links the same way.
  await page.goto('/');
  await page.locator('a[href^="/leads?recipe="]').first().click();
  await expect(page).toHaveURL(/\/leads\?recipe=/);
  expect(errors.filter((e) => !IGNORED_ERRORS.test(e))).toEqual([]);
});

test('Off-market: bulk share link shows property facts only, then revoke', async ({ page, browser }) => {
  await page.goto('/off-market?kind=builder_bait&sort=address');
  await expect(page.getByText('Property facts only').first()).toBeVisible();
  let row = page.locator(`[data-offmarket-row=${TEST_APN2}]`);
  for (let n = 2; !(await row.count()) && n <= 40; n++) {      // sorted by address, the test parcel may be on a later page
    await page.goto(`/off-market?kind=builder_bait&sort=address&page=${n}`);
    row = page.locator(`[data-offmarket-row=${TEST_APN2}]`);
  }
  await expect(row).toContainText('Builder bait');
  await expect(row).toContainText('5,200 sq ft lot');
  await expect(row.locator('[data-portfolio]')).toContainText('Territory Portfolio');
  await expect(row.locator('[data-portfolio]')).toContainText('Holds 2 parcels in territory');
  await expect(row).not.toContainText(/owner|equity|mortgage|Seattle/i);
  await row.locator('input[data-bulk-item]').check();
  await page.locator('#create-links').click();
  await expect(page.locator('[data-flash=ok]')).toContainText('1 share link created');
  const link = page.locator('[data-share-link]', { hasText: '2 E2E Beach Walk' }).first();
  const url = await link.locator('input[aria-label="Share link"]').inputValue();
  expect(url).toMatch(/\/share\/[0-9a-f]{64}$/);

  const anon = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const pub = await anon.newPage();
  expect((await pub.goto(url))!.status()).toBe(200);
  const body = await pub.locator('body').innerText();
  expect(body).toContain('Pacific Beach');
  expect(body).toContain('5,200 sq ft');
  for (const secret of [SECRET_OWNER, 'Secret Mailing', 'Seattle', '3,100,000', '2,000,000', 'mortgage', 'equity', 'tax', 'default', 'E2E Beach Walk', TEST_APN2, 'Sample', 'Territory Portfolio', 'code enforcement']) {
    expect(body, `share page must not contain "${secret}"`).not.toContain(secret);
  }
  expect(await pub.content()).not.toContain(SECRET_OWNER);

  await link.locator('[data-revoke]').click();
  await expect(page.locator('[data-flash=ok]')).toContainText('revoked');
  expect((await pub.goto(url))!.status()).toBe(404);
  await anon.close();
});

test('territory switcher filters Leads, search and the map data, and persists', async ({ page }) => {
  const idle = async () => page.waitForLoadState('networkidle');
  await page.goto('/leads');
  await setTerritory(page, 'Pacific Beach');
  await page.goto('/leads?recipe=builder_bait&sort=address');
  await expect(page.locator('#territory')).toHaveValue('Pacific Beach');
  const hoods = await page.locator('article').evaluateAll((els) => els.map((e) => e.textContent ?? ''));
  expect(hoods.length).toBeGreaterThan(0);
  expect(hoods.every((t) => t.includes('Pacific Beach'))).toBe(true);
  expect(hoods.some((t) => t.includes('La Jolla') || t.includes('Mission Beach'))).toBe(false);
  // API routes follow the same cookie.
  const map = await (await page.request.get('/api/map?all=1')).json();
  expect(map.features.length).toBeGreaterThan(0);
  expect(map.features.every((f: { properties: { neighborhood: string } }) => f.properties.neighborhood === 'Pacific Beach')).toBe(true);
  const leadsApi = await (await page.request.get('/api/leads?size=25')).json() as { items: { parcel: { neighborhood: string } }[] };
  expect(leadsApi.items.every((l) => l.parcel.neighborhood === 'Pacific Beach')).toBe(true);
  // The selected territory survives navigation and shows in the switcher.
  await page.goto('/recipes');
  await expect(page.locator('#territory')).toHaveValue('Pacific Beach');
  // Search is limited to the territory: the La Jolla test parcel is not found, the Pacific Beach one is.
  expect(await (await page.request.get('/api/search?q=E2E%20Test%20Way')).json()).toEqual([]);
  expect((await (await page.request.get('/api/search?q=E2E%20Beach%20Walk')).json()).length).toBe(1);
  // Switch to La Jolla: the other test parcel appears and the Pacific Beach one is gone.
  await page.goto('/off-market');
  await setTerritory(page, 'La Jolla');
  expect((await (await page.request.get('/api/search?q=E2E%20Test%20Way')).json()).length).toBe(1);
  expect(await (await page.request.get('/api/search?q=E2E%20Beach%20Walk')).json()).toEqual([]);
  // Back to All.
  await setTerritory(page, '');
  await idle();
  expect((await (await page.request.get('/api/search?q=E2E%20Be')).json()).length).toBe(1);
  await expect(page.locator('#territory')).toHaveValue('');
});

test('Cmd+K search finds an address or APN and opens the lead brief', async ({ page }) => {
  await page.goto('/leads');
  await page.keyboard.press('ControlOrMeta+k');
  const dialog = page.getByRole('dialog', { name: 'Search leads' });
  await expect(dialog).toBeVisible();
  await page.locator('#search-input').fill('E2E Test Way');
  await expect(page.locator('#search-results li').first()).toContainText(/1 E2E Test Way/i);
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(new RegExp(`/leads/${TEST_APN}$`));
  await expect(page.getByRole('heading', { name: '1 E2E Test Way' })).toBeVisible();
  // The sidebar search field opens the same dialog, and an APN works too.
  await page.getByRole('button', { name: /Search address or APN/ }).click();
  await expect(dialog).toBeVisible();
  await page.locator('#search-input').fill('E2E Beach');
  await expect(page.locator('#search-results')).toContainText(/2 E2E Beach Walk/i);
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
});

test('Reports, Performance, Data sources and Team render their designed content', async ({ page }) => {
  await page.goto('/reports');
  await expect(page.getByRole('heading', { name: 'Reports' }).first()).toBeVisible();
  await page.locator('a[href="/reports/la-jolla"]').click();
  await expect(page).toHaveURL(/\/reports\/la-jolla/);
  await page.goto('/performance');
  await expect(page.getByText('Connects when owner sale history is added in Phase 6')).toBeVisible();
  await expect(page.getByText('Parcels monitored').first()).toBeVisible();
  await page.goto('/data-sources');
  const text = await page.locator('main').innerText();
  for (const dev of ['source_runs', 'rpc', 'private.', 'materialized']) expect(text).not.toContain(dev);
  await page.goto('/team');
  await expect(page.getByText('E2E Tester')).toBeVisible();
});

test('record an outcome', async ({ page }) => {
  await page.goto(brief);
  await expect(page.locator('[data-outcome-card]')).toBeVisible();                            // the controls are in the co-pilot, no tab switch needed
  await page.getByPlaceholder('Note (optional)').fill('left a voicemail');
  await page.locator('[data-outcome=contacted]').click();
  await expect(page.locator('[data-flash=ok]')).toContainText('Outcome recorded');
  await expect(page.locator('section[aria-labelledby=act-h]')).toContainText('Contacted');
  await expect(page.locator('section[aria-labelledby=act-h]')).toContainText('left a voicemail');
  await page.goto('/pipeline');
  await expect(page.getByText('No outcomes recorded yet')).toHaveCount(0);
  await page.goto('/performance');
  await expect(page.getByText('Connects when owner sale history is added in Phase 6')).toBeVisible();
});

test('create a share link from the brief, open it signed out (property facts only), then revoke it', async ({ page, browser }) => {
  await page.goto(brief);
  await page.locator('#create-share').click();
  await expect(page.locator('[data-flash=ok]')).toContainText('Share link created');
  const url = await page.locator('[data-share-link] input').first().inputValue();
  expect(url).toMatch(/\/share\/[0-9a-f]{64}$/);

  const anon = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const pub = await anon.newPage();
  const res = await pub.goto(url);
  expect(res!.status()).toBe(200);
  const body = await pub.locator('body').innerText();
  expect(body).toContain('La Jolla');
  expect(body).toContain('RS-1-7');
  expect(body).toContain('6,400 sq ft');
  expect(body).toContain('1962');
  expect(body).toContain('SB 9 lot-split eligibility');
  expect(body.toLowerCase()).toContain('estimated');
  expect(body).toContain('E2E Tester');
  for (const secret of [SECRET_OWNER, 'Secret Mailing', 'Seattle', '777', '3,100,000', '2,000,000', 'mortgage', 'equity', 'tax', 'default', 'E2E Test Way', TEST_APN, 'Sample']) {
    expect(body, `share page must not contain "${secret}"`).not.toContain(secret);
  }
  expect(await pub.content()).not.toContain(SECRET_OWNER);

  await page.locator('[data-revoke]').first().click();
  await expect(page.locator('[data-flash=ok]')).toContainText('revoked');
  const gone = await pub.goto(url);
  expect(gone!.status()).toBe(404);
  await expect(pub.getByText('This link is no longer available')).toBeVisible();
  await anon.close();
});

test('map page: the MapLibre worker and /api/map load, and points are rendered', async ({ page, request }) => {
  const bad: string[] = [];
  page.on('response', (r) => { if (new URL(r.url()).origin === 'http://127.0.0.1:3000' && r.status() >= 400) bad.push(`${r.status()} ${r.url()}`); });
  // The worker file must be served as a static module (it was a 404 in production: blank map).
  const w = await request.get('/maplibre/maplibre-gl-worker.mjs');
  expect(w.status()).toBe(200);
  expect(w.headers()['content-type']).toMatch(/javascript/);
  const points = page.waitForResponse((r) => r.url().includes('/api/map'));
  await page.goto('/map');
  const res = await points;
  expect(res.status()).toBe(200);
  expect(res.headers()['content-type']).toContain('geo+json');
  await expect(page.locator('#lead-map canvas.maplibregl-canvas')).toBeVisible();
  await expect(page.locator('#map-count')).toContainText('parcels');
  // Parcel points (or clusters) are actually in the map, which only happens when the worker ran.
  await expect.poll(() => page.evaluate(() => {
    const m = (window as unknown as { __leadMap?: { querySourceFeatures: (s: string) => unknown[] } }).__leadMap;
    return m ? m.querySourceFeatures('leads').length : 0;
  }), { timeout: 30_000 }).toBeGreaterThan(0);
  expect(bad).toEqual([]);
});

test('street addresses are shown in title case, never ALL CAPS', async ({ page, request }) => {
  await page.goto('/leads');
  const first = await page.locator('h3').first().innerText();
  expect(first).toMatch(/^\d+ /);
  expect(first).not.toMatch(/[A-Z]{3,}/); // "6275 Cardeno Dr", not "6275 CARDENO DR"
  const api = await (await request.get('/api/leads?size=25')).json() as { items: { parcel: { situs_address: string | null } }[] };
  for (const l of api.items) expect(l.parcel.situs_address ?? '').not.toMatch(/\b[A-Z]{3,}\b/);
});

test('every signed-in page loads without a server error or console error', async ({ page }) => {
  const errors = noConsoleErrors(page);
  const paths = ['/', '/leads', '/outreach', '/pipeline', '/map', '/recipes', '/off-market', '/trends', '/trends/newsletter', '/reports', '/reports/la-jolla', '/performance', '/data-sources', '/team', '/settings', brief, `${brief}/presentation`];
  for (const path of paths) {
    const res = await page.goto(path);
    expect(res!.status(), path).toBe(200);
    await expect(page).toHaveURL(new RegExp(`${path.replace(/[/]/g, '\\/')}$`));
  }
  expect(errors.filter((e) => !IGNORED_ERRORS.test(e))).toEqual([]);
});

test('Outreach: Approve selected is disabled with nothing selected and enables with a selection', async ({ page }) => {
  await page.goto('/outreach?tab=drafts');
  const approve = page.locator('#approve-selected');
  await expect(approve).toBeDisabled();
  await expect(approve).toHaveAttribute('title', /Select at least one|Nothing is ready/);
  // With a ready draft on the page (the bulk-approve test uses it up, so this is conditional), selecting enables the button.
  const box = page.locator('input[data-bulk-item]:not(:disabled)').first();
  if (await box.count()) {
    await box.check();
    await expect(approve).toBeEnabled();
    await box.uncheck();
    await expect(approve).toBeDisabled();
  }
});

test('Outreach: draft previews are one line and end on a whole word', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/outreach?tab=drafts');
  const previews = page.locator('[data-preview]');
  expect(await previews.count()).toBeGreaterThan(0);
  const bad = await previews.evaluateAll((els) => els.flatMap((e) => {
    const full = (e as HTMLElement).dataset.preview!;
    const shown = e.textContent!;
    const h = (e as HTMLElement).clientHeight, line = parseFloat(getComputedStyle(e).lineHeight);
    const clipped = shown.endsWith('…') && !full.startsWith(shown.slice(0, -1).trimEnd() + ' ') && full !== shown.slice(0, -1);
    return h > line * 1.5 || clipped ? [shown] : [];
  }));
  expect(bad).toEqual([]);
});

for (const [name, size] of [['1440', { width: 1440, height: 900 }], ['390', { width: 390, height: 844 }]] as const) {
  test(`Trends at ${name}px: the legend sits in its own row above the plot, nothing overlaps, and the partial month is labeled`, async ({ page }) => {
    await page.setViewportSize(size);
    await page.goto('/trends');
    const charts = page.locator('[data-chart]:visible');
    expect(await charts.count()).toBeGreaterThan(0);
    for (const chart of await charts.all()) {
      const id = (await chart.getAttribute('data-chart'))!;
      const plot = (await chart.boundingBox())!;
      const legend = page.locator(`[data-chart-legend="${id}"]`);
      if (!(await legend.locator('li').count())) continue;
      const lb = (await legend.boundingBox())!;
      expect(lb.y + lb.height, `${id}: legend ends above the plot`).toBeLessThanOrEqual(plot.y + 0.5);
      expect(lb.x, id).toBeGreaterThanOrEqual(0);
      expect(lb.x + lb.width, `${id}: legend inside the viewport`).toBeLessThanOrEqual(size.width);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    // The current, partial month is called out as "<Mon> (to date)" on the monthly charts.
    const keys = page.locator('[data-partial-key]:visible');
    expect(await keys.count()).toBeGreaterThan(0);
    await expect(keys.first()).toContainText(/^[A-Z][a-z]{2} \(to date\)/);
    // Placeholder charts are not in the grid: they are one slim "Coming soon" strip.
    await expect(page.locator('[data-empty-chart]')).toHaveCount(0);
  });
}


// ---- Phase 5G: Today -------------------------------------------------------------------------------------------
for (const [w, h, split] of [[1440, 900, true], [390, 844, false]] as const) {
  test(`Today at ${w}px: executive hero (${split ? '65/35 split' : 'stacked'}), active strategies only, quiet recipes collapsed, nothing clipped`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await page.goto('/');
    const brief = page.locator('[data-hero-brief]');
    const panel = page.locator('[data-strategies]');
    await expect(brief).toBeVisible();
    await expect(panel).toBeVisible();
    const [bb, pb] = [(await brief.boundingBox())!, (await panel.boundingBox())!];
    if (split) {
      expect(Math.abs(bb.y - pb.y)).toBeLessThan(2);                                           // side by side
      const ratio = bb.width / (bb.width + pb.width);
      expect(ratio).toBeGreaterThan(0.6); expect(ratio).toBeLessThan(0.7);                    // about 65%
    } else {
      expect(pb.y).toBeGreaterThan(bb.y + bb.height - 1);                                      // stacked on a phone
      expect(bb.width).toBeGreaterThan(w - 60);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    // The briefing card is deep navy.
    expect(await brief.evaluate((e) => getComputedStyle(e).backgroundColor)).toBe('rgb(11, 18, 32)');
    // The panel lists only recipes with movement or top leads; the rest sit in a collapsed toggle.
    const quiet = page.locator('[data-quiet-recipes]');
    await expect(quiet).toHaveCount(1);
    expect(await quiet.evaluate((e) => (e as HTMLDetailsElement).open)).toBe(false);
    expect(await panel.locator('[data-recipe-grid] [data-recipe-tile]').count()).toBeGreaterThanOrEqual(0);
    for (const t of await panel.locator('[data-recipe-grid] [data-recipe-tile]').all()) await expect(t).not.toContainText('Waiting on data');
    await quiet.locator('summary').click();
    const idle = quiet.locator('[data-recipe-tile][data-idle]').first();
    await expect(idle).toContainText('Waiting on data');
    // every label is fully visible (Financial pressure included) once the toggle is open
    await expect(page.locator('[data-recipe-tile="financial_pressure"]')).toContainText('Financial pressure');
    const clipped = await panel.locator('[data-recipe-tile] span').evaluateAll((els) => els.filter((s) => s.scrollWidth > s.clientWidth + 1).map((s) => `${s.className}|${s.textContent}|${s.scrollWidth}>${s.clientWidth}`));
    expect(clipped).toEqual([]);
  });
}

test('Today: "Copy newsletter block" copies the briefing and confirms inline', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.goto('/');
  const btn = page.locator('#copy-newsletter');
  await expect(btn).toBeVisible();
  await expect(btn).toContainText('Copy newsletter block');
  await btn.click();
  await expect(page.locator('[data-hero-brief] [data-copy-status]')).toHaveText('Copied');
  const clip = await page.evaluate(() => navigator.clipboard.readText());
  expect(clip).toContain('E2E week in review');
  expect(clip).toContain('E2E newsletter paragraph');
  await expect(page.locator('[data-hero-brief] [data-copy-status]')).toHaveText('', { timeout: 6000 });   // confirmation fades
});

test('lead cards: a 4-tier ring color, an "Est. $XXk GCI" badge on the right, and icon chips without distress facts', async ({ page }) => {
  await page.goto('/leads?q=E2E');
  const card = page.locator('article', { hasText: '1 E2E Test Way' }).first();
  await expect(card).toBeVisible();
  const right = card.locator('[data-card-right]');
  await expect(right.locator('svg[data-tier]')).toHaveCount(1);
  const stroke = await right.locator('svg circle').nth(1).getAttribute('stroke');
  expect(stroke).toMatch(/^var\(--color-tier-(immediate|priority|watchlist|monitor)\)$/);
  const gci = right.locator('[data-gci-badge]');
  await expect(gci).toHaveText(/^Est\. \$\d+(\.\d)?[kM] GCI$/);
  await expect(gci).toHaveClass(/sample-fact/);                                                // the test parcel's value is sample data
  const rbox = (await right.boundingBox())!, cbox = (await card.boundingBox())!;
  expect(rbox.x).toBeGreaterThan(cbox.x + cbox.width / 2);                                     // right side of the card
  expect(await card.locator('[data-fact-chips] [data-chip-icon]').count()).toBeGreaterThan(0);
  const text = (await card.innerText()).toLowerCase();
  for (const w of ['tax default', 'ownership transfer', 'financial pressure', 'death', 'probate']) expect(text).not.toContain(w);
});

test('map: lens switcher recolors points, clusters use the score tiers, and the drawer opens the lead dossier', async ({ page }) => {
  const errors = noConsoleErrors(page);
  await page.goto('/map');
  const lensBtn = (name: string) => page.locator('[data-lens-bar]').getByRole('button', { name });
  for (const name of ['Score Tier', 'Estimated Equity', 'Upzoning / SB 9 & SB 79', 'STR Density']) await expect(lensBtn(name)).toBeVisible();
  await expect(lensBtn('Score Tier')).toHaveAttribute('aria-pressed', 'true');
  await expect.poll(() => page.evaluate(() => (window as unknown as { __leadMap?: { querySourceFeatures: (s: string) => unknown[] } }).__leadMap?.querySourceFeatures('leads').length ?? 0), { timeout: 30_000 }).toBeGreaterThan(0);
  const paint = (layer: string) => page.evaluate((l) => JSON.stringify((window as unknown as { __leadMap: { getPaintProperty: (a: string, b: string) => unknown } }).__leadMap.getPaintProperty(l, 'circle-color')), layer);
  const tierPoints = await paint('leads'), tierClusters = await paint('clusters');
  for (const hex of ['#B91C1C', '#B45309', '#1E3A8A', '#64748B']) { expect(tierPoints).toContain(hex); expect(tierClusters).toContain(hex); }
  expect(tierClusters).toContain('maxScore');                                                 // clusters take the highest score inside them
  await expect(page.locator('[data-legend-title]')).toHaveText('Score tier');
  for (const [name, title] of [['Estimated Equity', 'Estimated equity'], ['Upzoning / SB 9 & SB 79', 'Upzoning (estimated)'], ['STR Density', 'STR licenses nearby']] as const) {
    const lens = name === 'Estimated Equity' ? page.waitForResponse((r) => r.url().includes('/api/map-lens')) : null;   // fetched once, then kept
    await lensBtn(name).click();
    if (lens) expect((await lens).status()).toBe(200);
    await expect(lensBtn(name)).toHaveAttribute('aria-pressed', 'true');
    await expect(lensBtn('Score Tier')).toHaveAttribute('aria-pressed', 'false');
    await expect(page.locator('[data-legend-title]')).toHaveText(title);
    const now = await paint('leads');
    expect(now).not.toBe(tierPoints);                                                         // the points were recolored
    expect(await paint('clusters')).not.toBe(tierClusters);
  }
  await lensBtn('Score Tier').click();
  expect(await paint('leads')).toBe(tierPoints);
  // The lens payload has the fields the lenses read.
  const lensJson = await (await page.request.get('/api/map-lens')).json();
  expect(lensJson.available).toBe(true);
  expect(Object.keys(lensJson.equity).length).toBeGreaterThan(0);
  expect(Object.keys(lensJson.upzone).length).toBeGreaterThan(0);
  expect(lensJson.str.length).toBeGreaterThan(0);
  // Drawer: lot size, zoning, estimated GCI, top signal and a prominent dossier action.
  await page.locator('#map-results [data-apn]').first().click();
  const drawer = page.locator('[data-drawer="lead-preview"]');
  await expect(drawer).toBeVisible();
  await expect(drawer.locator('[data-open-dossier]')).toContainText('Open Lead Dossier');
  const facts = drawer.locator('[data-drawer-facts]');
  for (const label of ['Lot size', 'Zoning', 'Est. GCI']) await expect(facts).toContainText(label);
  await expect(facts).toContainText('est.');
  await expect(drawer.locator('[data-drawer-signal]')).toContainText('Top signal');
  const href = await drawer.locator('[data-open-dossier]').getAttribute('href');
  expect(href).toMatch(/^\/leads\/[^/]+$/);
  await drawer.locator('[data-open-dossier]').click();
  await expect(page).toHaveURL(new RegExp(`${href}$`));
  expect(errors.filter((e) => !IGNORED_ERRORS.test(e))).toEqual([]);
});

for (const [w, h] of [[1440, 900], [390, 844]] as const) {
  test(`lead brief at ${w}px: ${w >= 1024 ? '60/40 split workspace with a sticky co-pilot' : 'stacked, nothing overflows'}`, async ({ page, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    await page.setViewportSize({ width: w, height: h });
    await page.goto(brief);
    const left = page.locator('[data-workspace-left]'), right = page.locator('[data-copilot]');
    await expect(left).toBeVisible(); await expect(right).toBeVisible();
    const [lb, rb] = [(await left.boundingBox())!, (await right.boundingBox())!];
    // Co-pilot: channel tabs, copy button, approval status and outcome controls, all visible without switching tabs.
    for (const name of ['Letter', 'Email', 'Call Script']) await expect(right.getByRole('tab', { name })).toBeVisible();
    await expect(right.locator('#copy-script')).toBeVisible();
    await expect(right.locator('[data-approval-status]')).toContainText('Approval status');
    await expect(right.locator('[data-blockers]')).toContainText('DRE license');
    await expect(right.locator('[data-outcome-card] [data-outcome=contacted]')).toBeVisible();
    // Left: thesis, angle, score bars, dossier, timeline.
    await expect(left.locator('[data-why-card]')).toBeVisible();
    await expect(left.locator('[data-ai-angle]')).toBeVisible();
    await expect(left.locator('[data-score-card]')).toBeVisible();
    await expect(left.locator('[data-dossier]')).toBeVisible();
    await expect(left.locator('[data-timeline]')).toBeVisible();
    if (w >= 1024) {
      expect(Math.abs(lb.y - rb.y)).toBeLessThan(2);
      const ratio = lb.width / (lb.width + rb.width);
      expect(ratio).toBeGreaterThan(0.56); expect(ratio).toBeLessThan(0.64);                  // about 60%
      expect(await right.evaluate((e) => getComputedStyle(e).position)).toBe('sticky');
      await page.evaluate(() => window.scrollTo(0, 700));
      expect(Math.abs((await right.boundingBox())!.y - 16)).toBeLessThan(40);                  // it stays in view while the left column scrolls
    } else {
      expect(rb.y).toBeGreaterThan(lb.y + lb.height - 1);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    }
    // Copy script copies the open tab as it reads now.
    await right.getByRole('tab', { name: 'Letter' }).click();
    const text = await right.locator('[role=tabpanel]:not([hidden]) [data-draft-text]').first().evaluate((e) => (e instanceof HTMLTextAreaElement ? e.value : e.textContent ?? ''));
    await right.locator('#copy-script').click();
    await expect(right.locator('[data-copy-status]')).toHaveText('Copied');
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(text.trim());
    // Distress records stay in the labeled sensitive section on the left, never in the co-pilot.
    expect((await right.innerText()).toLowerCase()).not.toMatch(/tax default|probate|deceased/);
  });
}

test('presentation: a print-ready seller consultation dossier with estimated equity, net proceeds, momentum and area activity', async ({ page }) => {
  await page.goto(`${brief}/presentation`);
  const doc = page.locator('[data-dossier-print]');
  await expect(doc.getByRole('heading', { name: '1 E2E Test Way' })).toBeVisible();
  await expect(doc).toContainText('Seller consultation dossier');
  await expect(doc).toContainText('The Kaiser Team');
  const eq = doc.locator('[data-equity-section]');
  await expect(eq).toContainText('Estimated equity');
  await expect(eq.locator('[data-net-proceeds]')).toContainText('Est. seller net proceeds');
  await expect(eq.locator('[data-net-proceeds]')).toContainText('to');
  await expect(eq.locator('[data-net-proceeds]')).toContainText('estimated');
  await expect(eq.getByText('Sample', { exact: true }).first()).toBeVisible();                // the test parcel's owner data is sample
  await expect(doc.locator('[data-momentum]')).toContainText('momentum');
  await expect(doc.locator('[data-around]')).toContainText('Recent permit and upzoning activity');
  await expect(doc.locator('[data-around]')).toContainText('estimated');
  // No owner identity or mortgage detail on the printout.
  const body = await page.locator('body').innerText();
  for (const secret of [SECRET_OWNER, 'Secret Mailing', 'Seattle', 'Open mortgage', 'tax default']) expect(body).not.toContain(secret);
  // Print media: the toolbar is gone, the page is white, and the browser can render it to a PDF.
  await page.emulateMedia({ media: 'print' });
  await expect(page.locator('#print-btn')).toBeHidden();
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe('rgb(255, 255, 255)');
  const pdf = await page.pdf({ format: 'Letter', printBackground: true });
  expect(pdf.length).toBeGreaterThan(5_000);
  expect(pdf.subarray(0, 4).toString()).toBe('%PDF');
});

test('Today: a New signals row has the date on one line and the source and a truncated id on their own line', async ({ page }) => {
  await page.goto('/');
  const row = page.locator('[data-signal-item]').first();
  await expect(row).toBeVisible();
  const [d, src] = await Promise.all([row.locator('[data-signal-date]').boundingBox(), row.locator('[data-signal-source]').boundingBox()]);
  expect(src!.y).toBeGreaterThan(d!.y + d!.height - 2);                                          // the source line is below the date line
  const id = row.locator('[data-record-id]');
  await expect(id).toHaveCSS('text-overflow', 'ellipsis');
  expect(await id.getAttribute('title')).toBe((await id.textContent())!.trim());                // the full id is in the tooltip
  await expect(row.locator('[data-signal-date]')).not.toContainText('·');
});

test('Today: the four stat tiles render (the first-full-week rule is covered by npm run test:unit)', async ({ page }) => {
  await page.goto('/');
  for (const m of ['signals', 'drafts', 'outcomes', 'active_leads']) await expect(page.locator(`[data-stat="${m}"]`)).toBeVisible();
});

// ---- Phase 5F: AI layer -----------------------------------------------------------------------------------------
test('lead brief: "Why this lead" and the AI brief are one card: headline, summary, recipe chips, angle, then collapsed Sources', async ({ page }) => {
  const errors = noConsoleErrors(page);
  await page.goto(brief);
  const card = page.locator('[data-why-card]');
  await expect(card).toHaveCount(1);                                                          // one card, not two
  await expect(page.getByRole('heading', { name: 'Why this lead' })).toHaveCount(0);          // the AI headline replaces the heading
  await expect(card.locator('[data-ai-tag]').first()).toHaveText('AI summary');
  await expect(card.locator('[data-ai-headline]')).toHaveText('E2E recent remodel permits and long ownership');
  await expect(card.getByText('Sample', { exact: true })).toBeVisible();                       // the brief cites a sample owner fact
  // Order inside the card: headline, summary, recipe chips, suggested angle (internal), Sources.
  const ys = await Promise.all(['[data-ai-headline]', '[data-ai-summary]', '[data-recipe-tag]', '[data-ai-angle]', '[data-ai-sources]'].map(async (q) => (await card.locator(q).first().boundingBox())!.y));
  expect([...ys].sort((x, y) => x - y)).toEqual(ys);
  await expect(card.locator('[data-ai-angle]')).toContainText('(internal)');
  // Sources are collapsed, count their claims, and open on click.
  const sources = card.locator('[data-ai-sources]');
  await expect(sources.locator('summary')).toHaveText('Sources (2)');
  await expect(card.locator('[data-ai-claim]').first()).toBeHidden();
  await sources.locator('summary').click();
  await expect(card.locator('[data-ai-claim]')).toHaveCount(2);
  // Score components are their own card below it.
  const score = page.locator('[data-score-card]');
  await expect(score.getByRole('heading', { name: 'Score components' })).toBeVisible();
  expect((await card.boundingBox())!.y).toBeLessThan((await score.boundingBox())!.y);
  // A claim that cites a signal jumps to that record in the timeline; an owner fact jumps to the owner dossier.
  const links = card.locator('[data-claim-link]');
  await expect(links).toHaveCount(2);
  expect(await links.nth(0).getAttribute('href')).toMatch(/^#rec-[0-9a-f-]{36}$/);
  await links.nth(0).click();
  await expect(page.locator((await links.nth(0).getAttribute('href'))!)).toBeVisible();
  await links.nth(1).click();
  await expect(page.locator('#owner-h')).toBeVisible();
  expect(errors.filter((e) => !IGNORED_ERRORS.test(e))).toEqual([]);
});

test('a lead with no valid AI output shows the deterministic "Why this lead" in the same card, with no AI tag', async ({ page }) => {
  await page.goto(`/leads/${TEST_APN2}`);
  const card = page.locator('[data-why-card]');
  await expect(card).toHaveCount(1);
  await expect(card.getByRole('heading', { name: 'Why this lead' })).toBeVisible();
  await expect(card.locator('[data-why-text]')).toContainText('Older home on a large lot');
  await expect(card.locator('[data-ai-tag], [data-ai-sources], [data-ai-angle]')).toHaveCount(0);
});

test('Leads: the AI headline is the bold primary line with a sparkle icon, the top signal is the small gray line, no AI pill', async ({ page }) => {
  await page.goto('/leads?q=E2E');
  await expect(page.getByText('Headlines written by AI')).toHaveCount(1);                      // one note in the section header
  const row = page.locator('article', { hasText: '1 E2E Test Way' });
  const head = row.locator('[data-ai-headline]');
  await expect(head).toContainText('E2E recent remodel permits and long ownership');
  expect(await head.evaluate((e) => Number(getComputedStyle(e).fontWeight))).toBeGreaterThanOrEqual(600);
  await expect(row.locator('[data-ai-sparkle]')).toHaveAttribute('title', 'AI summary');
  await expect(row.locator('[data-ai-tag]')).toHaveCount(0);                                   // the per-row pill is gone
  await expect(row.getByText('AI SUMMARY', { exact: false })).toHaveCount(0);
  const [hy, sy] = await Promise.all([head.boundingBox(), row.locator('[data-top-signal]').boundingBox()]);
  expect(hy!.y).toBeLessThan(sy!.y);                                                           // top signal sits below, smaller and gray
  expect(await row.locator('[data-top-signal]').evaluate((e) => parseFloat(getComputedStyle(e).fontSize))).toBeLessThan(await head.evaluate((e) => parseFloat(getComputedStyle(e).fontSize)));
  // A row without AI output keeps the current layout: no sparkle, no secondary line.
  const plain = page.locator('article', { hasText: '2 E2E Beach Walk' });
  await expect(plain.locator('[data-ai-sparkle], [data-top-signal]')).toHaveCount(0);
});

test('Today has a "This week" card with the intro and a link to the briefing; Reports keeps an archive; the newsletter export includes the paragraph', async ({ page }) => {
  await page.goto('/');
  const card = page.locator('[data-week-card]');
  await expect(card).toBeVisible();
  await expect(card.locator('[data-ai-tag]')).toHaveText('AI summary');
  await expect(card.locator('[data-week-intro]')).toContainText('E2E intro: activity held steady');
  const top = await card.boundingBox();
  expect(top!.y).toBeLessThan((await page.locator('[data-stat-card], h2:has-text("Top leads")').first().boundingBox())!.y);
  await card.locator('[data-week-link]').click();
  await expect(page).toHaveURL(new RegExp(`/reports/briefings/${TEST_WEEK}$`));
  await expect(page.getByRole('heading', { name: 'E2E week in review' })).toBeVisible();
  await expect(page.locator('[data-briefing-newsletter]')).toContainText('E2E newsletter paragraph');
  await page.goto('/reports');
  await expect(page.getByRole('heading', { name: 'Briefings archive' })).toBeVisible();
  await page.locator('#open-briefings').click();
  await expect(page.locator('[data-briefing-row]').first()).toContainText('E2E week in review');
  await page.goto('/trends/newsletter');
  await expect(page.locator('[data-newsletter-paragraph]')).toContainText('E2E newsletter paragraph');
});

test('Data sources shows the AI task rows with the month against the budget and the warnings; Pipeline shows none of it', async ({ page }) => {
  await page.goto('/data-sources');
  await expect(page.getByRole('heading', { name: 'System & AI pipeline status' })).toBeVisible();
  const row = page.locator('[data-ai-task="lead_brief"]');
  await expect(row).toBeVisible();
  await expect(row).toContainText('$0.0123');
  await expect(page.locator('[data-ai-budget]')).toContainText('budget');
  await expect(page.locator('[data-ai-warnings]')).toContainText('E2E warning');
  // The AI block is the last thing on the page, below every data source card.
  const [cards, ai] = await Promise.all([page.locator('[data-source]').last().boundingBox(), page.locator('[data-ai-pipeline]').boundingBox()]);
  expect(ai!.y).toBeGreaterThan(cards!.y);
  // Agents and brokers never see tokens or costs in their sales funnel.
  await page.goto('/pipeline');
  await expect(page.locator('[data-ai-pipeline], [data-ai-task], [data-ai-budget]')).toHaveCount(0);
  const text = await page.locator('main').innerText();
  expect(text).not.toMatch(/OpenRouter|token|Spent this month|budget|\$0\.0/i);
});

test('Pipeline is a sales progression: Flagged to Listing with conversion and estimated GCI, labeled est. and Sample', async ({ page }) => {
  await page.goto(brief);                                    // log one outcome so the funnel has events
  await page.locator('[data-outcome=contacted]').click();
  await expect(page.locator('[data-flash=ok]')).toContainText('Outcome recorded');
  await page.goto('/pipeline');
  const stages = page.locator('[data-pipeline-stage]');
  await expect(stages).toHaveCount(5);
  expect(await stages.evaluateAll((els) => els.map((e) => e.querySelector('.eyebrow')!.textContent))).toEqual(['Flagged', 'Contacted', 'Conversation', 'Appointment', 'Listing']);
  await expect(page.locator('[data-pipeline-stage=contacted] [data-stage-rate]')).toContainText('of flagged');
  const gci = page.locator('[data-pipeline-stage=signal] [data-stage-gci]');
  await expect(gci).toContainText('est. GCI');
  await expect(gci).toContainText('Sample');                // the test parcel's owner value is sample data
  await expect(page.locator('[data-pipeline-progression]')).toContainText('2.5%');
  await expect(page.locator('[data-outcome-row]').first()).toBeVisible();
});

test('Recipes: each lead shows a fact from its own recipe, never the global active-STR-license line', async ({ page }) => {
  await page.goto('/recipes');
  for (const key of ['builder_bait', 'downsizer', 'stalled_project', 'tired_landlord', 'pre_list_prep', 'insurance_squeeze']) {
    const lines = page.locator(`article[data-recipe=${key}] [data-top-signal]`);
    for (const t of await lines.allInnerTexts()) expect(t, key).not.toMatch(/Active short-term rental license/);
  }
  const down = page.locator('article[data-recipe=downsizer] [data-top-signal]');
  if (await down.count()) for (const t of await down.allInnerTexts()) expect(t).toMatch(/years? owned|No open mortgage/);
  const bait = page.locator('article[data-recipe=builder_bait] [data-top-signal]');
  if (await bait.count()) for (const t of await bait.allInnerTexts()) expect(t).toMatch(/SB 9|SB 79|lot split|Parcel map|Demolition/i);
});

test('Trends: routine systems work and other permits are hidden by default and come back with the toggle', async ({ page }) => {
  await page.goto('/trends');
  const toggle = page.locator('[data-chart-toggle]:visible').first();
  await expect(page.getByLabel('Include routine & other permits').first()).toBeVisible();
  const id = (await toggle.getAttribute('data-chart-toggle'))!;
  const legend = page.locator(`[data-chart-legend="${id}"]`);
  await expect(legend).not.toContainText('Routine systems work');
  await expect(legend).not.toContainText('Other');
  await toggle.check();
  await expect(legend).toContainText('Routine systems work');
});

test('Today: the Active leads tile says "Scoring updated" (no percentage) while the scoring model differs between the two weeks', async ({ page }) => {
  await page.goto('/');
  const delta = page.locator('[data-stat=active_leads] [data-delta]');
  await expect(delta).toHaveText('Scoring updated');
  await expect(delta).not.toContainText('%');
});

test('with no AI rows the dashboard renders normally and shows nothing AI-related', async ({ page }) => {
  holdAiRows();
  try {
    const errors = noConsoleErrors(page);
    for (const path of ['/', '/leads', brief, '/reports', '/reports/briefings', '/pipeline', '/data-sources', '/trends/newsletter']) {
      const res = await page.goto(path);
      expect(res!.status(), path).toBeLessThan(400);
      await expect(page.locator('[data-ai-tag], [data-ai-brief], [data-week-card], [data-ai-pipeline], [data-ai-headline], [data-newsletter-ai]'), path).toHaveCount(0);
    }
    await page.goto(brief);
    await expect(page.getByRole('heading', { name: 'Why this lead' })).toBeVisible();
    await page.goto('/');
    await expect(page.getByRole('heading', { name: /^Good (morning|afternoon|evening)/ })).toBeVisible();
    const res = await page.goto(`/reports/briefings/${TEST_WEEK}`);
    expect(res!.status()).toBe(404);
    await page.goto('/reports');
    await expect(page.getByRole('heading', { name: 'Briefings archive' })).toHaveCount(0);
    expect(errors.filter((e) => !IGNORED_ERRORS.test(e))).toEqual([]);
  } finally {
    releaseAiRows();
  }
});


// ---- Phase 5H ---------------------------------------------------------------------------------------------------
test('Today: the "New signals" tile and the "New signals" panel use one definition and one window, so the counts match', async ({ page }) => {
  await page.goto('/');
  const tile = Number((await page.locator('[data-stat="signals"] [data-stat-value]').innerText()).replace(/,/g, ''));
  const panel = Number(await page.locator('section:has(h2:has-text("New signals")) [data-rail-count]').getAttribute('data-rail-count'));
  expect(tile).toBeGreaterThan(0);                 // the seeded test parcel has permits approved Nov 10
  expect(panel).toBe(tile);
});

test('lead lists: the gray line is the top-contribution signal, with a correct plural, and no duplicate "New" chip', async ({ page }) => {
  await page.goto("/leads?q=E2E");          // the filter parameter is q; it keeps the test parcel on the page whatever the score spread
  const card = page.locator('article', { hasText: '1 E2E Test Way' }).first();
  await expect(card).toBeVisible();
  const text = await card.innerText();
  expect(text).toContain('3 building permits approved Nov 10');
  expect(text).not.toMatch(/permit \(.*\) permits/i);
  // the status pill says New, so the New tag by the address must not repeat it
  const pillNew = await card.locator('span:text-is("New")').count();
  expect(pillNew).toBeLessThanOrEqual(1);
  await page.goto(brief);
  await expect(page.locator('main')).toContainText('3 building permits approved Nov 10');
});

// ---- Phase 7: precision terminal ---------------------------------------------------------------
test('precision rail: collapses to 64px, expands on hover, persists, and the command header stays 48px', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');
  const rail = page.locator('#sidebar');
  const root = page.locator('html');
  await expect(rail).toBeVisible();
  await expect(root).toHaveAttribute('data-rail', 'expanded');
  expect(Math.round((await rail.boundingBox())!.width)).toBe(232);

  const command = page.locator('header.command-bar');
  await expect(command).toBeVisible();
  await expect(command).toContainText('Model');
  expect(Math.round((await command.boundingBox())!.height)).toBe(48);

  await page.locator('[data-rail-toggle]').click();
  await expect(root).toHaveAttribute('data-rail', 'compact');
  await page.mouse.move(800, 500);                             // leaving the rail lets the compact width show
  await page.waitForTimeout(250);
  expect(Math.round((await rail.boundingBox())!.width)).toBe(64);
  expect(await page.evaluate(() => localStorage.getItem('ts-rail'))).toBe('compact');

  await page.reload();
  await expect(root).toHaveAttribute('data-rail', 'compact');
  await page.mouse.move(800, 500);
  await page.waitForTimeout(250);
  expect(Math.round((await rail.boundingBox())!.width)).toBe(64);

  // Hovering the compact rail reveals the labels without pushing the main column.
  await rail.hover();
  await page.waitForTimeout(250);
  expect(Math.round((await rail.boundingBox())!.width)).toBe(232);

  await page.locator('[data-rail-toggle]').click();
  await expect(root).toHaveAttribute('data-rail', 'expanded');
  await page.waitForTimeout(250);
  expect(Math.round((await rail.boundingBox())!.width)).toBe(232);
});

test('slide-over dossier: rows open in place, J/K triage, copy works, Escape closes, and the page never reloads', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/leads?q=E2E');
  const rows = page.locator('[data-lead-row]');
  await expect(rows.first()).toBeVisible();
  expect(await rows.count()).toBeGreaterThan(1);
  const url = page.url();

  await rows.first().click();
  const drawer = page.locator('#dossier-drawer');
  await expect(drawer).toBeVisible();
  await expect.poll(async () => drawer.locator('[data-dossier-title]').innerText()).not.toBe('Lead dossier');
  await expect(drawer.locator('[data-dossier-open-full]')).toHaveAttribute('href', /^\/leads\//);
  await expect(drawer.locator('[data-dossier-aerial] svg, [data-dossier-aerial] canvas').first()).toBeVisible();
  await expect(drawer.locator('[data-dossier-script]')).toBeVisible();
  const copy = drawer.locator('[data-dossier-copy]');
  await copy.click();
  await expect(copy).toHaveText('Copied');
  expect((await page.evaluate(() => navigator.clipboard.readText())).length).toBeGreaterThan(20);

  const first = await drawer.locator('[data-dossier-title]').innerText();
  await page.keyboard.press('j');
  await expect.poll(async () => drawer.locator('[data-dossier-title]').innerText()).not.toBe(first);
  const second = await drawer.locator('[data-dossier-title]').innerText();
  await page.keyboard.press('k');
  await expect.poll(async () => drawer.locator('[data-dossier-title]').innerText()).toBe(first);
  expect(second).not.toBe(first);

  await page.keyboard.press('Escape');
  await expect(drawer).toBeHidden();
  expect(page.url()).toBe(url);
});

test('lead brief: the satellite parcel aerial renders with a boundary overlay or the architectural fallback', async ({ page }) => {
  await page.goto(brief);
  const aerial = page.locator('[data-hero-aerial] [data-parcel-aerial-figure]');
  await expect(aerial).toBeVisible();
  await expect(aerial.locator('[data-aerial-map] canvas, [data-aerial-fallback] svg').first()).toBeVisible();
  await expect(aerial).toContainText(/Parcel boundary|No geometry on file/);
  await expect(aerial).toContainText('Esri World Imagery');
});

test('Trends: the Opportunity Matrix plots leads and its accessible table opens the dossier drawer', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/trends');
  const matrix = page.locator('[data-opportunity-matrix]');
  await expect(matrix).toBeVisible();
  await expect(matrix.locator('[data-matrix-chart] canvas')).toBeVisible();
  await expect(matrix.locator('[data-matrix-table] summary')).toContainText('View the top');
  await matrix.locator('[data-matrix-table] summary').click();
  const row = matrix.locator('[data-matrix-row]').first();
  await expect(row).toBeVisible();
  const apn = await row.getAttribute('data-matrix-row');
  expect(apn).toBeTruthy();
  await row.click();
  const drawer = page.locator('#dossier-drawer');
  await expect(drawer).toBeVisible();
  await expect.poll(async () => drawer.locator('[data-dossier-open-full]').getAttribute('href')).toContain(apn!);
});
