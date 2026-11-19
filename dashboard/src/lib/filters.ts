import type { LeadFilters, LeadSort, LeadStatus } from './data/types';

const SORTS: LeadSort[] = ['score', 'recent', 'lot', 'address'];
const STATUSES: LeadStatus[] = ['new', 'draft_ready', 'awaiting_approval', 'approved', 'sent'];

/** Lead/map filters from a query string: recipe, group, hood, range ("60-79"), q (address or APN). */
export function filtersFrom(sp: URLSearchParams): LeadFilters {
  const f: LeadFilters = {};
  const recipe = sp.get('recipe'), group = sp.get('group'), hood = sp.get('hood'), q = sp.get('q'), range = sp.get('range');
  if (recipe) f.recipe = recipe;
  if (group) f.signalGroup = group;
  if (hood) f.neighborhood = hood;
  if (q) f.search = q.slice(0, 80);
  const sort = sp.get('sort') as LeadSort | null, status = sp.get('status') as LeadStatus | null;
  if (sort && SORTS.includes(sort)) f.sort = sort;
  if (status && STATUSES.includes(status)) f.status = status;
  if (sp.get('new') === '1') f.isNew = true;
  const min = sp.get('min'), max = sp.get('max');
  if (min && /^\d{1,3}$/.test(min)) f.minScore = Number(min);
  if (max && /^\d{1,3}$/.test(max)) f.maxScore = Number(max);
  const m = range?.match(/^(\d{1,3})-(\d{1,3})$/);
  if (m) { f.minScore = Number(m[1]); f.maxScore = Number(m[2]); }
  return f;
}
