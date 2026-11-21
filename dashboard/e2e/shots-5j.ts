/**
 * Phase 5J screenshots: Today, Map, Lead Brief and Lead Presentation at 1440x900 and 390x844, saved to docs/screenshots/5j/.
 * Against the LIVE local stack (real top lead). Signs in as a temporary team member and removes it afterwards; fails on a page
 * error or horizontal overflow. Run: npx tsx e2e/shots-5j.ts   (with the dev server on :3000)
 */
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { chromium } from 'playwright';
import { cleanup } from './global-teardown';
import { rest, TEST_EMAIL } from './env';

const base = 'http://127.0.0.1:3000';
const out = resolve(import.meta.dirname, '../../docs/screenshots/5j');
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
    for (const [shot, path] of [['today', '/'], ['map', '/map'], ['lead-brief', `/leads/${top}`], ['lead-presentation', `/leads/${top}/presentation`]] as const) {
      await page.goto(`${base}${path}`);
      await page.waitForLoadState('networkidle');
      if (shot === 'map') {
        await page.waitForFunction(() => ((window as unknown as { __leadMap?: { querySourceFeatures: (s: string) => unknown[] } }).__leadMap?.querySourceFeatures('leads').length ?? 0) > 0, null, { timeout: 45_000 });
        await page.waitForTimeout(2500);                       // let basemap tiles paint
      }
      if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)) { console.log(`OVERFLOW ${shot} ${w}`); failures++; }
      await page.screenshot({ path: `${out}/${shot}-${w}.png`, fullPage: shot !== 'map' });
      console.log(`${shot}-${w}.png`);
      if (shot === 'map') {                                    // the same map with the Estimated Equity lens and the lead drawer open
        await page.getByRole('button', { name: 'Estimated Equity' }).click();
        await page.waitForTimeout(1200);
        await page.locator('#map-results [data-apn]').first().click().catch(() => page.evaluate(() => 0));
        if (w < 1024) { /* the results list is desktop-only */ }
        await page.waitForTimeout(1500);
        await page.screenshot({ path: `${out}/map-equity-lens-drawer-${w}.png` });
        console.log(`map-equity-lens-drawer-${w}.png`);
      }
    }
    if (errors.length) { console.log(`page errors at ${w}:`, errors); failures++; }
    await ctx.close();
  }
} finally {
  await gl.close();
  await cleanup();
}
console.log(`lead used: ${top}`);
process.exit(failures ? 1 : 0);
