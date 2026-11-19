import type { LeadFilters } from './data/types';

/** Lead/map filters from a query string: recipe, group, hood, range ("60-79"), q (address or APN). */
export function filtersFrom(sp: URLSearchParams): LeadFilters {
  const f: LeadFilters = {};
  const recipe = sp.get('recipe'), group = sp.get('group'), hood = sp.get('hood'), q = sp.get('q'), range = sp.get('range');
  if (recipe) f.recipe = recipe;
  if (group) f.signalGroup = group;
  if (hood) f.neighborhood = hood;
  if (q) f.search = q.slice(0, 80);
  const m = range?.match(/^(\d{1,3})-(\d{1,3})$/);
  if (m) { f.minScore = Number(m[1]); f.maxScore = Number(m[2]); }
  return f;
}
