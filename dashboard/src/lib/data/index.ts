import type { DataProvider, MarkSample, SharePageReader } from './provider';
import { supabaseProvider, supabaseShareReader } from './supabase';
import type { SupabaseClient } from '@supabase/supabase-js';

export type { DataProvider, SharePageReader } from './provider';
export * from './types';
export * from './catalog';

/**
 * DATA_PROVIDER selects supabase (default) or fixtures. Fixtures (about 1.1 MB of sample data) exist only in dev and
 * tests: `import.meta.env.PROD` is replaced at build time, so the dynamic imports below are dropped from the Worker bundle.
 */
export const providerName = (): 'supabase' | 'fixtures' =>
  !import.meta.env.PROD && ((import.meta.env.DATA_PROVIDER as string | undefined) ?? 'supabase') === 'fixtures' ? 'fixtures' : 'supabase';

export async function createProvider(db: SupabaseClient | null, mark: MarkSample, territory: string | null = null): Promise<DataProvider> {
  // The PROD test is written inline so the bundler can drop the whole branch (and the fixtures chunk) from production builds.
  if (!import.meta.env.PROD && providerName() === 'fixtures') return (await import('./fixtures')).fixturesProvider(mark, territory);
  if (!db) throw new Error('The supabase provider needs a signed-in session client.');
  return supabaseProvider(db, mark, territory);
}

export async function createShareReader(anon: SupabaseClient | null): Promise<SharePageReader> {
  if (!import.meta.env.PROD && (providerName() === 'fixtures' || !anon)) return (await import('./fixtures')).fixturesShareReader;
  if (!anon) throw new Error('The share page needs the database.');
  return supabaseShareReader(anon);
}
