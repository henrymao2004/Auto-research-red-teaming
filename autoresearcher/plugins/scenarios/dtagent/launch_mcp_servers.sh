#!/bin/bash
# Deprecated no-op launcher.
set -u
echo "[launch_mcp_servers] no-op: dtagent tool servers are bridged in-process by"
echo "  tools_mcp.py (dtap_servers/*_main.py). No host MCP server or external clone"
echo "  is needed. Bring backends up with: build_dtagent_backends.sh all"
