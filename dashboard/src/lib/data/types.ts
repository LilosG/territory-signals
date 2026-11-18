/**
 * Types mirroring supabase/migrations/20261118000000_foundation.sql exactly
 * (field names and nullability). uuid -> string, timestamptz -> ISO string,
 * date -> "YYYY-MM-DD", numeric -> number, geometry -> GeoJSON.
 * Types below the "View models" divider are dashboard-only compositions.
 */
import type { MultiPolygon, Point } from 'geojson';

export type Uuid = string;
export type IsoTimestamp = string;
export type IsoDate = string;

export interface Neighborhood {
  id: Uuid;
  name: string;
  planning_area: string | null;
  geom: MultiPolygon | null;
  is_official: boolean;
  created_at: IsoTimestamp;
}

export interface Parcel {
  apn: string;
  situs_address: string | null;
  zip: string | null;
  planning_area: string | null;
  neighborhood: string | null;
  geom: MultiPolygon | null;
  centroid: Point | null;
  lot_sqft: number | null;
  land_use: string | null;
  zoning: string | null;
  year_built: number | null;
  last_recorded_doc_date: IsoDate | null;
  source_key: string | null;
  created_at: IsoTimestamp;
  updated_at: IsoTimestamp;
}

export type SourceRunStatus = 'running' | 'success' | 'failed';
export interface SourceRun {
  id: Uuid;
  source_key: string;
  started_at: IsoTimestamp;
  finished_at: IsoTimestamp | null;
  status: SourceRunStatus;
  rows_fetched: number | null;
  rows_matched: number | null;
  rows_unmatched: number | null;
  error_message: string | null;
  created_at: IsoTimestamp;
}

export interface RawRecord {
  id: Uuid;
  source_key: string;
  source_record_id: string;
  run_id: Uuid;
  payload: Record<string, unknown>;
  fetched_at: IsoTimestamp;
  created_at: IsoTimestamp;
}

export type MatchMethod = 'apn' | 'spatial' | 'address' | 'name';
export interface Signal {
  id: Uuid;
  apn: string;
  signal_type: string;
  signal_group: string;
  signal_date: IsoDate | null;
  detected_at: IsoTimestamp;
  source_key: string;
  source_record_id: string;
  run_id: Uuid | null;
  confidence: number; // 0..1
  match_method: MatchMethod;
  is_estimate: boolean;
  is_sample: boolean;
  details: Record<string, unknown> | null;
  created_at: IsoTimestamp;
}

export type OwnerProvider = 'attom' | 'sample';
export interface Owner {
  id: Uuid;
  apn: string;
  owner_name: string | null;
  mailing_address: string | null;
  owner_occupied: boolean | null;
  absentee: boolean | null;
  out_of_state: boolean | null;
  last_sale_date: IsoDate | null;
  last_sale_price: number | null;
  mortgage_open: boolean | null;
  est_value: number | null;
  est_equity: number | null;
  provider: OwnerProvider;
  is_sample: boolean;
  as_of: IsoDate;
  created_at: IsoTimestamp;
}

export interface SaleHistory {
  id: Uuid;
  apn: string;
  sale_date: IsoDate | null;
  sale_price: number | null;
  doc_type: string | null;
  provider: string;
  is_sample: boolean;
  created_at: IsoTimestamp;
}

export interface ScoreComponent {
  key: string;
  label: string;
  points: number;
  max: number;
  /** Signal ids (or owner/sales facts) the points were computed from. */
  evidence: string[];
}
export interface ScoreComponents {
  items: ScoreComponent[];
}
export interface Score {
  id: Uuid;
  apn: string;
  score: number; // 0..100
  components: ScoreComponents | null;
  reason_text: string | null;
  recipe_matches: string[] | null;
  model_version: string;
  scored_at: IsoTimestamp;
  created_at: IsoTimestamp;
}

export interface Suppression {
  id: Uuid;
  apn: string;
  reason: string;
  until_date: IsoDate | null;
  created_at: IsoTimestamp;
}

export type OutreachChannel = 'mail' | 'email' | 'call_task';
export type OutreachStatus = 'draft' | 'awaiting_approval' | 'approved' | 'sent' | 'suppressed';
export interface Outreach {
  id: Uuid;
  apn: string;
  channel: OutreachChannel;
  status: OutreachStatus;
  content: string | null;
  /** Facts from the database the draft is allowed to use, with record citations. */
  source_facts: { facts: { text: string; source_key: string; source_record_id: string }[] } | null;
  approved_by: string | null;
  sent_at: IsoTimestamp | null;
  created_at: IsoTimestamp;
}

export type OutcomeStatus =
  | 'contacted' | 'conversation' | 'appointment' | 'listing' | 'not_interested' | 'bad_data';
export interface Outcome {
  id: Uuid;
  apn: string;
  team_member_email: string | null;
  status: OutcomeStatus;
  noted_at: IsoTimestamp;
  note: string | null;
  created_at: IsoTimestamp;
}

export type TeamRole = 'owner' | 'agent' | 'assistant';
export interface TeamMember {
  id: Uuid;
  email: string;
  name: string | null;
  role: TeamRole;
  created_at: IsoTimestamp;
}

/* ───────────── View models (dashboard only, not tables) ───────────── */

export type ScoreBand = 'low' | 'watch' | 'warm' | 'hot';

export interface Recipe {
  key: string;
  name: string;
  description: string;
  enabled: boolean;
}

export interface ClientConfig {
  client_id: string;
  display_name: string;
  territory: { planning_areas: string[]; zips: string[]; neighborhoods: string[] };
  owner_data_provider: OwnerProvider;
  outreach: { mode: 'preview'; weekly_send_cap: number; daily_send_cap: number };
  recipes: Recipe[];
  team_members: Pick<TeamMember, 'email' | 'name' | 'role'>[];
  /** True when recipes/caps are fixture values rather than loaded from YAML. */
  is_sample: boolean;
}

/** Where outreach stands for a lead, from the outreach table. Derived, never typed in by hand. */
export type LeadStatus = 'new' | 'draft_ready' | 'awaiting_approval' | 'approved' | 'sent';

export interface LeadSummary {
  parcel: Parcel;
  score: Score;
  owner: Owner | null;
  signal_count: number;
  top_signal_types: string[];
  latest_signal_date: IsoDate | null;
  status: LeadStatus;
  /** True if any signal feeding this lead is sample data. */
  is_sample: boolean;
}

export interface LeadFilters {
  recipe?: string;
  signalGroup?: string;
  neighborhood?: string;
  minScore?: number;
  maxScore?: number;
  search?: string;
}

export interface LeadDetail extends LeadSummary {
  owners: Owner[];
  sales: SaleHistory[];
  signals: Signal[];
  outreach: Outreach[];
  outcomes: Outcome[];
  years_owned: number | null;
}

export interface MapPoint {
  apn: string;
  lng: number;
  lat: number;
  score: number;
  band: ScoreBand;
  address: string;
  neighborhood: string;
  recipes: string[];
  signalGroups: string[];
  reason_text: string | null;
  owner_name: string | null;
  est_equity: number | null;
  years_owned: number | null;
}

export interface Coverage {
  parcels_monitored: number;
  sources_live: number;
  sources_total: number;
  last_pull: IsoTimestamp | null;
  signals_this_week: number;
  is_sample: boolean;
}

export interface TodayFeed {
  as_of: IsoTimestamp;
  coverage: Coverage;
  top_leads: LeadSummary[];
  new_signals: (Signal & { situs_address: string | null; neighborhood: string | null })[];
  approvals_waiting: (Outreach & { situs_address: string | null })[];
  call_tasks_due: (Outreach & { situs_address: string | null; score: number | null; reason_text: string | null; assigned_agent: string | null })[];
}

export interface TrendPoint { month: string; value: number }
export interface TrendSeries { key: string; label: string; points: TrendPoint[] }
export interface TrendMetric {
  key: 'turnover' | 'permits' | 'str_lost' | 'tax_default' | 'upzoning' | 'recipes';
  title: string;
  unit: string;
  /** Set for grouped-bar metrics: one group per category (neighborhood). Each series point's `month` then holds its category label. */
  categories?: string[];
  series: TrendSeries[]; // permits has one series per signal group
  is_estimate: boolean;
  takeaway: string; // computed deterministically
}
export interface Trends {
  area: string; // neighborhood name or "All"
  months: string[];
  metrics: TrendMetric[];
  is_sample: boolean;
}

export interface FunnelStage { key: 'signals' | 'contacted' | 'conversation' | 'appointment' | 'listing'; label: string; count: number }
export interface FunnelRow { label: string; stages: FunnelStage[] }
export interface Pipeline {
  by_agent: FunnelRow[];
  by_recipe: FunnelRow[];
  overall: FunnelRow;
  is_sample: boolean;
}

export interface Backtest {
  past_sales_considered: number;
  flagged_before_listing: number;
  share_flagged: number; // 0..1, computed
  avg_days_early: number;
  median_days_early: number;
  window: { from: IsoDate; to: IsoDate };
  is_sample: boolean;
  note: string;
}

export interface CoverageSource {
  source_key: string;
  label: string;
  last_run: SourceRun | null;
  status: SourceRunStatus | 'never';
  is_sample: boolean;
}

export interface FixtureBundle {
  generated_for: string; // fixed "today"
  neighborhoods: Neighborhood[];
  parcels: Parcel[];
  source_runs: SourceRun[];
  signals: Signal[];
  owners: Owner[];
  sales_history: SaleHistory[];
  scores: Score[];
  suppressions: Suppression[];
  outreach: Outreach[];
  outcomes: Outcome[];
  team_members: TeamMember[];
  trends: Record<string, { months: string[]; raw: Record<string, Record<string, number[]>> }>;
  backtest: Omit<Backtest, 'share_flagged'>;
  config: ClientConfig;
}
