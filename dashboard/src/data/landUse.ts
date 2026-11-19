/**
 * Plain labels for county land-use codes (ASR_LANDUSE). These come from the unit counts in
 * pipelines/territory/sources/reports/land_use_profile.csv and the "Land-use codes are inferred" note in BACKLOG.md:
 * the county dictionary is still unconfirmed, so only the five residential codes that are scored are named.
 * Every other code is shown as "Residential (code N)" rather than guessed.
 */
export const LAND_USE_LABELS: Record<string, string> = {
  '11': 'Single-family home',
  '12': 'Duplex',
  '13': 'Triplex or fourplex',
  '14': 'Small multifamily',
  '17': 'Condominium',
};

/** Label for a land-use code, or null when the parcel has none (so the row is hidden, not shown as a dash). */
export function landUseLabel(code: string | null | undefined): string | null {
  const c = (code ?? '').trim();
  if (!c) return null;
  return LAND_USE_LABELS[c] ?? `Residential (code ${c})`;
}
