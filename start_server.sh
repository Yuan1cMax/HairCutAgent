#!/usr/bin/env bash
set -euo pipefail

cd /home/ubuntu/barber_api

# Load deployment-only secrets from the untracked server environment file.
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source ./.env
  set +a
fi

: "${ADMIN_TOKEN:?ADMIN_TOKEN must be set in /home/ubuntu/barber_api/.env or the environment}"
export ADMIN_TOKEN

pkill -f "[p]ython3 main.py" || true
nohup python3 main.py > barber_api.log 2>&1 &

sleep 3
ps -ef | grep "python3 main.py" | grep -v grep || true
