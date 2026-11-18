/**
 * Saves desktop (1440x900) and mobile (390x844) screenshots of every screen
 * to dashboard/screenshots/ and fails if any page logs a console error.
 * Prereq: `npm run build`. Run: `npm run screenshots`
 */
import { spawn } from 'node:child_process';
import { mkdirSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
const out = resolve(root, 'screenshots');
mkdirSync(out, { recursive: true });
const PORT = 4399;
const base = `http://localhost:${PORT}`;

const fx = JSON.parse(readFileSync(resolve(root, 'src/data/fixtures.json'), 'utf8')) as { scores: { apn: string; score: number }[] };
const top = [...fx.scores].sort((a, b) => b.score - a.score)[0]!.apn;

const pages: [string, string][] = [
  ['today', '/'], ['map', '/map'], ['lead-brief', `/leads/${top}`], ['lead-presentation', `/leads/${top}/presentation`],
  ['trends', '/trends'], ['trends-newsletter', '/trends/newsletter'], ['pipeline', '/pipeline'], ['settings', '/settings'], ['system', '/design-system'],
];
const viewports = { desktop: { width: 1440, height: 900 }, mobile: { width: 390, height: 844 } } as const;

const server = spawn('npx', ['astro', 'dev', '--port', String(PORT)], { cwd: root, stdio: 'ignore' });
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
async function waitUp() {
  for (let i = 0; i < 60; i++) { try { if ((await fetch(base)).ok) return; } catch { /* retry */ } await sleep(500); }
  throw new Error('preview server did not start');
}

let failures = 0;
try {
  await waitUp();
  // The map needs software WebGL; other pages render more reliably in a plain browser.
  const plain = await chromium.launch();
  const gl = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  for (const [vpName, vp] of Object.entries(viewports)) {
    const ctxFor = (b: typeof plain) => b.newContext({ viewport: vp, deviceScaleFactor: 1, isMobile: vpName === 'mobile' });
    const ctxPlain = await ctxFor(plain), ctxGl = await ctxFor(gl);
    for (const [name, path] of pages) {
      const page = await (name === 'map' ? ctxGl : ctxPlain).newPage();
      const errors: string[] = [];
      page.on('console', (m) => { if (m.type() === 'error') errors.push(`console: ${m.text()}`); });
      page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
      page.on('requestfailed', (r) => errors.push(`requestfailed: ${r.url()} ${r.failure()?.errorText}`));
      await page.goto(base + path, { waitUntil: 'networkidle' });
      if (name === 'map') await page.waitForFunction(() => document.querySelector('.maplibregl-canvas') !== null).then(() => sleep(3500));
      else await sleep(700);
      // horizontal overflow check
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      if (overflow > 1) errors.push(`horizontal overflow: ${overflow}px`);
      await page.screenshot({ path: resolve(out, `${name}.${vpName}.png`), fullPage: name !== 'map' });
      if (name === 'map') {
        // interaction check: filter, then open the lead preview drawer
        await page.selectOption('select[name=hood]', 'Mission Beach');
        await sleep(900);
        const n = await page.evaluate(() => document.getElementById('map-count')?.textContent);
        if (!n?.startsWith('30')) errors.push(`filter did not apply: ${n}`);
        await page.selectOption('select[name=hood]', '');
        await sleep(600);
        const first = page.locator('#map-results button').first();
        if (vpName === 'desktop') { await first.click(); await sleep(900);
          if (!(await page.locator('[data-drawer=lead-preview]').isVisible())) errors.push('drawer did not open');
          await page.screenshot({ path: resolve(out, `map-drawer.${vpName}.png`) }); }
      }
      console.log(`${errors.length ? 'FAIL' : 'ok  '} ${vpName} ${path}`);
      for (const e of errors) { console.log(`     ${e}`); failures++; }
      await page.close();
    }
    await ctxPlain.close(); await ctxGl.close();
  }
  await plain.close(); await gl.close();
} finally {
  server.kill();
}
console.log(failures ? `\n${failures} problem(s)` : '\nAll pages clean: no console errors.');
process.exit(failures ? 1 : 0);
