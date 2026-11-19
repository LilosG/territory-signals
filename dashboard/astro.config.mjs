import { defineConfig } from 'astro/config';
import tailwindcss from '@tailwindcss/vite';
import cloudflare from '@astrojs/cloudflare';

// Server output: pages render on request (needed for per-user sessions and live data).
export default defineConfig({
  output: 'server',
  adapter: cloudflare({ imageService: 'passthrough' }),
  // No Astro sessions: auth lives in Supabase cookies, so no SESSION KV binding is needed.
  session: false,
  compressHTML: true,
  devToolbar: { enabled: false },
  // 127.0.0.1:3000 is the local Supabase auth site_url (supabase/config.toml), so magic links land here.
  server: { host: '127.0.0.1', port: 3000 },
  // ../config/clients/*.yaml is bundled at build time (Workers has no filesystem), so Vite must be allowed to read it.
  vite: { plugins: [tailwindcss()], optimizeDeps: { exclude: ['maplibre-gl'] }, server: { fs: { allow: ['..'] } } },
});
