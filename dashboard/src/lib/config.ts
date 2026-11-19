/** Reads the client config (config/clients/<CLIENT_ID>.yaml). Server only. The YAML files are bundled at build time (Workers has no filesystem). */
import { parse } from 'yaml';
import { RECIPES } from './data/catalog';
import type { ClientConfig, TeamRole } from './data/types';

interface RawClient {
  client_id: string; display_name: string;
  territory: { planning_areas: string[]; zips: string[]; neighborhoods: string[] };
  owner_data_provider: 'sample' | 'attom';
  team_members?: { name: string; email: string; role: TeamRole; phone?: string }[];
  team_profile: { display_name: string; brokerage?: string; office_address?: string };
  recipes: Record<string, { enabled: boolean }>;
  outreach: { mode: 'preview'; weekly_send_cap_per_agent: number; drafts_per_run: number; cooldown_days: number };
}

const files = import.meta.glob('../../../config/clients/*.yaml', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;

let cached: ClientConfig | null = null;

export function clientId(): string {
  return (import.meta.env.CLIENT_ID as string | undefined) ?? 'kaiser-team';
}

export function loadClientConfig(): ClientConfig {
  if (cached) return cached;
  const entry = Object.entries(files).find(([path]) => path.endsWith(`/${clientId()}.yaml`));
  if (!entry) throw new Error(`No client config for CLIENT_ID "${clientId()}" in config/clients/.`);
  const raw = parse(entry[1]) as RawClient;
  cached = {
    client_id: raw.client_id,
    display_name: raw.display_name,
    territory: raw.territory,
    owner_data_provider: raw.owner_data_provider,
    outreach: raw.outreach,
    team_profile: { display_name: raw.team_profile.display_name, brokerage: raw.team_profile.brokerage ?? '', office_address: raw.team_profile.office_address ?? '' },
    // Names come from the catalog; on/off comes from this client's config file.
    recipes: RECIPES.map((r) => ({ key: r.key, name: r.label, description: r.short_description, enabled: raw.recipes[r.key]?.enabled ?? r.enabled, requires_data: r.requires_data })),
    team_members: (raw.team_members ?? []).map((m) => ({ email: m.email.toLowerCase(), name: m.name, role: m.role, phone: m.phone })),
  };
  return cached;
}
