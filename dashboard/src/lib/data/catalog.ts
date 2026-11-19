/**
 * Names come from src/data/catalog.generated.json only (python -m territory.export_catalog, built from
 * config/scoring.yaml, signal_labels.yaml, permit_labels.yaml and the client's recipe toggles). Nothing here
 * defines a signal, recipe, component, band or stage. Only the display helpers and the external source
 * links below are written by hand.
 */
import raw from '../../data/catalog.generated.json';

interface CatalogFile {
  model_version: string;
  signal_types: { key: string; label: string }[];
  signal_groups: { key: string; label: string }[];
  permit_types: { key: string; label: string }[];
  recipes: { key: string; label: string; short_description: string; enabled: boolean; requires_data: string[] }[];
  components: { key: string; kind: string; family: string; max_points: number; label: string; family_label: string }[];
  score_bands: { key: string; label: string; min: number }[];
  stages: { key: string; label: string }[];
  owner_modifier_cap: number;
}
const catalog = raw as unknown as CatalogFile;

import type { ScoreBand } from './types';

const map = <T extends { key: string }, V>(xs: T[], f: (x: T) => V): Record<string, V> => Object.fromEntries(xs.map((x) => [x.key, f(x)]));

export const MODEL_VERSION = catalog.model_version;
export const SIGNAL_TYPES = map(catalog.signal_types, (x) => x.label);
export const SIGNAL_GROUPS = map(catalog.signal_groups, (x) => x.label);
export const PERMIT_TYPES = map(catalog.permit_types, (x) => x.label);
export const RECIPES = catalog.recipes;
export const RECIPE_LABELS = map(catalog.recipes, (x) => x.label);
export const COMPONENTS = map(catalog.components, (x) => ({ label: x.label, max: x.max_points, family: x.family, family_label: x.family_label, kind: x.kind }));
export const STAGES = catalog.stages;
export const OUTCOME_LABELS = map(catalog.stages, (x) => x.label);
export const SCORE_BANDS = [...catalog.score_bands].sort((a, b) => b.min - a.min) as { key: ScoreBand; label: string; min: number }[];
export const BAND_LABEL = Object.fromEntries(SCORE_BANDS.map((b) => [b.key, b.label])) as Record<ScoreBand, string>;
export const bandOf = (score: number): ScoreBand => (SCORE_BANDS.find((b) => score >= b.min) ?? SCORE_BANDS.at(-1)!).key;

/** Display label for a signal: permits use the plain-English permit label, transfers their own label. */
export function signalLabel(type: string, details?: Record<string, unknown> | null): string {
  if (type === 'permit_approved' || type === 'permit_stalled') {
    const pt = PERMIT_TYPES[String(details?.approval_type ?? '')];
    const base = SIGNAL_TYPES[type] ?? type;
    return pt ? `${base}: ${pt}` : base;
  }
  return SIGNAL_TYPES[type] ?? type;
}

/** The scoring component for a stored component key (label and the most points it can contribute). */
export const componentInfo = (key: string) => COMPONENTS[key];

/** External source pages for signal citations (display only). Keys are `source_runs.source_key` values. */
export const SOURCES: Record<string, { label: string; url: string }> = {
  stro_licenses: { label: 'City STR licenses', url: 'https://data.sandiego.gov/datasets/stro-licenses/' },
  dev_permits: { label: 'City development permits', url: 'https://data.sandiego.gov/datasets/development-permits/' },
  tax_default: { label: 'County tax-default list', url: 'https://www.sdttc.com/content/ttc/en/tax-collection/property-tax-sales/legal-ads.html' },
  parcels: { label: 'SanGIS parcels', url: 'https://geo.sandag.org/server/rest/directories/downloads/Parcels.csv' },
  zoning: { label: 'SANDAG base zoning', url: 'https://geo.sandag.org/server/rest/directories/downloads/Zoning_Base_SD.geojson' },
  upzoning_estimate: { label: 'In-house upzoning screen', url: 'https://geo.sandag.org/server/rest/directories/downloads/Transit_Stops_GTFS.geojson' },
  planning_areas: { label: 'Community planning areas', url: 'https://geo.sandag.org/server/rest/directories/downloads/Community_Plan_SD.geojson' },
  fire_zones: { label: 'Fire hazard zones (manual file)', url: 'https://osfm.fire.ca.gov/' },
  permit_rederive: { label: 'Permit re-derivation', url: '' },
  sample_sales_history: { label: 'Sample sales history', url: '' },
  sample_owner: { label: 'Sample owner data', url: '' },
};
export const SOURCE_LABEL = (key: string) => SOURCES[key]?.label ?? key;

export const LEAD_STATUS: Record<'new' | 'draft_ready' | 'awaiting_approval' | 'approved' | 'sent', { label: string; tone: 'good' | 'warning' | 'neutral' }> = {
  new: { label: 'New', tone: 'neutral' },
  draft_ready: { label: 'Draft ready', tone: 'good' },
  awaiting_approval: { label: 'Awaiting approval', tone: 'warning' },
  approved: { label: 'Approved', tone: 'good' },
  sent: { label: 'Sent', tone: 'neutral' },
};

/**
 * What the Data sources page shows, in this order, under friendly names. Internal steps (permit re-derivation) and
 * base layers (parcels, zoning, planning areas) are deliberately not listed. `key` is the pipeline's source key.
 */
export const SOURCE_CATALOG: { key: string; label: string; description: string }[] = [
  { key: 'dev_permits', label: 'City development permits', description: 'Approved and expired building, remodel, ADU and demolition permits.' },
  { key: 'stro_licenses', label: 'Short-term rental licenses', description: 'Active City licenses; removals appear from the second weekly snapshot.' },
  { key: 'tax_default', label: 'County tax-default list', description: 'Parcels on the Treasurer-Tax Collector power-to-sell list (updated each June).' },
  { key: 'upzoning_estimate', label: 'Upzoning screen (estimated)', description: 'In-house SB 9 and SB 79 eligibility screen. Not an official determination.' },
  { key: 'fire_zones', label: 'Fire hazard zones', description: 'State fire hazard severity zones, loaded from a downloaded file.' },
  { key: 'owner_data', label: 'Owner and sales records', description: 'Ownership, tenure, equity and sale history.' },
];
/** Pipeline steps that are not data sources a person needs to look at. */
export const INTERNAL_SOURCES = new Set(['permit_rederive', 'parcels', 'zoning', 'planning_areas', 'sample_sales_history', 'sample_owner']);

/** Signal types that make a dated selling event (shown in timelines, feeds and counts). Permits in the "other" group never are. */
export const EVENT_TYPES = ['permit_approved', 'permit_stalled', 'stro_license_removed'] as const;
/** Tax default and ownership transfer: only the lead brief shows these, in a labeled section. */
export const SENSITIVE_TYPES = ['tax_default', 'ownership_transfer'] as const;
/** Property traits (latest snapshot): upzoning estimates, an active STR license, fire zone. */
export const TRAIT_TYPES = ['sb9_lot_split_estimate', 'sb79_transit_estimate', 'stro_license_active', 'fire_hazard_zone'] as const;
/** Recipes that describe an owner in distress. Their tags never appear on lead cards or lists. */
export const SENSITIVE_RECIPES = new Set(['financial_pressure', 'quiet_inheritance']);
