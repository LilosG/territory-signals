/// <reference types="astro/client" />
import type { SupabaseClient } from '@supabase/supabase-js';
import type { DataProvider } from './lib/data/provider';

declare global {
  namespace App {
    interface Locals {
      supabase: SupabaseClient | null;
      user: { email: string } | null;
      data: DataProvider;
      /** Set by the data providers when anything shown on the page is sample data. Read by AppShell for the banner. */
      sample: { used: boolean };
      /** One-time message from the previous action (read from a short-lived cookie by the middleware). */
      flash: { kind: 'ok' | 'error'; text: string } | null;
    }
  }
}
declare global {
interface ImportMetaEnv {
  readonly PUBLIC_SUPABASE_URL: string;
  readonly PUBLIC_SUPABASE_ANON_KEY: string;
  readonly DATA_PROVIDER?: 'supabase' | 'fixtures';
  readonly CLIENT_ID?: string;
}
interface ImportMeta { readonly env: ImportMetaEnv }
}
