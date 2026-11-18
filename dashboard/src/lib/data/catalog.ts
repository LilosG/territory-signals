/** Static labels for signal types, groups, sources and recipes. Display only. */
export const SIGNAL_TYPES: Record<string, { label: string; group: string; phase: 2 | 6 }> = {
  stro_license_active: { label: 'Short-term rental license', group: 'short_term_rental', phase: 2 },
  stro_license_lapsed: { label: 'Short-term rental license lost', group: 'short_term_rental', phase: 2 },
  permit_demolition: { label: 'Demolition permit', group: 'permits', phase: 2 },
  permit_new_construction: { label: 'New construction permit', group: 'permits', phase: 2 },
  permit_addition_remodel: { label: 'Addition / remodel permit', group: 'permits', phase: 2 },
  permit_adu: { label: 'ADU permit', group: 'permits', phase: 2 },
  tax_default: { label: 'Tax-defaulted (power to sell)', group: 'tax_distress', phase: 2 },
  upzoning_sb9: { label: 'SB 9 lot-split eligibility', group: 'upzoning', phase: 2 },
  upzoning_sb79: { label: 'SB 79 transit eligibility', group: 'upzoning', phase: 2 },
  fire_hazard_zone: { label: 'Fire hazard zone', group: 'risk', phase: 2 },
  recorded_document: { label: 'Recent recorded document', group: 'ownership', phase: 2 },
  long_tenure: { label: 'Long tenure', group: 'ownership', phase: 6 },
  absentee_owner: { label: 'Absentee owner', group: 'ownership', phase: 6 },
  high_equity: { label: 'High equity', group: 'ownership', phase: 6 },
  inheritance_transfer: { label: 'Inheritance transfer', group: 'life_event', phase: 6 },
  trust_transfer: { label: 'Trust transfer', group: 'life_event', phase: 6 },
  notice_of_default: { label: 'Notice of default', group: 'distress', phase: 6 },
};

export const SIGNAL_GROUPS: Record<string, string> = {
  permits: 'Permits',
  short_term_rental: 'Short-term rentals',
  tax_distress: 'Tax distress',
  upzoning: 'Upzoning',
  risk: 'Risk',
  ownership: 'Ownership',
  life_event: 'Life events',
  distress: 'Distress',
};

export const SOURCES: Record<string, { label: string; url: string; is_sample?: boolean }> = {
  stro_licenses: { label: 'City STRO licenses', url: 'https://data.sandiego.gov/datasets/stro-licenses/' },
  dsd_permits: { label: 'City development permits', url: 'https://data.sandiego.gov/datasets/development-permits/' },
  treasurer_tax_defaults: { label: 'County tax-default list', url: 'https://www.sdttc.com/content/ttc/en/tax-collection/property-tax-sales/legal-ads.html' },
  sangis_parcels: { label: 'SanGIS parcels', url: 'https://geo.sandag.org/server/rest/directories/downloads/Parcels.csv' },
  sandag_zoning: { label: 'SANDAG base zoning', url: 'https://geo.sandag.org/server/rest/directories/downloads/Zoning_Base_SD.geojson' },
  sandag_transit: { label: 'SANDAG transit stops', url: 'https://geo.sandag.org/server/rest/directories/downloads/Transit_Stops_GTFS.geojson' },
  sandag_planning_areas: { label: 'Community planning areas', url: 'https://geo.sandag.org/server/rest/directories/downloads/Community_Plan_SD.geojson' },
  attom_recorder: { label: 'ATTOM recorder data', url: 'https://api.developer.attomdata.com/', is_sample: true },
  attom_owner: { label: 'ATTOM owner data', url: 'https://api.developer.attomdata.com/', is_sample: true },
  fire_hazard_zones: { label: 'Fire hazard zones (manual file)', url: 'https://osfm.fire.ca.gov/' },
};

export const OUTCOME_LABELS: Record<string, string> = {
  contacted: 'Contacted',
  conversation: 'Conversation',
  appointment: 'Appointment',
  listing: 'Listing',
  not_interested: 'Not interested',
  bad_data: 'Bad data',
};

export const bandOf = (score: number): 'low' | 'watch' | 'warm' | 'hot' =>
  score >= 80 ? 'hot' : score >= 60 ? 'warm' : score >= 40 ? 'watch' : 'low';
export const BAND_LABEL = { low: 'Low', watch: 'Watch', warm: 'Warm', hot: 'Hot' } as const;
