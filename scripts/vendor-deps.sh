#!/usr/bin/env bash
# Sets up everything a fresh clone needs before `make bootstrap`'s own
# CDK deploy can run, and everything `make dev` needs afterward. On this
# branch, `agentcore/` doesn't exist yet at this point -- WORKSHOP_GUIDE.md's
# Phase 0 creates it (via `agentcore create`) and installs its own
# `agentcore/cdk/node_modules` there directly, since that directory isn't
# here for this script to touch yet. Idempotent -- safe to re-run.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "Vendoring pure-Python deps into services/mcp_market_data/ (CodeZip, no Docker/layer needed)..."
python3 -m pip install --quiet --no-compile --upgrade --target services/mcp_market_data -r services/mcp_market_data/requirements.txt
echo "Vendored deps into services/mcp_market_data/"

echo "Vendoring pure-Python deps into services/legacy_deal_desk/ (bare python-jose, no compiled crypto backend)..."
python3 -m pip install --quiet --no-compile --upgrade --target services/legacy_deal_desk -r services/legacy_deal_desk/requirements.txt
echo "Vendored deps into services/legacy_deal_desk/"

echo "Setting up infra/.venv (CDK app deps)..."
# Checks for a working pip binary, not just that the directory exists --
# a venv dir can exist but be broken (e.g. left over from a system Python
# upgrade after it was created), and `-d` alone would silently try to use
# it and fail deep inside pip with a confusing error. Recreate whenever
# it's not there or not actually runnable.
if [ ! -x infra/.venv/bin/pip ]; then
  rm -rf infra/.venv
  python3 -m venv infra/.venv
fi
infra/.venv/bin/pip install --quiet --upgrade pip
infra/.venv/bin/pip install --quiet -r infra/requirements.txt
echo "infra/.venv ready."

echo "Setting up backend/.venv (FastAPI app deps)..."
if [ ! -x backend/.venv/bin/pip ]; then
  rm -rf backend/.venv
  python3 -m venv backend/.venv
fi
backend/.venv/bin/pip install --quiet --upgrade pip
backend/.venv/bin/pip install --quiet -r backend/requirements.txt
echo "backend/.venv ready."

echo "Installing frontend/node_modules (npm)..."
(cd frontend && npm install --silent)
echo "frontend/node_modules ready."
