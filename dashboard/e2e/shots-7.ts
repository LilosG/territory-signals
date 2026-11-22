/**
 * Phase 7 screenshots: Today, Leads with the slide-over dossier, the Lead Brief with the satellite parcel aerial, and
 * Trends with the Opportunity Matrix, at 1440x900 and 390x844, saved to docs/screenshots/7/.
 * Against the LIVE local stack (real top lead). Signs in as a temporary team member and removes it afterwards; fails
 * on a page error or horizontal overflow. Run: npx tsx e2e/shots-7.ts   (with the dev server on :3000)
 */
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { chromium } from 'playwright';
import { cleanup } from './global-teardown';
import { rest, TEST_EMAIL } from './env';

const base = 'http://127.0.0.1:3000';
const out = resolve(import.meta.dirname, '../../docs/screenshots/7');
mkdirSync(out, { recursive: true });

await cleanup();
await rest('/rest/v1/team_members', { method: 'POST', json: { email: TEST_EMAIL, name: 'Screenshot Tester', role: 'agent' } });
await rest('/auth/v1/admin/users', { method: 'POST', json: { email: TEST_EMAIL, email_confirm: true } });
const link = await rest('/auth/v1/admin/generate_link', { method: 'POST', json: { type: 'magiclink', email: TEST_EMAIL } });
const top = (await rest('/rest/v1/rpc/leads_page', { method: 'POST', json: { p_limit: 1 } }))[0].apn as string;

const gl = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
let failures = 0;
try {
  const ctx0 = await gl.newContext();
  const p0 = await ctx0.newPage();
  await p0.goto(`${base}/auth/callback?token_hash=${link.hashed_token}&type=magiclink`);
  await p0.waitForURL((u) => u.pathname === '/', { timeout: 30_000 });
  const state = await ctx0.storageState();
  await ctx0.close();

  for (const [w, h] of [[1440, 900], [390, 844]] as const) {
    const ctx = await gl.newContext({ storageState: state, viewport: { width: w, height: h } });
    const page = await ctx.newPage();
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));

    // Today
    await page.goto(`${base}/`);
    await page.waitForLoadState('networkidle');
    if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)) { console.log(`OVERFLOW today ${w}`); failures++; }
    await page.screenshot({ path: `${out}/today-${w}.png`, fullPage: true });
    console.log(`today-${w}.png`);

    // Leads with the universal slide-over dossier open
    await page.goto(`${base}/leads`);
    await page.waitForLoadState('networkidle');
    await page.waitForFunction(() => (window as unknown as { __dossierReady?: boolean }).__dossierReady === true, null, { timeout: 20_000 });
    await page.locator('[data-lead-row]').first().click();
    await page.locator('#dossier-drawer:not([hidden])').waitFor({ timeout: 20_000 });
    await page.waitForFunction(() => {
      const d = document.querySelector('#dossier-drawer');
      return !!d && !!d.querySelector('#dossier-facts-h') && !!d.querySelector('[data-dossier-aerial]');
    }, null, { timeout: 20_000 });
    await page.waitForFunction(() => {
      const el = document.querySelector('[data-dossier-aerial]');
      if (!el) return false;
      if (!el.querySelector('[data-aerial-map]')) return !!el.querySelector('[data-aerial-fallback] svg');
      return el.getAttribute('data-aerial-ready') === '1';
    }, null, { timeout: 20_000 });
    await page.waitForTimeout(2200);                             // satellite tiles / SVG fallback
    if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)) { console.log(`OVERFLOW leads ${w}`); failures++; }
    await page.screenshot({ path: `${out}/leads-dossier-${w}.png` });
    console.log(`leads-dossier-${w}.png`);

    // Lead brief with the satellite parcel aerial
    await page.goto(`${base}/leads/${top}`);
    await page.waitForLoadState('networkidle');
    await page.waitForFunction(() => !!document.querySelector('[data-hero-aerial] [data-aerial-ready], [data-hero-aerial] [data-aerial-fallback] svg'), null, { timeout: 30_000 });
    await page.waitForTimeout(2500);                             // Esri imagery paint
    if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)) { console.log(`OVERFLOW lead-brief ${w}`); failures++; }
    await page.screenshot({ path: `${out}/lead-brief-${w}.png`, fullPage: true });
    console.log(`lead-brief-${w}.png`);

    // Trends with the Opportunity Matrix
    await page.goto(`${base}/trends`);
    await page.waitForLoadState('networkidle');
    await page.waitForFunction(() => {
      const el = document.querySelector('[data-matrix-chart] canvas') as HTMLCanvasElement | null;
      return !!el && el.width > 0 && el.height > 0;
    }, null, { timeout: 30_000 });
    await page.waitForTimeout(1200);
    if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)) { console.log(`OVERFLOW trends ${w}`); failures++; }
    await page.screenshot({ path: `${out}/trends-matrix-${w}.png`, fullPage: true });
    console.log(`trends-matrix-${w}.png`);

    if (errors.length) { console.log(`page errors at ${w}:`, errors); failures++; }
    await ctx.close();
  }
} finally {
  await gl.close();
  await cleanup();
}
console.log(`lead used: ${top}`);
process.exit(failures ? 1 : 0);
