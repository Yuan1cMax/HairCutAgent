#!/usr/bin/env bash
set -euo pipefail

cd /home/ubuntu/barber_api

# Keep the first deployment private; expose it through an authenticated HTTPS
# reverse proxy only after the MCP client and access policy are verified.
export MCP_TRANSPORT="${MCP_TRANSPORT:-streamable-http}"
export MCP_HOST="${MCP_HOST:-127.0.0.1}"
export MCP_PORT="${MCP_PORT:-8004}"

pkill -f "python3 mcp_server.py" || true
nohup python3 mcp_server.py > mcp_server.log 2>&1 &

sleep 3
ps -ef | grep "python3 mcp_server.py" | grep -v grep || true
