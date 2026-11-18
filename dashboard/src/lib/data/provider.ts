import type {
  Backtest, ClientConfig, Coverage, CoverageSource, LeadDetail, LeadFilters, LeadSummary,
  MapPoint, Pipeline, TodayFeed, Trends,
} from './types';

/**
 * The single seam between the UI and data. Phase 4 ships `fixtures`;
 * Phase 5 adds a `supabase` implementation behind this same interface.
 */
export interface DataProvider {
  readonly name: 'fixtures' | 'supabase';
  readonly isSample: boolean;
  getTodayFeed(): Promise<TodayFeed>;
  getLeads(filters?: LeadFilters): Promise<LeadSummary[]>;
  getLead(apn: string): Promise<LeadDetail | null>;
  getMapPoints(filters?: LeadFilters): Promise<MapPoint[]>;
  getTrends(area: string): Promise<Trends>;
  getPipeline(): Promise<Pipeline>;
  getBacktest(): Promise<Backtest>;
  getCoverage(): Promise<Coverage>;
  /** Client config plus per-source status derived from source_runs. */
  getConfig(): Promise<ClientConfig>;
  getSources(): Promise<CoverageSource[]>;
}
