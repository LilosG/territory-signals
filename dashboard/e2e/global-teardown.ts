import { execFileSync } from 'node:child_process';
import { rest, TEST_APN, TEST_EMAIL } from './env';

const SQL = `
set session_replication_role = replica;  -- the append-only triggers are skipped for this cleanup only
delete from stage_events where apn = '${TEST_APN}';
delete from share_links where apn = '${TEST_APN}';
delete from outreach where apn = '${TEST_APN}';
delete from scores where apn = '${TEST_APN}';
delete from signals where apn = '${TEST_APN}';
delete from owners where apn = '${TEST_APN}';
delete from sales_history where apn = '${TEST_APN}';
delete from parcels where apn = '${TEST_APN}';
delete from team_members where email = '${TEST_EMAIL}';
`;

/** Removes the synthetic parcel, its rows, the test team member and the test auth user. */
export async function cleanup() {
  execFileSync('docker', ['exec', '-i', 'supabase_db_territory-signals', 'psql', '-U', 'supabase_admin', '-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-c', SQL], { stdio: ['ignore', 'ignore', 'inherit'] });
  const users = await rest('/auth/v1/admin/users?per_page=1000');
  for (const u of users.users as { id: string; email: string }[]) if (u.email === TEST_EMAIL) await rest(`/auth/v1/admin/users/${u.id}`, { method: 'DELETE' });
}

export default async function globalTeardown() { await cleanup(); }
