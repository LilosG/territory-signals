import type { APIRoute } from 'astro';
export const prerender = false;

/** Address or APN search for the Cmd+K dialog. Limited to the selected territory; at most 8 hits. */
export const GET: APIRoute = async ({ url, locals }) => {
  const h = { 'content-type': 'application/json', 'cache-control': 'private, max-age=30' };
  if (!locals.user) return new Response('[]', { status: 401, headers: { 'content-type': 'application/json' } });
  const q = (url.searchParams.get('q') ?? '').trim().slice(0, 80);
  if (q.length < 2) return new Response('[]', { headers: h });
  try {
    return new Response(JSON.stringify(await locals.data.searchLeads(q)), { headers: h });
  } catch (e) {
    console.error('[api/search] failed:', (e as Error).message);
    return new Response('Search is temporarily unavailable', { status: 503 });
  }
};
