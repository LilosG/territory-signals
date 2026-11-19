import type { APIRoute } from 'astro';
export const prerender = false;

/**
 * Magic-link landing. The email link carries a token_hash (verified with verifyOtp, works in any browser).
 * A PKCE `code` is still accepted. Any failure redirects to /login with a friendly message and is logged to the
 * Worker logs; this route never returns a 500.
 */
export const GET: APIRoute = async ({ url, locals, redirect }) => {
  const db = locals.supabase;
  if (!db) return redirect('/');
  const code = url.searchParams.get('code');
  const tokenHash = url.searchParams.get('token_hash');
  const type = url.searchParams.get('type') === 'magiclink' ? 'magiclink' : 'email';
  try {
    if (code) {
      const { error } = await db.auth.exchangeCodeForSession(code);
      if (error) { console.error('[auth/callback] exchangeCodeForSession failed:', error.name, error.status, error.code, error.message); return redirect('/login?error=link'); }
      return redirect('/');
    }
    if (tokenHash) {
      const { error } = await db.auth.verifyOtp({ token_hash: tokenHash, type });
      if (error) { console.error('[auth/callback] verifyOtp failed:', error.name, error.status, error.code, error.message); return redirect('/login?error=link'); }
      return redirect('/');
    }
    console.error('[auth/callback] called with no code or token_hash');
    return redirect('/login?error=link');
  } catch (e) {
    console.error('[auth/callback] unexpected error:', e instanceof Error ? `${e.name}: ${e.message}\n${e.stack}` : String(e));
    return redirect('/login?error=link');
  }
};
