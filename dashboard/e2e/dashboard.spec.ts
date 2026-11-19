import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { SECRET_OWNER, stack, TEST_APN, TEST_APN2, TEST_EMAIL } from './env';

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
  await expect(page.getByText('This week by recipe')).toBeVisible();
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
  for (const tab of ['Overview', 'Signals', 'Owner and property', 'Outreach', 'Activity']) await expect(page.getByRole('tab', { name: tab })).toBeVisible();
  await expect(page.locator('[data-model-version]')).toHaveText('Model v0.3-handset');
  await page.getByRole('tab', { name: 'Owner and property' }).click();
  const owner = page.locator('section[aria-labelledby=owner-h]');
  await expect(owner.getByText(SECRET_OWNER)).toBeVisible();
  await expect(owner.locator('h2').getByText('Sample', { exact: true })).toHaveCount(1);   // one badge, in the header
  await expect(owner.getByText('14 years')).toBeVisible();                                  // whole years
  await expect(owner.getByText('Open mortgage')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Sensitive records' })).toBeVisible();     // tax default only appears here, labeled
  await page.getByRole('tab', { name: 'Signals' }).click();
  const timeline = page.locator('ol').first();
  await expect(timeline.locator('[data-event]')).toHaveCount(1);                              // same-day permits collapse into one event
  await expect(timeline).toContainText('3 permits approved');
  await expect(timeline).toContainText('Nov 10, 2026');
  await timeline.getByText('Show all 3').click();
  await expect(timeline.locator('details li')).toHaveCount(3);
  await expect(timeline).toContainText('Matched by parcel number · 95%');
  await expect(timeline).not.toContainText(/years owned|absentee|equity|mortgage|tax default|death|deceased/i);   // owner traits and distress are not timeline events
  await expect(page.getByRole('region', { name: 'Property traits' })).toContainText('SB 9 lot-split eligibility');
});

test('lead cards and lists never show distress or life-event chips', async ({ page }) => {
  await page.goto('/leads');
  const text = (await page.locator('main').innerText()).toLowerCase();
  for (const word of ['tax default', 'ownership transfer', 'financial pressure', 'death', 'deceased', 'probate']) expect(text, word).not.toContain(word);
});

test('a blocked draft cannot be approved; an unblocked one can, after an edit', async ({ page }) => {
  await page.goto(`${brief}#drafts`);
  // blocked email draft
  const emailPanel = page.getByRole('region', { name: 'Email' });
  await expect(emailPanel.locator('[data-blocked]')).toContainText('missing agent name or DRE license');
  await expect(emailPanel.getByRole('button', { name: 'Approve draft' })).toBeDisabled();
  // unblocked letter: edit, then approve
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
  await expect(blockedRow.locator('[data-blocked]')).toContainText('Can’t be approved yet');
  await expect(blockedRow.locator('[data-blocked]')).toContainText('DRE license');
  await expect(blockedRow.locator('[data-blocked]')).not.toContainText(/blocked_reason|rpc|_/);
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

test('Recipes: a card per recipe, idle recipes say why, and links open the filtered Leads list', async ({ page }) => {
  const errors = noConsoleErrors(page);
  await page.goto('/recipes');
  const cards = page.locator('article[data-recipe]');
  expect(await cards.count()).toBeGreaterThan(0);
  const keys = await cards.evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.recipe!));
  expect(keys).not.toContain('financial_pressure');          // distress recipes live only in the lead brief
  expect(keys).not.toContain('quiet_inheritance');
  for (const idle of await page.locator('[data-idle]').all()) await expect(idle).toContainText('Idle.');
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
  for (const secret of [SECRET_OWNER, 'Secret Mailing', 'Seattle', '3,100,000', '2,000,000', 'mortgage', 'equity', 'tax', 'default', 'E2E Beach Walk', TEST_APN2, 'Sample']) {
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
  await page.getByRole('tab', { name: 'Activity' }).click();
  await page.getByPlaceholder('Note (optional)').fill('left a voicemail');
  await page.locator('[data-outcome=contacted]').click();
  await expect(page.locator('[data-flash=ok]')).toContainText('Outcome recorded');
  await page.getByRole('tab', { name: 'Activity' }).click();
  await expect(page.locator('[data-tab-panel=activity]')).toContainText('Contacted');
  await expect(page.locator('[data-tab-panel=activity]')).toContainText('left a voicemail');
  await page.goto('/pipeline');
  await expect(page.getByText('No outcomes recorded yet')).toHaveCount(0);
  await page.goto('/performance');
  await expect(page.getByText('Connects when owner sale history is added in Phase 6')).toBeVisible();
});

test('create a share link from the brief, open it signed out (property facts only), then revoke it', async ({ page, browser }) => {
  await page.goto(brief);
  await page.locator('#create-share').click();
  await expect(page.locator('[data-flash=ok]')).toContainText('Share link created');
  await page.getByRole('tab', { name: 'Activity' }).click();
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
