/**
 * Satellite parcel preview renderer (Phase 7). One implementation feeds the server-rendered ParcelAerial component
 * (lead brief hero) and the client-rendered slide-over dossier (drawer), so both show the same thing:
 *   - free Esri World Imagery raster tiles, with a crisp gold/crimson parcel boundary overlay,
 *   - a graceful architectural SVG lot-footprint diagram when the parcel has no geometry.
 * No paid API, no geocoding, no AI: tiles and geometry only.
 */
import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { MultiPolygon, Point } from 'geojson';

export interface AerialData {
  apn: string;
  address?: string | null;
  neighborhood?: string | null;
  lot_sqft?: number | null;
  zoning?: string | null;
  score?: number | null;
  centroid?: Point | null;
  geom?: MultiPolygon | null;
}

const GOLD = '#D4A017';
const CRIMSON = '#DC2626';
const INK = '#0F172A';
const MUTED = '#475569';
const LINE = '#CBD5E1';

const esc = (s: unknown) =>
  String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));

const boundaryColor = (data: AerialData) => ((data.score ?? 0) >= 80 ? CRIMSON : GOLD);

/** Every ring in a MultiPolygon (outer and holes), flattened. */
function rings(geom: MultiPolygon | null | undefined): number[][][] {
  if (!geom || !Array.isArray(geom.coordinates)) return [];
  return geom.coordinates.flatMap((poly) => poly.filter((ring) => Array.isArray(ring) && ring.length > 2));
}

function centerOf(data: AerialData): [number, number] | null {
  const c = data.centroid?.coordinates;
  if (Array.isArray(c) && typeof c[0] === 'number' && typeof c[1] === 'number') return [c[0], c[1]];
  const all = rings(data.geom).flat();
  if (!all.length) return null;
  const sum = all.reduce<[number, number]>((a, p) => [a[0] + (p[0] ?? 0), a[1] + (p[1] ?? 0)], [0, 0]);
  return [sum[0] / all.length, sum[1] / all.length];
}

function boundsOf(geom: MultiPolygon | null | undefined): maplibregl.LngLatBounds | null {
  const all = rings(geom).flat();
  if (!all.length) return null;
  const b = new maplibregl.LngLatBounds();
  for (const p of all) b.extend([p[0]!, p[1]!]);
  return b;
}

/** Approximate the footprint from the lot area when only a centroid exists: no survey is implied. */
function approximatePolygon(center: [number, number], lotSqft: number | null | undefined): MultiPolygon {
  const sqft = Math.max(2000, Number(lotSqft) || 6000);
  const ratio = 1.45;
  const widthFt = Math.sqrt(sqft * ratio);
  const depthFt = sqft / widthFt;
  const metersFt = 0.3048;
  const halfLng = (widthFt * metersFt) / 2 / (111320 * Math.cos((center[1] * Math.PI) / 180));
  const halfLat = (depthFt * metersFt) / 2 / 110540;
  const [lng, lat] = center;
  return {
    type: 'MultiPolygon',
    coordinates: [[[
      [lng - halfLng, lat - halfLat], [lng + halfLng, lat - halfLat],
      [lng + halfLng, lat + halfLat], [lng - halfLng, lat + halfLat], [lng - halfLng, lat - halfLat],
    ]]],
  };
}

/** Architectural lot-footprint diagram (SVG) used when no map center/geometry is available. */
export function lotFootprintSvg(data: AerialData): string {
  const sqft = Math.max(1200, Number(data.lot_sqft) || 6000);
  const ratio = 1.45;
  const wFt = Math.sqrt(sqft * ratio);
  const dFt = sqft / wFt;
  const lotW = 380;
  const lotH = Math.max(150, Math.min(240, (lotW * dFt) / wFt));
  const x = (640 - lotW) / 2;
  const y = (360 - lotH) / 2;
  const color = boundaryColor(data);
  const houseW = lotW * 0.42;
  const houseH = lotH * 0.34;
  const hx = x + lotW * 0.18;
  const hy = y + lotH * 0.28;
  const setback = 14;
  return `<svg viewBox="0 0 640 360" role="img" aria-label="Architectural lot-footprint diagram for ${esc(data.address ?? data.apn)}. ${esc(data.lot_sqft ? `${Math.round(sqft).toLocaleString('en-US')} square feet` : 'Lot size not recorded')}${data.zoning ? `, zoning ${esc(data.zoning)}` : ''}.">
    <defs>
      <pattern id="aerial-grid" width="18" height="18" patternUnits="userSpaceOnUse">
        <path d="M18 0H0V18" fill="none" stroke="#E2E8F0" stroke-width="1"/>
      </pattern>
      <linearGradient id="aerial-paper" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#FCFDFE"/><stop offset="1" stop-color="#F1F5F9"/>
      </linearGradient>
    </defs>
    <rect width="640" height="360" fill="url(#aerial-paper)"/>
    <rect width="640" height="360" fill="url(#aerial-grid)" opacity="0.75"/>
    <g font-family="Inter, ui-sans-serif, system-ui" font-variant-numeric="tabular-nums">
      <!-- lot boundary -->
      <rect x="${x}" y="${y}" width="${lotW}" height="${lotH}" fill="rgb(212 160 23 / 0.10)" stroke="${color}" stroke-width="2.5"/>
      <!-- setback line -->
      <rect x="${x + setback}" y="${y + setback}" width="${lotW - setback * 2}" height="${lotH - setback * 2}" fill="none" stroke="${LINE}" stroke-width="1" stroke-dasharray="4 4"/>
      <!-- house footprint -->
      <rect x="${hx}" y="${hy}" width="${houseW}" height="${houseH}" fill="#FFFFFF" stroke="${INK}" stroke-width="2"/>
      <rect x="${hx + 8}" y="${hy + 8}" width="${houseW - 16}" height="${houseH - 16}" fill="none" stroke="${LINE}" stroke-width="1"/>
      <path d="M${hx + 12} ${hy + houseH} v18 h${Math.min(56, houseW * 0.3)} v-18" fill="none" stroke="${INK}" stroke-width="1.5"/>
      <text x="${hx + houseW / 2}" y="${hy + houseH / 2 + 4}" text-anchor="middle" font-size="11" font-weight="600" fill="${INK}">Residence</text>
      <!-- driveway -->
      <rect x="${hx + 12}" y="${hy + houseH + 18}" width="18" height="${Math.max(10, y + lotH - (hy + houseH + 18))}" fill="#E2E8F0" stroke="${LINE}" stroke-width="0.75"/>
      <!-- dimensions -->
      <g stroke="${MUTED}" stroke-width="1">
        <path d="M${x} ${y - 13} H${x + lotW}" />
        <path d="M${x} ${y - 18} v10 M${x + lotW} ${y - 18} v10" />
        <path d="M${x - 13} ${y} V${y + lotH}" />
        <path d="M${x - 18} ${y} h10 M${x - 18} ${y + lotH} h10" />
      </g>
      <text x="${x + lotW / 2}" y="${y - 20}" text-anchor="middle" font-size="10" font-weight="600" fill="${MUTED}">${Math.round(wFt)} ft</text>
      <text x="${x - 20}" y="${y + lotH / 2}" text-anchor="middle" font-size="10" font-weight="600" fill="${MUTED}" transform="rotate(-90 ${x - 20} ${y + lotH / 2})">${Math.round(dFt)} ft</text>
      <!-- north arrow -->
      <g transform="translate(596 34)">
        <path d="M0 -14 7 8 0 3 -7 8Z" fill="${INK}"/>
        <text x="0" y="22" text-anchor="middle" font-size="9" font-weight="700" fill="${MUTED}">N</text>
      </g>
      <!-- labels -->
      <text x="${x + 4}" y="${y + lotH + 22}" font-size="10" font-weight="600" fill="${MUTED}">${esc(data.lot_sqft ? `${Math.round(sqft).toLocaleString('en-US')} sq ft lot` : 'Lot size not recorded')}${data.zoning ? ` · ${esc(data.zoning)}` : ''}</text>
      <text x="${x + lotW - 4}" y="${y + lotH + 22}" text-anchor="end" font-size="9" fill="${MUTED}">Schematic · not a survey</text>
    </g>
  </svg>`;
}

/** Overlay chips shared by the map and the fallback. */
function chips(data: AerialData, hasMap: boolean): string {
  const lot = data.lot_sqft ? `${Math.round(data.lot_sqft).toLocaleString('en-US')} sq ft` : null;
  return `<div class="pointer-events-none absolute inset-x-0 top-0 z-10 flex items-start justify-between gap-2 p-2.5">
    <div class="flex flex-wrap gap-1.5">
      <span class="aerial-chip">${hasMap ? '<span aria-hidden="true">◉</span> Satellite' : '<span aria-hidden="true">▤</span> Lot footprint'}</span>
      ${data.zoning ? `<span class="aerial-chip">${esc(data.zoning)}</span>` : ''}
      ${lot ? `<span class="aerial-chip">${esc(lot)}</span>` : ''}
    </div>
    <span class="aerial-chip">${hasMap ? 'Esri World Imagery' : 'Schematic'}</span>
  </div>
  <div class="pointer-events-none absolute inset-x-0 bottom-0 z-10 flex items-end justify-between gap-2 p-2.5">
    <span class="aerial-chip"><span aria-hidden="true" style="color:${boundaryColor(data)}">■</span> Parcel boundary</span>
    ${hasMap ? '' : '<span class="aerial-chip">No geometry on file</span>'}
  </div>`;
}

type Cleanup = () => void;
const cleanupByEl = new WeakMap<HTMLElement, Cleanup>();

/** Renders a satellite map (or the SVG fallback) into `el`. Returns a cleanup function. */
export function renderAerial(el: HTMLElement, data: AerialData, options: { interactive?: boolean } = {}): Cleanup {
  cleanupByEl.get(el)?.();
  const center = centerOf(data);
  const geom = data.geom && rings(data.geom).length ? data.geom : center ? approximatePolygon(center, data.lot_sqft) : null;
  const hasMap = !!center && !!geom;

  el.innerHTML = '';
  el.classList.add('aerial-frame');

  if (!hasMap) {
    el.innerHTML = `<div class="aerial-fallback" data-aerial-fallback>${lotFootprintSvg(data)}</div>${chips(data, false)}`;
    const noop = () => { el.innerHTML = ''; };
    cleanupByEl.set(el, noop);
    return noop;
  }

  // Keep the architectural diagram behind the map until the first tiles paint: no blank flash.
  el.innerHTML = `<div class="aerial-fallback" data-aerial-fallback>${lotFootprintSvg(data)}</div>
    <div class="aerial-map" data-aerial-map aria-hidden="true"></div>${chips(data, true)}`;
  const fallback = el.querySelector<HTMLElement>('[data-aerial-fallback]')!;
  const mapEl = el.querySelector<HTMLElement>('[data-aerial-map]')!;
  // MapLibre adds `.maplibregl-map { position: relative }` to its container. Pin the container to the frame
  // inline so the map fills the preview instead of collapsing to height 0.
  mapEl.style.position = 'absolute';
  mapEl.style.inset = '0';
  mapEl.style.width = '100%';
  mapEl.style.height = '100%';

  if (import.meta.env.PROD) maplibregl.setWorkerUrl('/maplibre/maplibre-gl-worker.mjs');

  const b = boundsOf(geom);
  const style: maplibregl.StyleSpecification = {
    version: 8,
    sources: {
      esri: {
        type: 'raster',
        tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
        tileSize: 256,
        maxzoom: 19,
        attribution: 'Imagery © Esri, Maxar, Earthstar Geographics',
      },
    },
    layers: [
      { id: 'background', type: 'background', paint: { 'background-color': '#E2E8F0' } },
      { id: 'imagery', type: 'raster', source: 'esri', paint: { 'raster-opacity': 1, 'raster-fade-duration': 200 } },
    ],
  };

  let map: maplibregl.Map;
  try {
    map = new maplibregl.Map({
      container: mapEl,
      style,
      center: b ? undefined : center,
      zoom: b ? undefined : 17.2,
      bounds: b ?? undefined,
      fitBoundsOptions: { padding: 42, maxZoom: 18.5 },
      attributionControl: { compact: true },
      interactive: options.interactive ?? false,
      cooperativeGestures: true,
    });
  } catch {
    el.innerHTML = `<div class="aerial-fallback" data-aerial-fallback>${lotFootprintSvg(data)}</div>${chips(data, false)}`;
    const noop = () => { el.innerHTML = ''; };
    cleanupByEl.set(el, noop);
    return noop;
  }

  map.on('load', () => {
    map.resize();
    map.addSource('parcel', {
      type: 'geojson',
      data: { type: 'Feature', properties: { apn: data.apn }, geometry: geom as MultiPolygon },
    });
    const color = boundaryColor(data);
    map.addLayer({ id: 'parcel-fill', type: 'fill', source: 'parcel', paint: { 'fill-color': color, 'fill-opacity': 0.14 } });
    map.addLayer({ id: 'parcel-line', type: 'line', source: 'parcel', paint: { 'line-color': color, 'line-width': 2.5, 'line-opacity': 1 } });
    map.addLayer({
      id: 'parcel-halo', type: 'line', source: 'parcel',
      paint: { 'line-color': '#FFFFFF', 'line-width': 5, 'line-opacity': 0.35 },
    });
    // The halo sits beneath the crisp boundary line.
    map.moveLayer('parcel-line');
  });
  map.on('error', () => { /* individual tile failures keep the fallback underneath */ });

  let removed = false;
  // Keep the architectural diagram until imagery is actually painted (idle), not merely styled (load).
  const reveal = () => {
    if (removed) return;
    fallback.hidden = true;
    el.dataset.aerialReady = '1';
  };
  map.once('idle', reveal);
  const revealTimer = window.setTimeout(reveal, 6000);

  const cleanup = () => {
    if (removed) return;
    removed = true;
    window.clearTimeout(revealTimer);
    map.remove();
    el.innerHTML = '';
  };
  cleanupByEl.set(el, cleanup);
  return cleanup;
}

/** Hydrates every server-rendered `<div data-parcel-aerial>` with its embedded JSON payload. */
export function hydrateAerials(root: ParentNode = document): void {
  root.querySelectorAll<HTMLElement>('[data-parcel-aerial]').forEach((el) => {
    const payload = el.querySelector<HTMLScriptElement>('[data-aerial-data]')?.textContent;
    if (!payload) return;
    try {
      const data = JSON.parse(payload) as AerialData;
      const height = Number(el.dataset.aerialHeight ?? 200);
      el.style.height = `${height}px`;
      el.removeAttribute('data-parcel-aerial');
      renderAerial(el, data, { interactive: el.dataset.aerialInteractive === '1' });
    } catch {
      el.innerHTML = `<div class="grid h-full place-items-center text-xs text-ink-muted">Aerial preview unavailable</div>`;
    }
  });
}
