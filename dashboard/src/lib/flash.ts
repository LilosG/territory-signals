import type { AstroCookies } from 'astro';

export interface Flash { kind: 'ok' | 'error'; text: string }
const NAME = 'ts_flash';

export function setFlash(cookies: AstroCookies, f: Flash) {
  cookies.set(NAME, encodeURIComponent(JSON.stringify(f)), { path: '/', maxAge: 30, httpOnly: true, sameSite: 'lax' });
}
/** Reads and clears the one-time message. */
export function takeFlash(cookies: AstroCookies): Flash | null {
  const c = cookies.get(NAME);
  if (!c) return null;
  cookies.delete(NAME, { path: '/' });
  try { return JSON.parse(decodeURIComponent(c.value)) as Flash; } catch { return null; }
}
/** Only same-site paths are valid redirect targets. */
export const safeBack = (v: unknown, fallback = '/'): string => (typeof v === 'string' && /^\/(?!\/)[^\s]*$/.test(v) ? v : fallback);
