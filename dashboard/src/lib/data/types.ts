/**
 * Types mirroring supabase/migrations/20261118000000_foundation.sql exactly
 * (field names and nullability). uuid -> string, timestamptz -> ISO string,
 * date -> "YYYY-MM-DD", numeric -> number, geometry -> GeoJSON.
 * Types below the "View models" divider are dashboard-only compositions.
 */
import type { MultiPolygon, Point } from 'geojson';
import type { Marked } from '../present';

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
export type OwnerDataMode = 'attom' | 'sample' | 'hybrid';
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

export interface Suppression {
  id: Uuid;
  apn: string;
  reason: string;
  until_date: IsoDate | null;
  created_at: IsoTimestamp;
}

/** One element of scores.components, as written by the scorer (territory/scoring_engine.py). */
export interface RawScoreComponent {
  key: string;                 // e.g. "tax_default", "permit_approved:adu", "owner:years_owned"
  kind: 'signal' | 'owner';
  family: string;
  contribution: number;        // points this component added
  raw_weight: number;
  decay_factor?: number;
  is_sample: boolean;
  is_estimate: boolean;
  facts?: Record<string, unknown>;
  signal_id?: string | null;
  source_key?: string;
  source_record_id?: string;
  confidence?: number;
}
/** A component ready to display: label and max points come from the catalog. */
export interface ScoreItem { key: string; label: string; points: number; max: number; is_sample: boolean; is_estimate: boolean }

export interface Score {
  id: Uuid;
  apn: string;
  score: number; // 0..100
  components: RawScoreComponent[] | null;
  reason_text: string | null;
  recipe_matches: string[] | null;
  primary_recipe: string | null;
  model_version: string;
  uses_sample_data: boolean;
  scored_at: IsoTimestamp;
  created_at: IsoTimestamp;
}

export interface SourceFact {
  kind: 'component' | 'parcel_field' | 'owner_field' | string;
  key?: string;                 // component key
  parcel_field?: string;        // e.g. "neighborhood"
  owner_field?: string;
  value?: unknown;
  apn?: string;
  source_key?: string;
  source_record_id?: string;
  is_estimate?: boolean;
  is_sample?: boolean;
}

export type OutreachChannel = 'mail' | 'email' | 'call_task';
export type OutreachStatus = 'draft' | 'awaiting_approval' | 'approved' | 'sent' | 'suppressed';
export interface Outreach {
  id: Uuid;
  apn: string;
  channel: OutreachChannel;
  status: OutreachStatus;
  content: string | null;
  /** The facts the draft text relies on, each with its source record (written by territory/outreach.py). */
  source_facts: SourceFact[] | null;
  approved_by: string | null;
  sent_at: IsoTimestamp | null;
  recipe: string | null;
  assigned_to: string | null;
  blocked_reason: string | null;
  uses_sample_data: boolean;
  original_content: string | null;
  edited_by: string | null;
  edited_at: IsoTimestamp | null;
  created_at: IsoTimestamp;
}

export interface StageEvent {
  id: Uuid;
  apn: string;
  stage: string;
  team_member_email: string | null;
  occurred_at: IsoTimestamp;
  note: string | null;
  source: 'dashboard' | 'system';
}

export type TeamRole = 'owner' | 'agent' | 'assistant';
export interface TeamMember { id: Uuid; email: string; name: string | null; role: TeamRole; created_at: IsoTimestamp }

export interface ShareLink { token: string; apn: string; created_by: string; created_at: IsoTimestamp; revoked_at: IsoTimestamp | null }

/* ───────────── View models (dashboard only, not tables) ───────────── */

export type ScoreBand = 'low' | 'watch' | 'warm' | 'hot';

export interface Recipe { key: string; name: string; description: string; enabled: boolean; requires_data?: string[] }

export interface ClientConfig {
  client_id: string;
  display_name: string;
  territory: { planning_areas: string[]; zips: string[]; neighborhoods: string[] };
  owner_data_provider: OwnerDataMode;
  outreach: { mode: 'preview'; weekly_send_cap_per_agent: number; drafts_per_run: number; cooldown_days: number; approval_required_recipes: string[] };
  team_profile: { display_name: string; brokerage: string; office_address: string };
  recipes: Recipe[];
  team_members: { email: string; name: string | null; role: TeamRole; phone?: string }[];
  ai: { enabled: boolean; monthly_budget_usd: number };
}

/** Where outreach stands for a lead, from the outreach table. Derived, never typed in by hand. */
export type LeadStatus = 'new' | 'draft_ready' | 'awaiting_approval' | 'approved' | 'sent';

export interface TopComponent { key: string; facts: Record<string, unknown> | null; points: number; signal_date: IsoDate | null; is_sample: boolean; is_estimate: boolean }

/** One row of the deterministic territory portfolio clustering (public.parcel_portfolios). */
export interface PortfolioInfo {
  portfolio_key: string;
  entity_type: 'trust' | 'llc_corp' | 'individual_multi' | 'single';
  territory_parcel_count: number;
  total_est_value: number | null;
  total_est_equity: number | null;
  is_sample: boolean;
}

/** AI layer (Phase 5F). Every AI output is stored, validated and cites the records it used. Never sets scores. */
export interface AiClaim { text: string; /** signal ids, `owner:<field>`, `parcel:<apn>` or `score:<id>` */ record_ids: string[] }
export interface LeadBriefAi {
  headline: string; summary: string; claims: AiClaim[]; suggested_angle: string;
  uses_sample: boolean; model: string; created_at: IsoTimestamp;
}
export interface WeeklySection { neighborhood: string; bullets: string[] }
export interface WeeklyBriefAi {
  week_start: IsoDate; title: string; intro: string; sections: WeeklySection[]; newsletter_paragraph: string;
  model: string; created_at: IsoTimestamp;
}
export interface AiTaskRow {
  task: 'permit_intent' | 'lead_brief' | 'weekly_brief'; model: string | null; status: string; skip_reason: string | null;
  last_run_at: IsoTimestamp | null; calls: number; cached: number; invalid: number; rejected: number; tokens: number;
  cost_run: number | null; cost_unknown: boolean; cost_month: number; warnings: string[];
}
export interface AiStatus { tasks: AiTaskRow[]; monthly_budget_usd: number; cost_month: number; warnings: string[] }

export interface LeadSummary {
  parcel: { apn: string; situs_address: string | null; neighborhood: string | null };
  score: { score: number; reason_text: string | null; recipe_matches: string[]; primary_recipe: string | null; model_version: string; scored_at: IsoTimestamp; uses_sample_data: boolean };
  owner: { owner_name: string | null; is_sample: boolean; last_sale_date: IsoDate | null; est_equity: number | null; est_value?: number | null; absentee: boolean | null; out_of_state: boolean | null } | null;
  /** Whole years since the current owner's tenure started (owners.last_sale_date). */
  years_owned: number | null;
  lot_sqft: number | null;
  zoning: string | null;
  /** Most recent selling-relevant event (approved permit outside "other", removed STR license). */
  latest_signal_date: IsoDate | null;
  /** The three largest signal components, for the card headline. */
  top_components: TopComponent[];
  status: LeadStatus;
  /** True if the score or the owner row shown for this lead is sample data. */
  is_sample: boolean;
  /** One-line AI headline (Phase 5F), shown under the address; null when there is no valid brief. */
  ai_headline?: string | null;
}

export type LeadSort = 'score' | 'recent' | 'lot' | 'address';
export interface LeadFilters {
  recipe?: string;
  signalGroup?: string;
  neighborhood?: string;
  minScore?: number;
  maxScore?: number;
  search?: string;
  status?: LeadStatus;
  /** Saved view "New this week": a selling-relevant event dated in the last 7 days. */
  isNew?: boolean;
  sort?: LeadSort;
}
export interface LeadPage { items: LeadSummary[]; total: number; page: number; pageSize: number }

export interface LeadDetail {
  parcel: Parcel;
  score: Score;
  score_items: ScoreItem[];
  owner: Owner | null;
  years_owned: number | null;
  sales: SaleHistory[];
  /** Dated selling events (permits outside "other", STR removals), newest first. Collapsed by the page. */
  signals: Signal[];
  /** Live events on the parcel; `signals` holds the latest 80 of them. */
  signal_total: number;
  /** Tax default and ownership transfer: shown only in the brief's labeled sensitive section. */
  sensitive_signals: Signal[];
  /** Latest snapshot of property traits: upzoning estimates, active STR license, fire zone. */
  trait_signals: Signal[];
  outreach: Outreach[];
  stage_events: StageEvent[];
  share_links: ShareLink[];
  status: LeadStatus;
  is_sample: boolean;
  /** Validated AI summary with its cited records, or null (also null when the AI layer is off). */
  ai_brief: LeadBriefAi | null;
  /** Territory portfolio when the owner holds 2+ territory parcels (internal pages only; never on a share page). */
  portfolio: PortfolioInfo | null;
}

/** One draft the slide-over dossier can show and copy. Content is the drafted text; blocked_reason is internal. */
export interface DossierOutreach {
  channel: OutreachChannel;
  status: OutreachStatus;
  content: string | null;
  blocked_reason: string | null;
  uses_sample_data: boolean;
}

/**
 * The slide-over Quick-Dossier payload (Phase 7). It deliberately carries no owner identity, mailing address or
 * sensitive signal: the drawer is a list surface, so distress and life-event facts stay in the full workspace.
 */
export interface Dossier {
  parcel: Parcel;
  score: Pick<Score, 'score' | 'reason_text' | 'recipe_matches' | 'primary_recipe' | 'model_version' | 'uses_sample_data'>;
  score_items: ScoreItem[];
  top_signal: Marked | null;
  ai_brief: Pick<LeadBriefAi, 'headline' | 'summary' | 'suggested_angle' | 'uses_sample' | 'model' | 'created_at'> | null;
  owner: { is_sample: boolean; est_value: number | null; est_equity: number | null; absentee: boolean | null; out_of_state: boolean | null } | null;
  years_owned: number | null;
  /** Estimated gross commission income (2.5% of estimated value); null when no estimated value exists. */
  gci: number | null;
  outreach: DossierOutreach | null;
  portfolio: PortfolioInfo | null;
  status: LeadStatus;
  is_sample: boolean;
}

/** One bubble in the Trends Opportunity Matrix. Equity and score are the two axes; GCI sizes the bubble. */
export interface MatrixPoint {
  apn: string;
  address: string | null;
  neighborhood: string | null;
  score: number;
  equity: number;
  gci: number;
  lot_sqft: number | null;
  zoning: string | null;
  is_sample: boolean;
  tier: 'immediate' | 'priority' | 'watchlist' | 'monitor';
}

export interface MapPoint { apn: string; score: number; band: ScoreBand; recipe: string | null; neighborhood: string; lng: number; lat: number }
export interface MapData { points: MapPoint[]; is_sample: boolean }

export interface Coverage {
  parcels_monitored: number;
  sources_live: number;
  sources_total: number;
  last_pull: IsoTimestamp | null;
  signals_this_week: number;
  is_sample: boolean;
}

/** What the public /share/[token] page may show: property facts only. */
export interface SharePage {
  neighborhood: string | null;
  lot_sqft: number | null;
  zoning: string | null;
  year_built: number | null;
  /** signal types of the in-house estimates (SB 9, SB 79), always shown as estimated */
  upzoning_estimates: string[];
  agent_name: string | null;
  agent_email: string | null;
  agent_phone: string | null;
}

/** One selling-relevant event, same-day events of one kind on a parcel merged into one with a count. */
export interface SignalEvent {
  apn: string; situs_address: string | null; neighborhood: string | null;
  type: string; group: string; date: IsoDate; count: number;
  is_sample: boolean; is_estimate: boolean; source_key: string; source_record_id: string;
  details: Record<string, unknown> | null;
}

export interface NavCounts { leads: number; drafts: number; awaiting_approval: number; approved: number; call_tasks: number; off_market: number }

export interface StatSeries {
  metric: 'signals' | 'drafts' | 'outcomes' | 'active_leads';
  days: { day: IsoDate; n: number }[];
  this_week: number;
  last_week: number;
  /** Weekly totals, index 0 = this week (last 7 days), 1 = the comparison week, 2.. older. Used to spot the initial data load. */
  weeks?: number[];
  /** The day this metric first had data (first pull of its sources, first draft or outcome). */
  first_day?: IsoDate | null;
  /** Active leads only: the scoring model of this week differs from the comparison week's, so a % change would mean nothing. */
  scoring_updated?: boolean;
}
export interface RecipeWeek {
  key: string; label: string; parcels: number; new_this_week: number;
  /** Why the recipe has no matches yet ("Needs the fire hazard zone file"); null when it has matches. */
  idle_reason?: string | null;
}

/** A row of the outreach queue. */
export interface OutreachItem {
  id: Uuid; apn: string; channel: OutreachChannel; status: OutreachStatus; recipe: string | null;
  content: string | null; blocked_reason: string | null; blocked: string[]; uses_sample_data: boolean;
  situs_address: string | null; neighborhood: string | null; score: number | null; assigned_name: string | null;
  created_at: IsoTimestamp; due_date: IsoDate | null; approved_by: string | null;
}
export type OutreachTab = 'drafts' | 'awaiting_approval' | 'approved' | 'call_tasks';
export interface OutreachPage { tab: OutreachTab; items: OutreachItem[]; total: number; page: number; pageSize: number; counts: NavCounts }

export interface TodayFeed {
  as_of: IsoTimestamp;
  territory: string | null;
  coverage: Coverage;
  stats: StatSeries[];
  leads_total: number;
  top_leads: LeadSummary[];
  recipe_strip: RecipeWeek[];
  approvals: OutreachItem[]; approvals_total: number;
  call_tasks: OutreachItem[]; call_tasks_total: number;
  new_signals: SignalEvent[]; new_signals_total: number;
  /** Latest valid weekly briefing, or null. */
  weekly: WeeklyBriefAi | null;
}

export interface RecipeCard {
  key: string; name: string; description: string; enabled: boolean;
  parcels: number; new_this_week: number; strong: number;
  top: { apn: string; score: number; situs_address: string | null; neighborhood: string | null; top_signal?: Marked | null }[];
  /** Why an enabled or disabled recipe has no matches; null when it has some. */
  idle_reason: string | null;
  is_sample: boolean;
}

export interface OffMarketRow {
  apn: string; situs_address: string | null; neighborhood: string | null; lot_sqft: number | null; zoning: string | null;
  year_built: number | null; land_use: string | null; kinds: string[]; upzoning: string[]; has_share_link: boolean;
  /** The top-contribution signal line (same rule as the lead lists). */
  top_signal?: Marked | null;
  /** Territory portfolio when the owner holds 2+ territory parcels (internal page only). */
  portfolio?: PortfolioInfo | null;
}
export interface ActiveShareLink { token: string; apn: string; situs_address: string | null; neighborhood: string | null; created_by: string; created_at: IsoTimestamp }
export interface OffMarketPage { items: OffMarketRow[]; total: number; page: number; pageSize: number; links: ActiveShareLink[] }
export interface OffMarketFilters { kind?: 'builder_bait' | 'tired_landlord'; sort?: 'lot' | 'score' | 'address' }

export interface SearchHit { apn: string; situs_address: string | null; neighborhood: string | null; score: number }

export interface CoverageWeek { week: IsoDate; signals: number; sources_live: number; parcels_monitored: number }
export interface Performance { by_agent: FunnelRow[]; by_recipe: FunnelRow[]; overall: FunnelRow; has_events: boolean; coverage: CoverageWeek[]; backtest: Backtest | null; is_sample: boolean }

export type SourceState = 'live' | 'running' | 'not_connected' | 'sample' | 'failed';
export interface SourceCard { key: string; label: string; description: string; state: SourceState; last_run: IsoTimestamp | null; rows_fetched: number | null; rows_matched: number | null; note: string | null }

export interface TrendPoint { month: string; value: number }
export interface TrendSeries { key: string; label: string; points: TrendPoint[] }
export interface TrendMetric {
  key: 'turnover' | 'permits' | 'str_lost' | 'tax_default' | 'upzoning' | 'recipes';
  title: string;
  unit: string;
  /** Set for grouped-bar metrics: one group per category (neighborhood). */
  categories?: string[];
  series: TrendSeries[];
  is_estimate: boolean;
  /** True when any row behind this chart is sample data. */
  is_sample: boolean;
  takeaway: string; // computed deterministically
  /** Series hidden by default behind a toggle (the "other" permit group). */
  optional_series?: TrendSeries[];
  optional_label?: string;
  /** Set when the chart would mislead (all rows are sample data, or there is nothing yet): a designed empty state is shown instead. */
  empty_state?: string;
}
export interface Trends {
  area: string; months: string[];
  /** The current, incomplete month ("YYYY-MM"): shown as "(to date)" and left out of period comparisons. */
  partial_month: string;
  metrics: TrendMetric[];
  /** Charts with nothing to show yet, with what unlocks each. */
  coming_soon: { key: TrendMetric['key']; title: string; unlock: string }[];
  is_sample: boolean;
}

export interface FunnelStage { key: 'signal' | 'contacted' | 'conversation' | 'appointment' | 'listing'; label: string; count: number }
export interface FunnelRow { label: string; stages: FunnelStage[] }
export interface RecentOutcome { apn: string; situs_address: string | null; neighborhood: string | null; stage: string; by: string | null; note: string | null; occurred_at: IsoTimestamp }
/** Estimated property value behind one funnel stage: distinct parcels that reached it, and the sum of their owners' est_value. */
export interface StageValue { key: FunnelStage['key']; parcels: number; valued_parcels: number; est_value: number; sample_parcels: number }
/** ATTOM trial-quota status (from api_usage_log); null when the table is not present yet. */
export interface AttomUsage {
  calls_today: number;
  daily_call_cap: number;
  calls_this_month: number;
  last_call_at: IsoTimestamp | null;
}

export interface Pipeline { by_agent: FunnelRow[]; by_recipe: FunnelRow[]; overall: FunnelRow; stage_values: StageValue[]; has_events: boolean; recent: RecentOutcome[]; is_sample: boolean; attom_usage?: AttomUsage | null }

/** A real historical backtest row (backtest_runs). Null until a run exists. */
export interface Backtest {
  past_sales_considered: number;
  flagged_before_listing: number;
  share_flagged: number; // 0..1, computed
  avg_days_early: number;
  median_days_early: number;
  capture_rate_pct?: number;
  breakdown_by_signal_group?: Record<string, number>;
  window: { from: IsoDate; to: IsoDate };
  is_sample: boolean;
  note: string;
  computed_at?: IsoTimestamp;
}

export interface CoverageSource {
  source_key: string;
  label: string;
  last_run: SourceRun | null;
  status: SourceRunStatus | 'never';
}

export interface TurnoverRow { month: string; neighborhood: string; sales: number; sample_rows: number }
export interface SignalMonthRow { month: string; neighborhood: string; signal_type: string; signal_group: string; signals: number; sample_rows: number }
export interface UpzoningRow { neighborhood: string; sb9: number; sb79_quarter_mile: number; sb79_half_mile: number; sample_rows: number }
export interface RecipeRow { neighborhood: string; recipe: string; parcels: number; sample_rows: number }
export interface TrendRows { turnover: TurnoverRow[]; signals: SignalMonthRow[]; upzoning: UpzoningRow[]; recipes: RecipeRow[] }

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
  stage_events: StageEvent[];
  team_members: TeamMember[];
  share_links: ShareLink[];
  /** Pre-aggregated monthly rows shaped like the SQL trend views. */
  trend_rows: TrendRows;
  backtest: Omit<Backtest, 'share_flagged'>;
}
