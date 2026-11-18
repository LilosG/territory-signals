import { defineConfig } from 'astro/config';
import tailwindcss from '@tailwindcss/vite';
import vercel from '@astrojs/vercel';

// Server output: pages render on request (needed for per-user sessions and live data).
export default defineConfig({
  output: 'server',
  adapter: vercel(),
  compressHTML: true,
  devToolbar: { enabled: false },
  vite: { plugins: [tailwindcss()], optimizeDeps: { exclude: ['maplibre-gl'] } },
});
