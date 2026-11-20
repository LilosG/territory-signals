/**
 * Phase 5H screenshots: Today, Leads and the 1505 Felspar St lead page at 1440 wide, saved to docs/screenshots/5h/. Against the LIVE local stack. Signs in as a temporary
 * team member and removes it afterwards. Run: npx tsx scripts/screenshots-5h.ts
 */
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { chromium } from 'playwright';
import { cleanup } from '../e2e/global-teardown';
import { psql, rest, TEST_EMAIL } from '../e2e/env';

const base = 'http://127.0.0.1:3000';
const out = resolve(import.meta.dirname, '../../docs/screenshots/5h');
mkdirSync(out, { recursive: true });

await cleanup();
await rest('/rest/v1/team_members', { method: 'POST', json: { email: TEST_EMAIL, name: 'Screenshot Tester', role: 'agent' } });
await rest('/auth/v1/admin/users', { method: 'POST', json: { email: TEST_EMAIL, email_confirm: true } });
const link = await rest('/auth/v1/admin/generate_link', { method: 'POST', json: { type: 'magiclink', email: TEST_EMAIL } });

// A lead that has a valid AI brief: the highest-scoring one.
const rows = await rest('/rest/v1/latest_ai_outputs?task=eq.lead_brief&select=subject_id&limit=200');
void rows; // (the anon-style service key can read the view; the page picks the lead below)
let apn = process.argv[2];
let plain = process.argv[3];                       // a lead with no AI output
{
  const top = await rest('/rest/v1/rpc/leads_page', { method: 'POST', json: { p_limit: 200 } });
  const have = new Set((rows as { subject_id: string }[]).map((r) => r.subject_id));
  apn ??= (top as { apn: string }[]).find((t) => have.has(t.apn))?.apn ?? top[0].apn;
  plain ??= (top as { apn: string }[]).find((t) => !have.has(t.apn))?.apn;
}
console.log(`with AI: ${apn}; without AI: ${plain}`);

const browser = await chromium.launch();
let failures = 0;
try {
  const ctx0 = await browser.newContext();
  const p0 = await ctx0.newPage();
  await p0.goto(`${base}/auth/callback?token_hash=${link.hashed_token}&type=magiclink`);
  await p0.waitForURL((u) => u.pathname === '/', { timeout: 30_000 });
  const state = await ctx0.storageState();
  await ctx0.close();

  for (const [name, w, h] of [['desktop', 1440, 900]] as const) {
    const ctx = await browser.newContext({ storageState: state, viewport: { width: w, height: h } });
    const page = await ctx.newPage();
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    for (const [shot, path] of [['today', '/'], ['leads', '/leads'], ['lead-felspar', '/leads/4230940100']] as const) {
      await page.goto(`${base}${path}`);
      await page.waitForLoadState('networkidle');
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
      if (overflow) { console.log(`OVERFLOW ${shot} ${name}`); failures++; }
      // Nothing may be cut off or overlap: no element wider than the viewport, and no tile text clipped inside its box.
      const clipped = await page.evaluate(() => [...document.querySelectorAll('[data-recipe-tile] span, [data-signal-item] p, [data-stat] p, article h3, article p')]
        .filter((e) => { const s = getComputedStyle(e); return s.textOverflow !== 'ellipsis' && !s.whiteSpace.includes('nowrap') ? false : e.scrollWidth > e.clientWidth + 1 && s.textOverflow !== 'ellipsis'; })
        .map((e) => e.textContent?.trim().slice(0, 40)));
      if (clipped.length) { console.log(`CLIPPED ${shot} ${name}:`, clipped); failures++; }
      await page.screenshot({ path: `${out}/${shot}-${w}.png`, fullPage: true });
      console.log(`${shot}-${w}.png`);
    }
    if (errors.length) { console.log(`${name} page errors:`, errors); failures++; }
    await ctx.close();
  }
} finally {
  await browser.close();
  await cleanup();
  void psql;
}
console.log(`lead used: ${apn}`);
process.exit(failures ? 1 : 0);
