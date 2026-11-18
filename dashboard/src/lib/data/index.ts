import { fixturesProvider } from './fixtures';
import type { DataProvider } from './provider';

export type { DataProvider } from './provider';
export * from './types';
export * from './catalog';

const name = (import.meta.env.PUBLIC_DATA_PROVIDER as string | undefined) ?? 'fixtures';

/** Phase 5 will return a supabase-backed provider when PUBLIC_DATA_PROVIDER=supabase. */
export function getProvider(): DataProvider {
  if (name !== 'fixtures') throw new Error(`Data provider "${name}" is not available until Phase 5.`);
  return fixturesProvider;
}
export const data = getProvider();
