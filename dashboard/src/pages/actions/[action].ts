import type { APIRoute } from 'astro';
import { setFlash, safeBack } from '../../lib/flash';
export const prerender = false;

const STAGES = ['contacted', 'conversation', 'appointment', 'listing', 'not_interested', 'bad_data'];

/**
 * The working actions. Each is a plain form POST that calls a SECURITY DEFINER database function (which checks the
 * caller is on the team) and redirects back with a one-time message. Nothing here sends anything.
 */
export const POST: APIRoute = async ({ params, request, locals, cookies, redirect }) => {
  const form = await request.formData();
  const back = safeBack(form.get('back'));
  const db = locals.supabase;
  const str = (k: string) => String(form.get(k) ?? '');
  const fail = (text: string) => { setFlash(cookies, { kind: 'error', text }); return redirect(back, 303); };
  const done = (text: string) => { setFlash(cookies, { kind: 'ok', text }); return redirect(back, 303); };
  if (!db) return fail('Actions need the live database. They are off in fixtures mode.');

  const clean = (m: string) => m.replace(/^Blocked: /, 'Blocked: ');
  switch (params.action) {
    case 'approve': {
      const { error } = await db.rpc('approve_outreach', { p_id: str('id') });
      return error ? fail(clean(error.message)) : done('Draft approved. Nothing is sent: outreach is in preview mode.');
    }
    case 'edit': {
      const { error } = await db.rpc('edit_outreach', { p_id: str('id'), p_content: str('content') });
      return error ? fail(clean(error.message)) : done('Edit saved.');
    }
    case 'stage': {
      const stage = str('stage');
      if (!STAGES.includes(stage)) return fail('Unknown outcome.');
      const { error } = await db.rpc('record_stage', { p_apn: str('apn'), p_stage: stage, p_note: str('note') || null });
      return error ? fail(clean(error.message)) : done('Outcome recorded.');
    }
    case 'share-create': {
      const { error } = await db.rpc('create_share_link', { p_apn: str('apn') });
      return error ? fail(clean(error.message)) : done('Share link created. Copy it from the Share links panel.');
    }
    case 'share-revoke': {
      const { error } = await db.rpc('revoke_share_link', { p_token: str('token') });
      return error ? fail(clean(error.message)) : done('Share link revoked. It no longer opens.');
    }
    default:
      return new Response('Not found', { status: 404 });
  }
};
