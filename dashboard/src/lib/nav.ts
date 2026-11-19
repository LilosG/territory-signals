/** The sidebar: groups, pages and which live count (from nav_counts) each badge shows. */
import type { NavCounts } from './data/types';

export type NavKey =
  | 'today' | 'leads' | 'outreach' | 'pipeline' | 'map' | 'recipes' | 'off-market' | 'trends' | 'reports'
  | 'performance' | 'data-sources' | 'team' | 'settings' | 'system';
export type IconName =
  | 'today' | 'leads' | 'outreach' | 'pipeline' | 'map' | 'recipes' | 'offmarket' | 'trends' | 'reports'
  | 'performance' | 'sources' | 'team' | 'settings';

export interface NavItem { key: NavKey; href: string; label: string; icon: IconName; count?: (c: NavCounts, recipes: number) => number | null }
export interface NavGroup { label: string; items: NavItem[] }

export const NAV: NavGroup[] = [
  { label: 'Work', items: [
    { key: 'today', href: '/', label: 'Today', icon: 'today' },
    { key: 'leads', href: '/leads', label: 'Leads', icon: 'leads', count: (c) => c.leads },
    { key: 'outreach', href: '/outreach', label: 'Outreach', icon: 'outreach', count: (c) => c.drafts + c.awaiting_approval },
    { key: 'pipeline', href: '/pipeline', label: 'Pipeline', icon: 'pipeline' },
  ] },
  { label: 'Opportunities', items: [
    { key: 'map', href: '/map', label: 'Map', icon: 'map' },
    { key: 'recipes', href: '/recipes', label: 'Recipes', icon: 'recipes', count: (_c, r) => r },
    { key: 'off-market', href: '/off-market', label: 'Off-market', icon: 'offmarket', count: (c) => c.off_market },
  ] },
  { label: 'Market', items: [
    { key: 'trends', href: '/trends', label: 'Trends', icon: 'trends' },
    { key: 'reports', href: '/reports', label: 'Reports', icon: 'reports' },
  ] },
  { label: 'Results', items: [
    { key: 'performance', href: '/performance', label: 'Performance', icon: 'performance' },
  ] },
  { label: 'Admin', items: [
    { key: 'data-sources', href: '/data-sources', label: 'Data sources', icon: 'sources' },
    { key: 'team', href: '/team', label: 'Team', icon: 'team' },
    { key: 'settings', href: '/settings', label: 'Settings', icon: 'settings' },
  ] },
];

/** The five items on the phone's bottom bar; "More" opens the full menu. */
export const MOBILE_TABS: NavKey[] = ['today', 'leads', 'map', 'outreach'];
