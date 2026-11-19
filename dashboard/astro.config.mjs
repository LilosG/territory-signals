import { defineConfig } from 'astro/config';
import tailwindcss from '@tailwindcss/vite';
import vercel from '@astrojs/vercel';

// Server output: pages render on request (needed for per-user sessions and live data).
export default defineConfig({
  output: 'server',
  adapter: vercel(),
  compressHTML: true,
  devToolbar: { enabled: false },
  // 127.0.0.1:3000 is the local Supabase auth site_url (supabase/config.toml), so magic links land here.
  server: { host: '127.0.0.1', port: 3000 },
  vite: { plugins: [tailwindcss()], optimizeDeps: { exclude: ['maplibre-gl'] } },
});
