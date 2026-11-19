import type { APIRoute } from 'astro';
import { filtersFrom } from '../../lib/filters';
export const prerender = false;

/** Compact GeoJSON for every scored parcel that matches the filters (filtering happens in SQL). */
export const GET: APIRoute = async ({ url, locals }) => {
  const { points, is_sample } = await locals.data.getMapData(filtersFrom(url.searchParams));
  const body = {
    type: 'FeatureCollection',
    sample: is_sample,
    features: points.map((p) => ({
      type: 'Feature',
      properties: { apn: p.apn, score: p.score, band: p.band, primary_recipe: p.recipe, neighborhood: p.neighborhood },
      geometry: { type: 'Point', coordinates: [p.lng, p.lat] },
    })),
  };
  return new Response(JSON.stringify(body), { headers: { 'content-type': 'application/geo+json', 'cache-control': 'private, max-age=60' } });
};
