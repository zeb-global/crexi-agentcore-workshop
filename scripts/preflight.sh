#!/usr/bin/env bash
# Fails loudly with the exact missing item, before anyone burns fifteen
# minutes on a deploy that was going to fail anyway. Every check here maps
# to a real failure mode this build (or a prior workshop) actually hit.
set -uo pipefail
cd "$(dirname "$0")/.."
FAIL=0

check() { printf '%-55s' "$1"; }
ok()    { echo "OK  $1"; }
bad()   { echo "FAIL  $1"; FAIL=1; }

check "Node.js >= 20"
if command -v node >/dev/null && [ "$(node -e 'console.log(process.versions.node.split(".")[0])')" -ge 20 ] 2>/dev/null; then
  ok "$(node --version)"
else
  bad "node not found or < 20 -- install from nodejs.org"
fi

check "Python >= 3.12"
PYVER=$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null)
if [ -n "$PYVER" ] && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)'; then
  ok "python $PYVER"
else
  bad "python3 not found or < 3.12"
fi

check "AWS CLI v2"
if command -v aws >/dev/null && aws --version 2>&1 | grep -q "aws-cli/2"; then
  ok "$(aws --version 2>&1)"
else
  bad "aws-cli v2 not found"
fi

check "AgentCore CLI installed"
if command -v agentcore >/dev/null; then
  AC_VERSION=$(agentcore --version 2>&1 | tail -1)
  ok "$AC_VERSION"
else
  bad "agentcore CLI not found -- npm install -g @aws/agentcore"
fi

check "No shadowing pip agentcore on PATH"
# The CLI's own known failure mode: an old bedrock-agentcore-starter-toolkit
# pip package shadows the npm 'agentcore' command, most common on machines
# that also did Python-based AgentCore tutorials.
if agentcore --version 2>&1 | grep -qiE "^[0-9]+\.[0-9]+\.[0-9]+"; then
  ok "npm agentcore responds with a version"
else
  bad "agentcore --version did not return a version -- run: pip uninstall bedrock-agentcore-starter-toolkit"
fi

check "AWS credentials valid"
if IDENTITY=$(aws sts get-caller-identity --output json 2>&1); then
  ACCOUNT=$(echo "$IDENTITY" | python3 -c 'import json,sys; print(json.load(sys.stdin)["Account"])' 2>/dev/null)
  ok "account $ACCOUNT"
else
  bad "aws sts get-caller-identity failed -- credentials missing or expired"
fi

check "Effective AWS region is us-west-2"
# Not the *configured* region -- the EFFECTIVE one. AWS_REGION in a shell
# profile can silently override a correctly-configured AWS CLI profile,
# and the resulting error looks like a permissions problem, not a region
# problem. This bit a prior workshop.
EFFECTIVE_REGION=$(aws configure list 2>&1 | awk '/^region/ {print $3}')
if [ "$EFFECTIVE_REGION" = "us-west-2" ]; then
  ok "us-west-2"
else
  bad "effective region is '$EFFECTIVE_REGION', not us-west-2 -- check AWS_REGION/AWS_DEFAULT_REGION env vars, which override the profile"
fi

check "CDK bootstrapped in this account/region"
if aws cloudformation describe-stacks --stack-name CDKToolkit >/dev/null 2>&1; then
  ok "CDKToolkit stack present"
else
  bad "CDK not bootstrapped -- run: cdk bootstrap"
fi

check "Bedrock models invocable (Sonnet 4.6 / Opus 4.6 / Nova Lite)"
# Bedrock enables foundation-model access by default, so this checks for
# region/profile mistakes, not a missing grant -- see scope-and-architecture.md.
MODELS_OK=1
for MODEL_ID in "us.anthropic.claude-sonnet-4-6" "us.anthropic.claude-opus-4-6-v1" "us.amazon.nova-lite-v1:0"; do
  if ! aws bedrock-runtime converse \
        --model-id "$MODEL_ID" \
        --messages '[{"role":"user","content":[{"text":"hi"}]}]' \
        --inference-config '{"maxTokens":8}' >/dev/null 2>&1; then
    MODELS_OK=0
    echo "    -- $MODEL_ID not invocable"
  fi
done
if [ "$MODELS_OK" = "1" ]; then
  ok "all three invocable"
else
  bad "one or more models not invocable -- check inference profile IDs for this region"
fi

check "WORKSHOP_ID set and valid"
if [ -n "${WORKSHOP_ID:-}" ]; then
  if [[ "$WORKSHOP_ID" =~ ^[a-zA-Z][a-zA-Z0-9]*$ ]]; then
    ok "$WORKSHOP_ID"
  else
    bad "WORKSHOP_ID='$WORKSHOP_ID' must start with a letter, letters/digits only"
  fi
else
  bad "WORKSHOP_ID not set -- export WORKSHOP_ID=<yourid>"
fi

echo ""
if [ "$FAIL" = "1" ]; then
  echo "Preflight FAILED -- fix the items above before 'make bootstrap'."
  exit 1
else
  echo "Preflight passed."
fi
