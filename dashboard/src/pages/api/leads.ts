import type { APIRoute } from 'astro';
import { filtersFrom } from '../../lib/filters';
export const prerender = false;

/** One page of leads (JSON) for the map's results list and preview. Page size is capped. The provider limits it to the selected territory. */
export const GET: APIRoute = async ({ url, locals }) => {
  const size = Math.min(50, Math.max(1, Number(url.searchParams.get('size') ?? 25) || 25));
  const page = Math.max(1, Number(url.searchParams.get('page') ?? 1) || 1);
  const f = filtersFrom(url.searchParams);
  // The map's results list follows its default: parcels scoring 30+ unless "Show all parcels" is on. Search by APN is never limited.
  if (url.searchParams.get('all') !== '1' && f.minScore == null && !f.search) f.minScore = 30;
  const out = await locals.data.getLeads(f, page, size);
  return new Response(JSON.stringify(out), { headers: { 'content-type': 'application/json', 'cache-control': 'private, max-age=30' } });
};
