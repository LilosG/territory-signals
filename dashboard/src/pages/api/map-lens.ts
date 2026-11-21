import type { APIRoute } from 'astro';
import { providerName } from '../../lib/data';
export const prerender = false;

/**
 * Per-parcel values for the map's lenses (Phase 5J): estimated equity, SB 9 / SB 79 screens and active STR licenses.
 * The map_geojson payload carries only apn, score, recipe and neighborhood, and this phase may not change the database,
 * so these are read from the existing tables with the signed-in user's own session (row-level security applies):
 *   owners (latest row per parcel), and live signals of three types (apn only).
 * Compact on purpose: { equity: { apn: [estEquity, estValue] }, upzone: { apn: 9 | 79 | 88 }, str: [apn] }.
 * 88 = both screens. Everything here is an estimate or a license flag; no owner names, hosts or phone numbers are read.
 * Cached in memory for five minutes (the data changes on pipeline runs, not per request).
 */
const headers = { 'content-type': 'application/json', 'cache-control': 'private, max-age=300' };
const PAGE = 1000;                    // PostgREST max_rows
let cache: { at: number; body: string } | null = null;

export const GET: APIRoute = async ({ locals }) => {
  if (providerName() === 'fixtures' || !locals.supabase) return new Response(JSON.stringify({ available: false }), { headers });
  if (cache && Date.now() - cache.at < 300_000) return new Response(cache.body, { headers });
  const { data: { session } } = await locals.supabase.auth.getSession();
  if (!session) return new Response('Not signed in', { status: 401 });
  const base = `${import.meta.env.PUBLIC_SUPABASE_URL}/rest/v1`;
  const h = { apikey: import.meta.env.PUBLIC_SUPABASE_ANON_KEY, authorization: `Bearer ${session.access_token}` };

  /** All rows of a query, a page of 1000 at a time, eight pages in flight, stopping at the first short page. */
  async function all<T>(query: string): Promise<T[]> {
    const out: T[] = [];
    for (let start = 0; ; start += PAGE * 8) {
      const pages = await Promise.all(Array.from({ length: 8 }, async (_, i) => {
        const res = await fetch(`${base}/${query}&limit=${PAGE}&offset=${start + i * PAGE}`, { headers: h });
        if (!res.ok) throw new Error(`${query.split('?')[0]} ${res.status}`);
        return (await res.json()) as T[];
      }));
      for (const p of pages) out.push(...p);
      if (pages.some((p) => p.length < PAGE)) return out;
    }
  }

  try {
    const sig = (type: string) => all<{ apn: string }>(`signals?select=apn&signal_type=eq.${type}&superseded_by=is.null&order=apn.asc,id.asc`);
    const [owners, sb9, sb79, str] = await Promise.all([
      all<{ apn: string; est_equity: number | null; est_value: number | null }>('owners?select=apn,est_equity,est_value&order=apn.asc,as_of.desc,created_at.desc,id.asc'),
      sig('sb9_lot_split_estimate'), sig('sb79_transit_estimate'), sig('stro_license_active'),
    ]);
    const equity: Record<string, [number | null, number | null]> = {};
    for (const o of owners) if (!(o.apn in equity)) equity[o.apn] = [o.est_equity != null ? Number(o.est_equity) : null, o.est_value != null ? Number(o.est_value) : null];
    const upzone: Record<string, number> = {};
    for (const s of sb9) upzone[s.apn] = 9;
    for (const s of sb79) upzone[s.apn] = upzone[s.apn] === 9 ? 88 : 79;
    const body = JSON.stringify({ available: true, equity, upzone, str: [...new Set(str.map((s) => s.apn))] });
    cache = { at: Date.now(), body };
    return new Response(body, { headers });
  } catch (e) {
    console.error('[api/map-lens]', (e as Error).message);
    return new Response('Lens data is temporarily unavailable', { status: 503 });
  }
};
