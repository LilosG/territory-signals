/** The score ring as an SVG string, so Astro components and browser scripts (map drawer, search) draw the same thing. */
export const RING_SIZES = { xs: 28, sm: 36, md: 44, lg: 64, xl: 80 } as const;
export type RingSize = keyof typeof RING_SIZES;

/**
 * The four score tiers (Phase 5J), highest first. One definition feeds the ring, the map, the legend and the range filter.
 * Cut-offs are display-only: the stored score and scoring model are untouched.
 */
export type Tier = 'immediate' | 'priority' | 'watchlist' | 'monitor';
export const TIERS: { key: Tier; label: string; min: number; color: string }[] = [
  { key: 'immediate', label: 'Immediate', min: 80, color: '#B91C1C' },
  { key: 'priority', label: 'Priority', min: 65, color: '#B45309' },
  { key: 'watchlist', label: 'Active Watchlist', min: 45, color: '#1E3A8A' },
  { key: 'monitor', label: 'Monitor', min: 0, color: '#64748B' },
];
export const tierOf = (score: number): Tier => (TIERS.find((t) => score >= t.min) ?? TIERS[TIERS.length - 1]!).key;
export const tierLabel = (score: number): string => TIERS.find((t) => t.key === tierOf(score))!.label;
export const tierColor = (score: number): string => `var(--color-tier-${tierOf(score)})`;
/** "80–100", "65–79", "45–64", "0–44" */
export const tierRange = (i: number): { lo: number; hi: number; text: string } => {
  const lo = TIERS[i]!.min; const hi = i === 0 ? 100 : TIERS[i - 1]!.min - 1;
  return { lo, hi, text: `${lo}–${hi}` };
};

export function ringSvg(score: number, size: RingSize = 'md', label?: string): string {
  const px = RING_SIZES[size];
  const stroke = Math.max(3, Math.round(px / 11));
  const r = (px - stroke) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, score)) / 100;
  const font = Math.round(px * (px >= 64 ? 0.34 : 0.36));
  return `<svg width="${px}" height="${px}" viewBox="0 0 ${px} ${px}" role="img" aria-label="${label ?? `Score ${score} out of 100, ${tierLabel(score)}`}" data-tier="${tierOf(score)}" class="shrink-0">`
    + `<circle cx="${px / 2}" cy="${px / 2}" r="${r}" fill="none" stroke="var(--color-line)" stroke-width="${stroke}"/>`
    + `<circle cx="${px / 2}" cy="${px / 2}" r="${r}" fill="none" stroke="${tierColor(score)}" stroke-width="${stroke}" stroke-linecap="round" stroke-dasharray="${(c * pct).toFixed(2)} ${c.toFixed(2)}" transform="rotate(-90 ${px / 2} ${px / 2})"/>`
    + `<text x="50%" y="50%" text-anchor="middle" dominant-baseline="central" font-size="${font}" font-weight="600" fill="var(--color-ink)" style="font-variant-numeric:tabular-nums">${score}</text></svg>`;
}
