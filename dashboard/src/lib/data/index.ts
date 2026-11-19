import { fixturesProvider, fixturesShareReader } from './fixtures';
import type { DataProvider, MarkSample, SharePageReader } from './provider';
import { supabaseProvider, supabaseShareReader } from './supabase';
import type { SupabaseClient } from '@supabase/supabase-js';

export type { DataProvider, SharePageReader } from './provider';
export * from './types';
export * from './catalog';

/** DATA_PROVIDER selects supabase (default) or fixtures. */
export const providerName = (): 'supabase' | 'fixtures' =>
  ((import.meta.env.DATA_PROVIDER as string | undefined) ?? 'supabase') === 'fixtures' ? 'fixtures' : 'supabase';

export function createProvider(db: SupabaseClient | null, mark: MarkSample, territory: string | null = null): DataProvider {
  if (providerName() === 'fixtures') return fixturesProvider(mark, territory);
  if (!db) throw new Error('The supabase provider needs a signed-in session client.');
  return supabaseProvider(db, mark, territory);
}

export function createShareReader(anon: SupabaseClient | null): SharePageReader {
  return providerName() === 'fixtures' || !anon ? fixturesShareReader : supabaseShareReader(anon);
}
