import type { APIRoute } from 'astro';
import { setFlash, safeBack } from '../../lib/flash';
import { loadClientConfig } from '../../lib/config';
import { TERRITORY_COOKIE } from '../../lib/territory';
export const prerender = false;

const MAX_BULK = 50;
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

  // Territory switcher: a cookie, so it works without a database and applies to every page.
  if (params.action === 'territory') {
    const hood = str('territory');
    if (hood && loadClientConfig().territory.neighborhoods.includes(hood)) {
      cookies.set(TERRITORY_COOKIE, hood, { path: '/', maxAge: 60 * 60 * 24 * 365, sameSite: 'lax', httpOnly: true });
    } else cookies.delete(TERRITORY_COOKIE, { path: '/' });
    return redirect(back, 303);
  }
  if (!db) return fail('Actions need the live database. They are off in fixtures mode.');

  const clean = (m: string) => m.replace(/^Blocked: /, 'Blocked: ');
  switch (params.action) {
    case 'approve': {
      const { error } = await db.rpc('approve_outreach', { p_id: str('id') });
      return error ? fail(clean(error.message)) : done('Draft approved. Nothing is sent: outreach is in preview mode.');
    }
    case 'approve-bulk': {
      // Each draft goes through the same database check as a single approval, so a blocked draft is skipped and named.
      const ids = [...new Set(form.getAll('id').map(String).filter(Boolean))].slice(0, MAX_BULK);
      if (ids.length === 0) return fail('Select at least one draft.');
      let ok = 0; const skipped: string[] = [];
      for (const id of ids) {
        const { error } = await db.rpc('approve_outreach', { p_id: id });
        if (error) skipped.push(clean(error.message)); else ok++;
      }
      if (ok === 0) return fail(`Nothing approved. ${[...new Set(skipped)].slice(0, 2).join(' ')}`);
      return done(`${ok} ${ok === 1 ? 'draft' : 'drafts'} approved${skipped.length ? `, ${skipped.length} skipped (${[...new Set(skipped)].slice(0, 2).join('; ')})` : ''}. Nothing is sent: outreach is in preview mode.`);
    }
    case 'share-bulk': {
      const apns = [...new Set(form.getAll('apn').map(String).filter(Boolean))].slice(0, MAX_BULK);
      if (apns.length === 0) return fail('Select at least one property.');
      let ok = 0, failed = 0;
      for (const apn of apns) {
        const { error } = await db.rpc('create_share_link', { p_apn: apn });
        if (error) failed++; else ok++;
      }
      if (ok === 0) return fail('No share links could be created.');
      return done(`${ok} share ${ok === 1 ? 'link' : 'links'} created${failed ? `, ${failed} failed` : ''}. Copy them from the share links list.`);
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
