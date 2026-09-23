#!/usr/bin/env bash
# Sets up everything a fresh clone needs before `make bootstrap`'s own
# cdk/agentcore deploy steps can run, and everything `make dev` needs
# afterward. Confirmed this is genuinely missing by cloning fresh from
# origin and running the documented flow end to end -- infra/.venv,
# backend/.venv, frontend/node_modules, and agentcore/cdk/node_modules
# are all referenced elsewhere (cd infra && source .venv/bin/activate,
# cd backend && source .venv/bin/activate, cd frontend && npm run dev,
# and `agentcore deploy`'s own `tsc` build of agentcore/cdk) but nothing
# anywhere created any of the four. Idempotent -- safe to re-run.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "Vendoring pure-Python deps into services/mcp_market_data/ (CodeZip, no Docker/layer needed)..."
python3 -m pip install --quiet --no-compile --upgrade --target services/mcp_market_data -r services/mcp_market_data/requirements.txt
echo "Vendored deps into services/mcp_market_data/"

echo "Setting up infra/.venv (CDK app deps)..."
if [ ! -d infra/.venv ]; then
  python3 -m venv infra/.venv
fi
infra/.venv/bin/pip install --quiet --upgrade pip
infra/.venv/bin/pip install --quiet -r infra/requirements.txt
echo "infra/.venv ready."

echo "Installing agentcore/cdk/node_modules (npm) -- needed for agentcore deploy's own tsc build..."
(cd agentcore/cdk && npm install --silent)
echo "agentcore/cdk/node_modules ready."

echo "Setting up backend/.venv (FastAPI app deps)..."
if [ ! -d backend/.venv ]; then
  python3 -m venv backend/.venv
fi
backend/.venv/bin/pip install --quiet --upgrade pip
backend/.venv/bin/pip install --quiet -r backend/requirements.txt
echo "backend/.venv ready."

echo "Installing frontend/node_modules (npm)..."
(cd frontend && npm install --silent)
echo "frontend/node_modules ready."
