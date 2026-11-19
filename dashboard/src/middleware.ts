import { defineMiddleware } from 'astro:middleware';
import { createProvider, providerName } from './lib/data';
import { takeFlash } from './lib/flash';
import { serverClient } from './lib/supabase';
import { loadClientConfig } from './lib/config';
import { TERRITORY_COOKIE } from './lib/territory';

/** Reachable without a session. Everything else redirects to /login. */
const isPublic = (p: string) => p === '/login' || p.startsWith('/auth/') || p.startsWith('/share/') || p.startsWith('/_astro/') || p === '/favicon.ico';

const unavailable = (what: string, e: { name?: string; message?: string; code?: string; status?: number }) => {
  console.error(`[middleware] ${what} failed:`, e.name, e.status, e.code, e.message);
  return new Response('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Try again</title><body style="font-family:system-ui;max-width:28rem;margin:4rem auto;padding:0 1rem"><h1>One moment</h1><p>The dashboard could not reach its database just now. You are still signed in. <a href="">Reload</a> in a few seconds.</p>', { status: 503, headers: { 'content-type': 'text/html; charset=utf-8', 'retry-after': '3', 'cache-control': 'no-store' } });
};

export const onRequest = defineMiddleware(async ({ url, request, cookies, locals, redirect }, next) => {
  locals.sample = { used: false };
  // Taken here (before any HTML streams) so the cookie can be cleared. Only page navigations consume it.
  locals.flash = request.method === 'GET' && !url.pathname.startsWith('/api/') ? takeFlash(cookies) : null;
  const mark = () => { locals.sample.used = true; };
  const cookieHood = cookies.get(TERRITORY_COOKIE)?.value ?? '';
  locals.territory = loadClientConfig().territory.neighborhoods.includes(cookieHood) ? cookieHood : null;

  // Fixtures mode: a local demo with no database and no login.
  if (providerName() === 'fixtures') {
    locals.supabase = null; locals.user = { email: 'demo@example.com' }; locals.data = createProvider(null, mark, locals.territory);
    return next();
  }

  const supabase = serverClient(request, cookies);
  locals.supabase = supabase;
  const { data: { user }, error: userError } = await supabase.auth.getUser();
  // A transient failure (auth service unreachable or erroring) must not look like "signed out": answer 503 and let the
  // browser retry, instead of redirecting to /login.
  if (userError && (userError.name === 'AuthRetryableFetchError' || (userError.status ?? 0) >= 500)) return unavailable('getUser', userError);
  let member = false;
  if (user) {
    // Defense in depth: the database gate stops new accounts, this stops a removed member with an old session.
    const res = await supabase.rpc('is_team_member');
    // Only a definite "no" signs the user out. A database error (timeout, restart) is not an answer.
    if (res.error) return unavailable('is_team_member', res.error);
    member = res.data === true;
    if (!member) await supabase.auth.signOut();
  }
  locals.user = user && member ? { email: user.email ?? '' } : null;
  locals.data = createProvider(supabase, mark, locals.territory);

  if (!locals.user && !isPublic(url.pathname)) return redirect(user && !member ? '/login?error=not-team' : '/login');
  return next();
});
