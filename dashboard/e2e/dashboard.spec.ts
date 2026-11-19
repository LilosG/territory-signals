import { expect, test, type Page } from '@playwright/test';
import { SECRET_OWNER, stack, TEST_APN, TEST_EMAIL } from './env';

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

  test('login with a real magic link from the local mail viewer', async ({ page, request }) => {
    const mail = stack().mail;
    await page.goto('/login');
    await page.getByLabel('Email').fill(TEST_EMAIL);
    await page.getByRole('button', { name: 'Email me a sign-in link' }).click();
    const limited = await page.getByText('Too many sign-in emails').isVisible();
    test.skip(limited, 'Local Supabase limits sign-in emails per hour; rerun later');
    await expect(page.getByText('Check your email.')).toBeVisible();

    let link = '';
    await expect.poll(async () => {
      const list = await (await request.get(`${mail}/api/v1/search?query=${encodeURIComponent(`to:${TEST_EMAIL}`)}`)).json() as { messages?: { ID: string }[] };
      const id = list.messages?.[0]?.ID; if (!id) return '';
      const msg = await (await request.get(`${mail}/api/v1/message/${id}`)).json() as { HTML: string; Text: string };
      link = (msg.HTML.match(/href="([^"]+\/auth\/v1\/verify[^"]+)"/)?.[1] ?? msg.Text.match(/(http\S+\/auth\/v1\/verify\S+)/)?.[1] ?? '').replace(/&amp;/g, '&');
      return link;
    }, { timeout: 20_000 }).not.toBe('');
    await page.goto(link);
    await expect(page).toHaveURL(/127\.0\.0\.1:3000\/$/);
    await expect(page.getByRole('heading', { name: 'Good morning' })).toBeVisible();
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

test('Today loads live data', async ({ page }) => {
  const errors = noConsoleErrors(page);
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Good morning' })).toBeVisible();
  await expect(page.locator('article')).toHaveCount(10);
  await expect(page.getByText('Parcels monitored')).toBeVisible();
  await expect(page.locator('[data-sample-banner]')).toBeVisible();      // live scores still rest on sample owner data
  await expect(page.locator('[data-user-email]')).toHaveText(TEST_EMAIL);
  expect(errors).toEqual([]);
});

test('the map endpoint returns compact GeoJSON for all scored parcels', async ({ request }) => {
  const res = await request.get('/api/map');
  expect(res.status(), await res.text().then((t) => t.slice(0, 300))).toBe(200);
  const fc = await res.json();
  expect(fc.type).toBe('FeatureCollection');
  expect(fc.features.length).toBeGreaterThan(20_000);
  expect(Object.keys(fc.features[0].properties).sort()).toEqual(['apn', 'band', 'neighborhood', 'primary_recipe', 'score']);
  const lj = await (await request.get('/api/map?hood=Mission%20Beach&range=60-100')).json();
  expect(lj.features.length).toBeLessThan(fc.features.length);
  expect(lj.features.every((f: { properties: { neighborhood: string; score: number } }) => f.properties.neighborhood === 'Mission Beach' && f.properties.score >= 60)).toBe(true);
});

test('lead brief shows the data, labels from the catalog and the owner panel', async ({ page }) => {
  await page.goto(brief);
  await expect(page.getByRole('heading', { name: '1 E2E Test Way' })).toBeVisible();
  await expect(page.locator('[data-model-version]')).toHaveText('Model v0.3-handset');
  const owner = page.locator('section[aria-labelledby=owner-h]');
  await expect(owner.getByText(SECRET_OWNER)).toBeVisible();
  await expect(owner.locator('h2').getByText('Sample', { exact: true })).toHaveCount(1);   // one badge, in the header
  await expect(owner.getByText('14 years')).toBeVisible();                                  // whole years
  await expect(owner.getByText('Open mortgage')).toBeVisible();
  const timeline = page.locator('ol').first();
  await expect(timeline).toContainText('Matched by parcel number · 95%');
  await expect(timeline).toContainText('Matched by location · 90%');
  await expect(timeline).not.toContainText(/years owned|absentee|equity|mortgage/i);        // owner traits are not timeline events
});

test('a blocked draft cannot be approved; an unblocked one can, after an edit', async ({ page }) => {
  await page.goto(`${brief}#drafts`);
  // blocked email draft
  await page.getByRole('tab', { name: 'Email' }).click();
  const emailPanel = page.getByRole('tabpanel', { name: 'Email' });
  await expect(emailPanel.locator('[data-blocked]')).toContainText('missing agent name or DRE license');
  await expect(emailPanel.getByRole('button', { name: 'Approve draft' })).toBeDisabled();
  // unblocked letter: edit, then approve
  await page.getByRole('tab', { name: 'Letter' }).click();
  const letter = page.getByRole('tabpanel', { name: 'Letter' });
  await expect(letter.locator('[data-blocked]')).toHaveCount(0);
  await letter.locator('textarea').fill('Hello neighbor,\n\nE2E edited letter.');
  await letter.getByRole('button', { name: 'Save edit' }).click();
  await expect(page.locator('[data-flash=ok]')).toContainText('Edit saved');
  await expect(page.getByRole('tabpanel', { name: 'Letter' }).locator('[data-edited]')).toContainText(`Edited by ${TEST_EMAIL}`);
  await page.getByRole('tabpanel', { name: 'Letter' }).getByRole('button', { name: 'Approve draft' }).click();
  await expect(page.locator('[data-flash=ok]')).toContainText('Draft approved');
  const done = page.getByRole('tabpanel', { name: 'Letter' });
  await expect(done.locator('[data-draft-status]')).toHaveText('Approved');
  await expect(done).toContainText(`Approved by ${TEST_EMAIL}`);
  await expect(done.getByText('E2E edited letter.')).toBeVisible();
  // outreach history uses sentence case and a dash for the empty sent date
  const history = page.getByRole('table', { name: 'Outreach history' });
  await expect(history).toContainText('Approved');
  await expect(history.locator('tbody td').last()).toHaveText('—');
});

test('record an outcome', async ({ page }) => {
  await page.goto(brief);
  await page.getByPlaceholder('Note (optional)').fill('left a voicemail');
  await page.locator('[data-outcome=contacted]').click();
  await expect(page.locator('[data-flash=ok]')).toContainText('Outcome recorded');
  const table = page.getByRole('table', { name: 'Recorded outcomes' });
  await expect(table).toContainText('Contacted');
  await expect(table).toContainText('left a voicemail');
  await page.goto('/pipeline');
  await expect(page.getByText('No outcomes recorded yet')).toHaveCount(0);
  await expect(page.getByText('Runs once owner sale history is connected (Phase 6)')).toBeVisible();
});

test('create a share link, open it signed out (property facts only), then revoke it', async ({ page, browser }) => {
  await page.goto(brief);
  await page.locator('details[data-overflow] summary').click();
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
