import { execSync } from 'node:child_process';
import { resolve } from 'node:path';

/** Local Supabase stack settings, from `supabase status` (or SUPABASE_* env vars). */
export function stack() {
  if (process.env.SUPABASE_SERVICE_KEY && process.env.SUPABASE_URL) {
    return { url: process.env.SUPABASE_URL, service: process.env.SUPABASE_SERVICE_KEY, mail: process.env.MAILPIT_URL ?? 'http://127.0.0.1:54324' };
  }
  const out = execSync('supabase status -o env', { cwd: resolve(import.meta.dirname, '../..'), encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
  const v = Object.fromEntries(out.split('\n').map((l) => l.match(/^([A-Z_]+)="(.*)"$/)).filter((m): m is RegExpMatchArray => !!m).map((m) => [m[1]!, m[2]!]));
  return { url: v.API_URL!, service: v.SERVICE_ROLE_KEY!, mail: v.MAILPIT_URL ?? 'http://127.0.0.1:54324' };
}

export const TEST_EMAIL = 'e2e-test@example.test';
export const TEST_APN = 'E2ETEST001';
export const SECRET_OWNER = 'E2E SECRET OWNER';

export async function rest(path: string, init: RequestInit & { json?: unknown } = {}) {
  const s = stack();
  const res = await fetch(`${s.url}${path}`, {
    ...init,
    headers: { apikey: s.service, authorization: `Bearer ${s.service}`, 'content-type': 'application/json', prefer: 'return=representation', ...(init.headers ?? {}) },
    body: init.json !== undefined ? JSON.stringify(init.json) : init.body,
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`${init.method ?? 'GET'} ${path} -> ${res.status} ${text}`);
  return text ? JSON.parse(text) : null;
}
