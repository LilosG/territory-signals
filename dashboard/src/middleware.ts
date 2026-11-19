import { defineMiddleware } from 'astro:middleware';
import { createProvider, providerName } from './lib/data';
import { takeFlash } from './lib/flash';
import { serverClient } from './lib/supabase';

/** Reachable without a session. Everything else redirects to /login. */
const isPublic = (p: string) => p === '/login' || p.startsWith('/auth/') || p.startsWith('/share/') || p.startsWith('/_astro/') || p === '/favicon.ico';

export const onRequest = defineMiddleware(async ({ url, request, cookies, locals, redirect }, next) => {
  locals.sample = { used: false };
  // Taken here (before any HTML streams) so the cookie can be cleared. Only page navigations consume it.
  locals.flash = request.method === 'GET' && !url.pathname.startsWith('/api/') ? takeFlash(cookies) : null;
  const mark = () => { locals.sample.used = true; };

  // Fixtures mode: a local demo with no database and no login.
  if (providerName() === 'fixtures') {
    locals.supabase = null; locals.user = { email: 'demo@example.com' }; locals.data = createProvider(null, mark);
    return next();
  }

  const supabase = serverClient(request, cookies);
  locals.supabase = supabase;
  const { data: { user } } = await supabase.auth.getUser();
  let member = false;
  if (user) {
    // Defense in depth: the database gate stops new accounts, this stops a removed member with an old session.
    const res = await supabase.rpc('is_team_member');
    member = res.data === true;
    if (!member) await supabase.auth.signOut();
  }
  locals.user = user && member ? { email: user.email ?? '' } : null;
  locals.data = createProvider(supabase, mark);

  if (!locals.user && !isPublic(url.pathname)) return redirect(user && !member ? '/login?error=not-team' : '/login');
  return next();
});
