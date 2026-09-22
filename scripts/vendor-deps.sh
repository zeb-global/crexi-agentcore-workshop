#!/usr/bin/env bash
# Vendors pure-Python dependencies into the two MCP Lambda directories so
# `cdk deploy` never needs Docker or a Lambda layer -- CodeZip + a plain
# `pip install --target` is enough as long as nothing has a compiled
# extension (pypdf is confirmed pure-Python, no .so/.pyd files).
set -euo pipefail
cd "$(dirname "$0")/.."
pip install --quiet --no-compile --target services/mcp_market_data -r services/mcp_market_data/requirements.txt
echo "Vendored deps into services/mcp_market_data/"
