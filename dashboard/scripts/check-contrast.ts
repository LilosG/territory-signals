/** The lightest score band must reach at least 3:1 against white and the basemap fills (Positron: land, water, parks). */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const css = readFileSync(resolve(import.meta.dirname, '../src/styles/tokens.css'), 'utf8');
const lum = (hex: string) => {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0]! + 0.7152 * c[1]! + 0.0722 * c[2]!;
};
const ratio = (a: string, b: string) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x! + 0.05) / (y! + 0.05); };
const band = (k: string) => css.match(new RegExp(`--color-band-${k}:\\s*(#[0-9a-fA-F]{6})`))![1]!;
const surfaces: Record<string, string> = { white: '#ffffff', land: '#f2efe9', 'darker land': '#e8e6dc', water: '#d3dde2', parks: '#d4e5d0' };
let bad = 0;
for (const [name, bg] of Object.entries(surfaces)) {
  const r = ratio(band('low'), bg);
  console.log(`${r >= 3 ? 'ok  ' : 'FAIL'} band-low ${band('low')} on ${name}: ${r.toFixed(2)}:1`);
  if (r < 3) bad++;
}
process.exit(bad ? 1 : 0);
