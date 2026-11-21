#!/usr/bin/env bash
# Idempotent Hetzner/Debian/Ubuntu installer for the Territory Signals weekly pipeline.
#
#   sudo bash deploy/vps/install.sh
#
# It creates (or updates) the Python virtualenv, installs requirements.txt, writes the environment file at
# /etc/territory-signals/kaiser-team.env (chmod 600) only when it is missing, and installs the systemd service and
# timer. It never overwrites an existing environment file and never starts a pipeline run.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
SERVICE_USER="${SERVICE_USER:-territory}"
ENV_DIR="/etc/territory-signals"
ENV_FILE="$ENV_DIR/kaiser-team.env"
UNIT_DIR="/etc/systemd/system"
VENV="$APP_DIR/.venv"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "install.sh must run as root (use sudo)." >&2
  exit 1
fi
if [[ ! -f "$APP_DIR/requirements.txt" ]]; then
  echo "requirements.txt not found in $APP_DIR; run this script from the repository." >&2
  exit 1
fi

echo "==> Territory Signals weekly install"
echo "    app:     $APP_DIR"
echo "    user:    $SERVICE_USER"

# 1. System packages. --no-install-recommends keeps the image small; rerunning apt is safe.
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
  ca-certificates curl git python3 python3-venv python3-pip \
  libpq5 tzdata

# 2. A dedicated system user (idempotent). The pipeline must not run as root.
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
  echo "    created system user $SERVICE_USER"
else
  echo "    system user $SERVICE_USER already exists"
fi

# 3. Virtualenv and dependencies. Always re-run pip so a git pull + install.sh is a real upgrade.
if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV"
  echo "    created $VENV"
else
  echo "    reusing $VENV"
fi
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/pip" install --requirement "$APP_DIR/requirements.txt"

# 4. Environment file: created once with mode 600; an existing file is never modified.
install -d -m 0755 "$ENV_DIR"
if [[ ! -f "$ENV_FILE" ]]; then
  umask 077
  cat > "$ENV_FILE" <<'EOF'
# Territory Signals — Kaiser Team weekly pipeline.
# Keep this file at mode 600. Fill in the secrets, then restart the timer.
# Cloud database (Supabase). Use the session-pooler or direct connection string.
SUPABASE_DB_URL=
# AI provider key named by config/clients/kaiser-team.yaml (llm.api_key_env).
LLM_API_KEY=
# SMTP for the Monday executive digest. DIGEST_TO must list internal team member emails only.
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
DIGEST_FROM=
DIGEST_TO=
# Optional: override the dashboard links in the digest.
# DASHBOARD_BASE_URL=https://kaiser-team-signals.mike-1d7.workers.dev
EOF
  chmod 600 "$ENV_FILE"
  echo "    wrote $ENV_FILE (mode 600)"
else
  chmod 600 "$ENV_FILE"
  echo "    kept existing $ENV_FILE (mode 600)"
fi

# 5. Ownership: the service user needs to write data/outbox and pipeline reports.
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

# 6. systemd units. Substitute the install path so a clone outside /opt also works.
tmp_service="$(mktemp)"
tmp_timer="$(mktemp)"
trap 'rm -f "$tmp_service" "$tmp_timer"' EXIT
sed "s#/opt/territory-signals#${APP_DIR}#g; s/^User=.*/User=${SERVICE_USER}/; s/^Group=.*/Group=${SERVICE_USER}/" \
  "$SCRIPT_DIR/territory-weekly.service" > "$tmp_service"
sed "s#/opt/territory-signals#${APP_DIR}#g" "$SCRIPT_DIR/territory-weekly.timer" > "$tmp_timer"
install -m 0644 "$tmp_service" "$UNIT_DIR/territory-weekly.service"
install -m 0644 "$tmp_timer" "$UNIT_DIR/territory-weekly.timer"
systemctl daemon-reload

if command -v systemd-analyze >/dev/null 2>&1; then
  systemd-analyze verify "$UNIT_DIR/territory-weekly.service" "$UNIT_DIR/territory-weekly.timer" || true
fi

# Enable (not start): starting the timer is a deliberate step in DEPLOY.md, so installation never sends a digest.
systemctl enable territory-weekly.timer

echo
echo "Installed. Next:"
echo "  1. sudo editor $ENV_FILE       # fill in the secrets (mode stays 600)"
echo "  2. sudo systemctl start territory-weekly.timer"
echo "  3. systemctl list-timers territory-weekly.timer --no-pager"
echo "  4. sudo systemctl start territory-weekly.service   # first run now"
echo "  5. sudo journalctl -u territory-weekly.service -n 200 --no-pager"
