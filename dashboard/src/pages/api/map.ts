import type { APIRoute } from 'astro';
import { filtersFrom } from '../../lib/filters';
import { providerName } from '../../lib/data';
import { tierOf } from '../../lib/ring';
export const prerender = false;

const headers = { 'content-type': 'application/geo+json', 'cache-control': 'private, max-age=60' };

/**
 * GeoJSON for every scored parcel that matches the filters. Filtering and the GeoJSON itself are built in SQL
 * (map_geojson); with the database provider the Worker streams that response straight through without parsing it
 * (26k features would blow the Workers CPU limit if built in JavaScript). The score tier (lib/ring.ts) is added in the browser for the database path; cluster colors follow the highest score inside each cluster.
 * Lens values (equity, upzoning, STR) come from /api/map-lens, not from this payload.
 */
export const GET: APIRoute = async ({ url, locals }) => {
  const f = filtersFrom(url.searchParams);
  // The territory switcher wins over any neighborhood filter; by default only parcels scoring 30+ are mapped.
  if (locals.territory) f.neighborhood = locals.territory;
  if (url.searchParams.get('all') !== '1' && f.minScore == null) f.minScore = 30;
  if (providerName() === 'fixtures' || !locals.supabase) {
    const { points, is_sample } = await locals.data.getMapData(f);
    return new Response(JSON.stringify({
      type: 'FeatureCollection', sample: is_sample,
      features: points.map((p) => ({ type: 'Feature', properties: { apn: p.apn, score: p.score, tier: tierOf(p.score), primary_recipe: p.recipe, neighborhood: p.neighborhood }, geometry: { type: 'Point', coordinates: [p.lng, p.lat] } })),
    }), { headers });
  }
  // The session was verified by the middleware (getUser); this only reads the access token from the cookie.
  const { data: { session } } = await locals.supabase.auth.getSession();
  if (!session) return new Response('Not signed in', { status: 401 });
  const args = {
    p_recipe: f.recipe ?? null, p_group: f.signalGroup ?? null, p_hood: f.neighborhood ?? null,
    p_min: f.minScore ?? null, p_max: f.maxScore ?? null,
  };
  const res = await fetch(`${import.meta.env.PUBLIC_SUPABASE_URL}/rest/v1/rpc/map_geojson`, {
    method: 'POST',
    headers: { apikey: import.meta.env.PUBLIC_SUPABASE_ANON_KEY, authorization: `Bearer ${session.access_token}`, 'content-type': 'application/json' },
    body: JSON.stringify(args),
  });
  if (!res.ok) {
    console.error('[api/map] map_geojson failed:', res.status, (await res.text()).slice(0, 300));
    return new Response('Map data is temporarily unavailable', { status: 503 });
  }
  return new Response(res.body, { headers });
};
