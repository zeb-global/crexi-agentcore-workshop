#!/usr/bin/env bash
# Writes backend/.env for one participant so the FastAPI backend talks to
# THEIR harnesses, Cognito pool, and tables instead of backend/config.py's
# dev01 fallback defaults (which only exist so `python -c "import config"`
# doesn't explode -- they are not a valid target for anyone else to run
# against). Run once after `make bootstrap`, and again after any `make
# deploy` that changes a harness ARN, before `make dev`.
set -euo pipefail
cd "$(dirname "$0")/.."

WORKSHOP_ID="${1:?Usage: scripts/wire-backend-env.sh <WORKSHOP_ID>}"
REGION="${AWS_REGION:-us-west-2}"

STATUS_JSON=$(agentcore status --target "$WORKSHOP_ID" --type harness --json 2>/dev/null)

INVESTOR_ARN=$(python3 -c "
import json, sys
resources = json.loads(sys.argv[1])['resources']
print(next(r['identifier'] for r in resources if r['name'].startswith('investorAgent')))
" "$STATUS_JSON")

BROKER_ARN=$(python3 -c "
import json, sys
resources = json.loads(sys.argv[1])['resources']
print(next(r['identifier'] for r in resources if r['name'].startswith('brokerAgent')))
" "$STATUS_JSON")

IDENTITY_STACK="Crexi${WORKSHOP_ID}Identity"
USER_POOL_ID=$(aws cloudformation describe-stacks --stack-name "$IDENTITY_STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text)
APP_CLIENT_ID=$(aws cloudformation describe-stacks --stack-name "$IDENTITY_STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='AppClientId'].OutputValue" --output text)

LEGACY_DESK_URL=$(aws cloudformation describe-stacks --stack-name "Crexi${WORKSHOP_ID}Legacy" \
  --query "Stacks[0].Outputs[?OutputKey=='LegacyDeskUrl'].OutputValue" --output text)

# Checkpoint 4 / Legacy Portal OAuth: creates (or reuses) the workload
# identity + credential provider this reference deployment needs, and
# wires the resulting Cognito/workload callback URLs together. See that
# script's own header for why this lives here and not in `make bootstrap`.
LEGACY_OAUTH_RETURN_URL="http://localhost:8000/oauth/legacy-callback"
OAUTH_NAMES=$(bash scripts/setup-legacy-oauth.sh "$WORKSHOP_ID" "$LEGACY_OAUTH_RETURN_URL")
LEGACY_OAUTH_WORKLOAD_NAME=$(echo "$OAUTH_NAMES" | grep LEGACY_OAUTH_WORKLOAD_NAME | cut -d= -f2)
LEGACY_OAUTH_PROVIDER_NAME=$(echo "$OAUTH_NAMES" | grep LEGACY_OAUTH_PROVIDER_NAME | cut -d= -f2)

cat > backend/.env <<EOF
WORKSHOP_ID=${WORKSHOP_ID}
AWS_REGION=${REGION}
INVESTOR_HARNESS_ARN=${INVESTOR_ARN}
BROKER_HARNESS_ARN=${BROKER_ARN}
COGNITO_USER_POOL_ID=${USER_POOL_ID}
COGNITO_APP_CLIENT_ID=${APP_CLIENT_ID}
LEGACY_DESK_URL=${LEGACY_DESK_URL}
LEGACY_OAUTH_WORKLOAD_NAME=${LEGACY_OAUTH_WORKLOAD_NAME}
LEGACY_OAUTH_PROVIDER_NAME=${LEGACY_OAUTH_PROVIDER_NAME}
LEGACY_OAUTH_RETURN_URL=${LEGACY_OAUTH_RETURN_URL}
EOF

echo "Wrote backend/.env for WORKSHOP_ID=${WORKSHOP_ID}."
