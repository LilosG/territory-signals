/** Supabase clients for the server. The session lives in cookies (PKCE flow), so every read runs as the signed-in user. */
import { createServerClient, parseCookieHeader } from '@supabase/ssr';
import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import type { AstroCookies } from 'astro';

const url = () => import.meta.env.PUBLIC_SUPABASE_URL;
const key = () => import.meta.env.PUBLIC_SUPABASE_ANON_KEY;

export const supabaseConfigured = () => !!url() && !!key();

export function serverClient(request: Request, cookies: AstroCookies): SupabaseClient {
  return createServerClient(url(), key(), {
    cookies: {
      getAll: () => parseCookieHeader(request.headers.get('Cookie') ?? '').map((c) => ({ name: c.name, value: c.value ?? '' })),
      setAll: (list) => { for (const { name, value, options } of list) cookies.set(name, value, options); },
    },
  });
}

/** No session: only what the anon role may call (the public share page function). */
export function anonClient(): SupabaseClient {
  return createClient(url(), key(), { auth: { persistSession: false, autoRefreshToken: false } });
}
