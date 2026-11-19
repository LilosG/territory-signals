/**
 * Saves desktop (1440x900) and mobile (390x844) screenshots of every screen, against the LIVE local stack, to
 * dashboard/screenshots/. Fails on any console error, failed request, or horizontal overflow, and checks the
 * mobile Today layout. Prereqs: Docker + `supabase start`, `.env` copied from `.env.example`.
 * Run: npm run screenshots   (starts the dev server itself unless one is already on :3000)
 *
 * It signs in as a temporary team member and creates one temporary share link; both are removed afterwards.
 */
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { cleanup } from '../e2e/global-teardown';
import { rest, TEST_EMAIL } from '../e2e/env';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
const out = resolve(root, 'screenshots');
mkdirSync(out, { recursive: true });
const base = 'http://127.0.0.1:3000';
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

const up = async () => { try { return (await fetch(`${base}/login`)).ok; } catch { return false; } };
let server: ReturnType<typeof spawn> | null = null;
if (!(await up())) {
  server = spawn('npx', ['astro', 'dev'], { cwd: root, stdio: 'ignore' });
  for (let i = 0; i < 80 && !(await up()); i++) await sleep(500);
  if (!(await up())) throw new Error('dev server did not start');
}

const token = 'screenshot' + 'a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718';
const dropLink = () => rest(`/rest/v1/share_links?token=eq.${token}`, { method: 'DELETE' });
let failures = 0;
const plain = await chromium.launch();
const gl = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
try {
  await cleanup();
  await rest('/rest/v1/team_members', { method: 'POST', json: { email: TEST_EMAIL, name: 'Screenshot Tester', role: 'agent' } });
  await rest('/auth/v1/admin/users', { method: 'POST', json: { email: TEST_EMAIL, email_confirm: true } });
  const link = await rest('/auth/v1/admin/generate_link', { method: 'POST', json: { type: 'magiclink', email: TEST_EMAIL } });

  // Real records to show: the top-scored lead, and a lead that has a (blocked) draft waiting for approval.
  const top = (await rest('/rest/v1/rpc/leads_page', { method: 'POST', json: { p_limit: 1 } }))[0].apn as string;
  const drafted = (await rest('/rest/v1/outreach?status=eq.awaiting_approval&select=apn&limit=1'))[0].apn as string;
  await dropLink();
  await rest('/rest/v1/share_links', { method: 'POST', json: { token, apn: top, created_by: TEST_EMAIL } });

  const pages: [string, string, boolean][] = [   // name, path, needs session
    ['login', '/login', false], ['share', `/share/${token}`, false],
    ['today', '/', true], ['leads', '/leads', true], ['map', '/map', true],
    ['lead-brief', `/leads/${top}`, true], ['lead-brief-draft', `/leads/${drafted}#drafts`, true], ['lead-presentation', `/leads/${top}/presentation`, true],
    ['trends', '/trends', true], ['trends-newsletter', '/trends/newsletter', true], ['pipeline', '/pipeline', true], ['settings', '/settings', true], ['design-system', '/design-system', true],
  ];
  // The link is single use: sign in once and reuse the session for every page.
  const login = await plain.newContext();
  const lp = await login.newPage();
  await lp.goto(`${base}/auth/callback?token_hash=${link.hashed_token}&type=magiclink`);
  await lp.waitForURL((u) => u.pathname === '/');
  const state = await login.storageState();
  await login.close();
  const viewports = { desktop: { width: 1440, height: 900 }, mobile: { width: 390, height: 844 } } as const;

  for (const [vpName, vp] of Object.entries(viewports)) {
    for (const [name, path, authed] of pages) {
      const browser = name === 'map' ? gl : plain;
      const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: 1, isMobile: vpName === 'mobile', ...(authed ? { storageState: state } : {}) });
      const page = await ctx.newPage();
      const errors: string[] = [];
      page.on('console', (m) => { if (m.type() === 'error') errors.push(`console: ${m.text()}`); });
      page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
      // Map tile requests are cancelled on purpose when the view moves; that is not an error.
      page.on('requestfailed', (r) => r.url().includes('tiles.openfreemap.org') || errors.push(`requestfailed: ${r.url()} ${r.failure()?.errorText}`));
      page.on('response', (r) => { if (r.status() >= 400 && !r.url().includes('/share/')) errors.push(`http ${r.status()}: ${r.url()}`); });
      await page.goto(base + path, { waitUntil: 'networkidle' });
      if (name === 'map') { await page.waitForFunction(() => document.querySelector('.maplibregl-canvas') !== null); await sleep(5000); } else await sleep(600);

      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      if (overflow > 1) errors.push(`horizontal overflow: ${overflow}px`);

      if (name === 'today' && vpName === 'mobile') {
        const box = await page.locator('article').first().boundingBox();
        if (!box || box.y + box.height > vp.height) errors.push(`first lead card is not fully visible without scrolling (bottom ${box ? Math.round(box.y + box.height) : 'n/a'} > ${vp.height})`);
        if (await page.getByRole('link', { name: 'Open map' }).isVisible()) errors.push('"Open map" should be hidden on mobile');
      }
      if (name === 'map') {
        await page.selectOption('select[name=hood]', 'Mission Beach'); await sleep(2500);
        const n = await page.evaluate(() => document.getElementById('map-count')?.textContent);
        if (!n || !/^[\d,]+ parcels$/.test(n) || n.startsWith('0')) errors.push(`filter did not apply: ${n}`);
        await page.selectOption('select[name=hood]', ''); await sleep(2000);
        if (vpName === 'desktop') {
          await page.locator('#map-results button').first().click(); await sleep(1500);
          if (!(await page.locator('[data-drawer=lead-preview]').isVisible())) errors.push('drawer did not open');
          await page.screenshot({ path: resolve(out, `map-drawer.${vpName}.png`) });
          await page.keyboard.press('Escape');
        }
      }
      await page.screenshot({ path: resolve(out, `${name}.${vpName}.png`), fullPage: name !== 'map' });
      console.log(`${errors.length ? 'FAIL' : 'ok  '} ${vpName} ${path.split('#')[0]}`);
      for (const e of errors) { console.log(`     ${e}`); failures++; }
      await ctx.close();
    }
  }
} finally {
  await plain.close(); await gl.close();
  await dropLink();
  await cleanup();
  server?.kill();
}
console.log(failures ? `\n${failures} problem(s)` : '\nAll screens clean: no console errors, no horizontal overflow.');
process.exit(failures ? 1 : 0);
