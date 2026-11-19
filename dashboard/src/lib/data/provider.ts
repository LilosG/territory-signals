import type {
  Backtest, ClientConfig, Coverage, CoverageSource, LeadDetail, LeadFilters, LeadPage, MapData, Pipeline, SharePage, TodayFeed, Trends,
} from './types';

/** Called by a provider whenever it returns something that is, or is derived from, sample data. Drives the sample banner. */
export type MarkSample = () => void;

/**
 * The single seam between the UI and data. `fixtures` (generated sample bundle) and `supabase`
 * (the user's own session, so RLS applies) implement the same interface.
 */
export interface DataProvider {
  readonly name: 'fixtures' | 'supabase';
  getTodayFeed(): Promise<TodayFeed>;
  getLeads(filters?: LeadFilters, page?: number, pageSize?: number): Promise<LeadPage>;
  getLead(apn: string): Promise<LeadDetail | null>;
  getMapData(filters?: LeadFilters): Promise<MapData>;
  getTrends(area: string): Promise<Trends>;
  getPipeline(): Promise<Pipeline>;
  /** `null` when there is nothing real to show (supabase mode until owner sale history exists, Phase 6). */
  getBacktest(): Promise<Backtest | null>;
  getCoverage(): Promise<Coverage>;
  /** Client config (config/clients/<id>.yaml) joined with the recipe catalog. */
  getConfig(): Promise<ClientConfig>;
  getSources(): Promise<CoverageSource[]>;
}

/** Public share page: property facts only. Works without a session. */
export interface SharePageReader {
  getSharePage(token: string): Promise<SharePage | null>;
}
