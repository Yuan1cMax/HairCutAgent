#!/usr/bin/env bash
set -euo pipefail

cd /home/ubuntu/barber_api

# Persisted admin token for the lightweight admin console.
export ADMIN_TOKEN='REMOVED_CREDENTIAL'

pkill -f "python3 main.py" || true
nohup python3 main.py > barber_api.log 2>&1 &

sleep 3
ps -ef | grep "python3 main.py" | grep -v grep || true
