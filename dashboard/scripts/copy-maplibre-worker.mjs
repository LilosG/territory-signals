// MapLibre GL 6 starts its web worker from a module file that sits next to maplibre-gl.mjs. After Vite bundles the
// app that file does not exist in the output (the browser got a 404 and the map stayed blank). Copy it into
// public/maplibre/ so it is served as a static asset; LeadMap.astro points MapLibre at it with setWorkerUrl().
import { copyFileSync, mkdirSync } from 'node:fs';
mkdirSync('public/maplibre', { recursive: true });
copyFileSync('node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs', 'public/maplibre/maplibre-gl-worker.mjs');
