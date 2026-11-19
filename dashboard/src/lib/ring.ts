/** The score ring as an SVG string, so Astro components and browser scripts (map drawer, search) draw the same thing. */
export const RING_SIZES = { xs: 28, sm: 36, md: 44, lg: 64, xl: 80 } as const;
export type RingSize = keyof typeof RING_SIZES;

export function ringSvg(score: number, band: string, size: RingSize = 'md', label?: string): string {
  const px = RING_SIZES[size];
  const stroke = Math.max(3, Math.round(px / 11));
  const r = (px - stroke) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, score)) / 100;
  const font = Math.round(px * (px >= 64 ? 0.34 : 0.36));
  return `<svg width="${px}" height="${px}" viewBox="0 0 ${px} ${px}" role="img" aria-label="${label ?? `Score ${score} out of 100`}" class="shrink-0">`
    + `<circle cx="${px / 2}" cy="${px / 2}" r="${r}" fill="none" stroke="var(--color-line)" stroke-width="${stroke}"/>`
    + `<circle cx="${px / 2}" cy="${px / 2}" r="${r}" fill="none" stroke="var(--color-band-${band})" stroke-width="${stroke}" stroke-linecap="round" stroke-dasharray="${(c * pct).toFixed(2)} ${c.toFixed(2)}" transform="rotate(-90 ${px / 2} ${px / 2})"/>`
    + `<text x="50%" y="50%" text-anchor="middle" dominant-baseline="central" font-size="${font}" font-weight="600" fill="var(--color-ink)" style="font-variant-numeric:tabular-nums">${score}</text></svg>`;
}
