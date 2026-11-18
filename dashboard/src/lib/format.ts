const usd0 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
const usdC = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 2 });
const num = new Intl.NumberFormat('en-US');

export const fmtUsd = (n: number | null | undefined) => (n == null ? '—' : usd0.format(n));
export const fmtUsdCompact = (n: number | null | undefined) => (n == null ? '—' : usdC.format(n));
export const fmtNum = (n: number | null | undefined) => (n == null ? '—' : num.format(n));
export const fmtPct = (n: number | null | undefined, digits = 0) => (n == null ? '—' : `${(n * 100).toFixed(digits)}%`);
export const fmtDate = (s: string | null | undefined) =>
  s ? new Date(s.length === 10 ? `${s}T12:00:00Z` : s).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }) : '—';
export const fmtDateTime = (s: string | null | undefined) =>
  s ? new Date(s).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'America/Los_Angeles' }) : '—';
export const fmtMonth = (ym: string) =>
  new Date(`${ym}-01T12:00:00Z`).toLocaleDateString('en-US', { month: 'short', year: '2-digit', timeZone: 'UTC' });
export const fmtApn = (apn: string) => `${apn.slice(0, 3)}-${apn.slice(3, 6)}-${apn.slice(6, 8)}-${apn.slice(8)}`;
/** Reference "now" for fixtures so rendered output is deterministic. */
export const FIXTURE_NOW = new Date('2026-11-18T12:00:00Z');
export const daysSince = (s: string, now: Date = FIXTURE_NOW) => Math.floor((now.getTime() - new Date(s).getTime()) / 86_400_000);
export const cx = (...xs: (string | false | null | undefined)[]) => xs.filter(Boolean).join(' ');
