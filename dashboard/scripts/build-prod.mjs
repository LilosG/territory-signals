// Production build with the cloud (public) values from deploy-env/.env baked in.
// The Cloudflare adapter reads dashboard/.env with higher priority than .env.production, so the local .env
// is moved aside for the duration of the build and always restored. Nothing here is a secret
// (PUBLIC_SUPABASE_URL, PUBLIC_SUPABASE_ANON_KEY, DATA_PROVIDER).
import { existsSync, renameSync, copyFileSync, rmSync, readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';

const src = 'deploy-env/.env';
if (!existsSync(src)) { console.error('Missing dashboard/deploy-env/.env (see DEPLOY.md).'); process.exit(1); }
if (readFileSync(src, 'utf8').includes('127.0.0.1')) { console.error('deploy-env/.env points at a local URL; refusing to build for production.'); process.exit(1); }

const hadEnv = existsSync('.env');
const restore = () => { rmSync('.env', { force: true }); if (hadEnv) renameSync('.env.local-backup', '.env'); };
if (hadEnv) renameSync('.env', '.env.local-backup');
process.on('exit', restore);
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => process.exit(130));
copyFileSync(src, '.env');
spawnSync('node', ['scripts/copy-maplibre-worker.mjs'], { stdio: 'inherit' });
const r = spawnSync('npx', ['astro', 'build'], { stdio: 'inherit' });
process.exit(r.status ?? 1);
