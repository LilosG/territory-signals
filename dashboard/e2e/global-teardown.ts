import { psql, refreshAggregates, rest, TEST_APN, TEST_APN2, TEST_EMAIL } from './env';

const SQL = `
set session_replication_role = replica;  -- the append-only triggers are skipped for this cleanup only
delete from ai_outputs where input_hash = 'e2e';
delete from ai_task_runs where model = 'e2e-model';
update ai_outputs set client_id = replace(client_id, '-hold', '') where client_id like '%-hold';
update ai_task_runs set client_id = replace(client_id, '-hold', '') where client_id like '%-hold';
delete from stage_events where apn in ('${TEST_APN}', '${TEST_APN2}');
delete from share_links where apn in ('${TEST_APN}', '${TEST_APN2}');
delete from outreach where apn in ('${TEST_APN}', '${TEST_APN2}');
delete from scores where apn in ('${TEST_APN}', '${TEST_APN2}');
delete from signals where apn in ('${TEST_APN}', '${TEST_APN2}');
delete from owners where apn in ('${TEST_APN}', '${TEST_APN2}');
delete from sales_history where apn in ('${TEST_APN}', '${TEST_APN2}');
delete from parcels where apn in ('${TEST_APN}', '${TEST_APN2}');
delete from team_members where email = '${TEST_EMAIL}';
`;

/** Removes the synthetic parcel, its rows, the test team member and the test auth user. */
export async function cleanup() {
  psql(SQL);
  refreshAggregates();
  const users = await rest('/auth/v1/admin/users?per_page=1000');
  for (const u of users.users as { id: string; email: string }[]) if (u.email === TEST_EMAIL) await rest(`/auth/v1/admin/users/${u.id}`, { method: 'DELETE' });
}

export default async function globalTeardown() { await cleanup(); }
