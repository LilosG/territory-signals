import type {
  Backtest, ClientConfig, Coverage, LeadDetail, LeadFilters, LeadPage, MapData, NavCounts, OffMarketFilters, OffMarketPage,
  OutreachPage, OutreachTab, Performance, Pipeline, RecipeCard, SearchHit, SharePage, SourceCard, TeamMember, TodayFeed, Trends, WeeklyBriefAi,
} from './types';

/** Called by a provider whenever it returns something that is, or is derived from, sample data. Drives the sample banner. */
export type MarkSample = () => void;

/**
 * The single seam between the UI and data. `fixtures` (generated sample bundle) and `supabase`
 * (the user's own session, so RLS applies) implement the same interface. A provider is created per request for one
 * territory (a neighborhood name, or null for all); every list, count and chart is limited to it.
 */
export interface DataProvider {
  readonly name: 'fixtures' | 'supabase';
  readonly territory: string | null;
  getNavCounts(): Promise<NavCounts>;
  getTodayFeed(): Promise<TodayFeed>;
  getLeads(filters?: LeadFilters, page?: number, pageSize?: number): Promise<LeadPage>;
  getLead(apn: string): Promise<LeadDetail | null>;
  getMapData(filters?: LeadFilters): Promise<MapData>;
  getTrends(area: string): Promise<Trends>;
  getPipeline(): Promise<Pipeline>;
  getPerformance(): Promise<Performance>;
  /** `null` when there is nothing real to show (supabase mode until owner sale history exists, Phase 6). */
  getBacktest(): Promise<Backtest | null>;
  getCoverage(): Promise<Coverage>;
  /** Client config (config/clients/<id>.yaml) joined with the recipe catalog. */
  getConfig(): Promise<ClientConfig>;
  getSources(): Promise<SourceCard[]>;
  getTeam(): Promise<TeamMember[]>;
  getOutreach(tab: OutreachTab, page?: number, pageSize?: number): Promise<OutreachPage>;
  getRecipes(): Promise<RecipeCard[]>;
  getOffMarket(filters?: OffMarketFilters, page?: number, pageSize?: number): Promise<OffMarketPage>;
  searchLeads(q: string): Promise<SearchHit[]>;
  /** Weekly briefings, newest first (empty when the AI layer is off or nothing valid exists). */
  getBriefings(): Promise<WeeklyBriefAi[]>;
}

/** Public share page: property facts only. Works without a session. */
export interface SharePageReader {
  getSharePage(token: string): Promise<SharePage | null>;
}
