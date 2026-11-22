import type { APIRoute } from 'astro';
import type { Dossier, DossierOutreach, OutreachChannel } from '../../lib/data/types';
import { detailHeadline, estGci, isSensitiveComponent, publicReason } from '../../lib/present';
export const prerender = false;

const CHANNEL_ORDER: OutreachChannel[] = ['mail', 'email', 'call_task'];

/**
 * The slide-over Quick-Dossier payload (Phase 7). One parcel at a time, read through the user's session (RLS applies).
 * Deliberately excludes owner identity, mailing address, sales history and sensitive signals: the drawer is a list
 * surface, so distress and life-event facts stay in the full workspace.
 */
export const GET: APIRoute = async ({ url, locals }) => {
  if (!locals.user) return new Response(JSON.stringify({ error: 'Not signed in' }), { status: 401, headers: { 'content-type': 'application/json' } });
  const apn = (url.searchParams.get('apn') ?? '').trim().slice(0, 40);
  if (!apn) return new Response(JSON.stringify({ error: 'Missing APN' }), { status: 400, headers: { 'content-type': 'application/json' } });
  try {
    const lead = await locals.data.getLead(apn);
    if (!lead) return new Response(JSON.stringify({ error: 'Not found' }), { status: 404, headers: { 'content-type': 'application/json' } });
    const pick = CHANNEL_ORDER.map((ch) => lead.outreach.find((o) => o.channel === ch && o.content)).find(Boolean);
    const draft: DossierOutreach | null = pick
      ? { channel: pick.channel, status: pick.status, content: pick.content, blocked_reason: pick.blocked_reason, uses_sample_data: pick.uses_sample_data }
      : null;
    const geo = lead.parcel.geom as unknown as { type?: string; coordinates?: unknown } | null;
    const centroid = lead.parcel.centroid as unknown as { coordinates?: unknown } | null;
    const payload: Dossier = {
      parcel: {
        ...lead.parcel,
        geom: geo && geo.type === 'MultiPolygon' ? ({ type: 'MultiPolygon', coordinates: geo.coordinates } as Dossier['parcel']['geom']) : null,
        centroid: centroid && Array.isArray(centroid.coordinates) ? ({ type: 'Point', coordinates: centroid.coordinates } as Dossier['parcel']['centroid']) : null,
      },
      score: {
        score: lead.score.score, reason_text: publicReason(lead.score.reason_text), recipe_matches: lead.score.recipe_matches ?? [],
        primary_recipe: lead.score.primary_recipe, model_version: lead.score.model_version, uses_sample_data: lead.score.uses_sample_data,
      },
      score_items: lead.score_items.filter((i) => !isSensitiveComponent(i.key)),
      top_signal: detailHeadline(lead),
      ai_brief: lead.ai_brief
        ? { headline: lead.ai_brief.headline, summary: lead.ai_brief.summary, suggested_angle: lead.ai_brief.suggested_angle, uses_sample: lead.ai_brief.uses_sample, model: lead.ai_brief.model, created_at: lead.ai_brief.created_at }
        : null,
      owner: lead.owner
        ? { is_sample: !!lead.owner.is_sample, est_value: lead.owner.est_value, est_equity: lead.owner.est_equity, absentee: lead.owner.absentee, out_of_state: lead.owner.out_of_state }
        : null,
      years_owned: lead.years_owned,
      gci: lead.owner?.est_value != null && lead.owner.est_value > 0 ? estGci(lead.owner.est_value) : null,
      outreach: draft,
      portfolio: lead.portfolio,
      status: lead.status,
      is_sample: lead.is_sample,
    };
    return new Response(JSON.stringify(payload), { headers: { 'content-type': 'application/json', 'cache-control': 'private, no-store' } });
  } catch (e) {
    console.error('[api/dossier] failed:', (e as Error).message);
    return new Response(JSON.stringify({ error: 'Dossier is temporarily unavailable' }), { status: 503, headers: { 'content-type': 'application/json' } });
  }
};
