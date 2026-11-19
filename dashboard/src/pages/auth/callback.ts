import type { APIRoute } from 'astro';
export const prerender = false;

/** Magic-link landing. Exchanges the one-time code (PKCE) or token hash for a session cookie. */
export const GET: APIRoute = async ({ url, locals, redirect }) => {
  const db = locals.supabase;
  if (!db) return redirect('/');
  const code = url.searchParams.get('code');
  const tokenHash = url.searchParams.get('token_hash');
  const type = url.searchParams.get('type') === 'magiclink' ? 'magiclink' : 'email';
  let ok = false;
  if (code) ok = !(await db.auth.exchangeCodeForSession(code)).error;
  else if (tokenHash) ok = !(await db.auth.verifyOtp({ token_hash: tokenHash, type })).error;
  return redirect(ok ? '/' : '/login?error=link');
};
