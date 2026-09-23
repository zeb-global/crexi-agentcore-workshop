#!/usr/bin/env bash
# Confirms a deploy actually landed in a working state -- run after
# `make bootstrap` (or any `make deploy`), before `make dev`. Per
# scope-and-architecture.md's own spec for this command: `agentcore
# validate` first (catches a malformed harness.json before anyone
# wastes a deploy round trip on it), then `agentcore status --json
# --type harness` for the rest (both harnesses must report READY).
# Also checks the two local-only things that fail SILENTLY otherwise:
# backend/.env existing and actually being loadable by config.py.
set -uo pipefail
cd "$(dirname "$0")/.."
FAIL=0

check() { printf '%-55s' "$1"; }
ok()    { echo "OK  $1"; }
bad()   { echo "FAIL  $1"; FAIL=1; }

WORKSHOP_ID="${WORKSHOP_ID:-}"
if [ -z "$WORKSHOP_ID" ]; then
  bad "WORKSHOP_ID not set -- export WORKSHOP_ID=<yourid> (same one you bootstrapped with)"
  echo ""
  echo "Verify FAILED -- fix the items above."
  exit 1
fi

check "agentcore.json / harness.json valid"
VALIDATE_OUTPUT=$(agentcore validate 2>&1)
if echo "$VALIDATE_OUTPUT" | grep -qi "^Valid"; then
  ok "Valid"
else
  bad "agentcore validate failed -- see below"
  echo "$VALIDATE_OUTPUT" | tail -20
fi

check "Both harnesses deployed and READY"
STATUS_JSON=$(agentcore status --target "$WORKSHOP_ID" --type harness --json 2>/dev/null)
if [ -z "$STATUS_JSON" ]; then
  bad "agentcore status returned nothing -- has 'make bootstrap WORKSHOP_ID=$WORKSHOP_ID' completed?"
else
  NOT_READY=$(python3 -c "
import json, sys
try:
    data = json.loads(sys.argv[1])
except (ValueError, json.JSONDecodeError):
    print('__PARSE_ERROR__')
    sys.exit(0)
resources = data.get('resources', [])
harnesses = [r for r in resources if r.get('resourceType') == 'harness']
if len(harnesses) < 2:
    print(f'__ONLY_{len(harnesses)}_HARNESSES__')
    sys.exit(0)
targets = data.get('deployedState', {}).get('targets', {}).get(sys.argv[2], {})
harness_states = targets.get('resources', {}).get('harnesses', {})
bad_ones = [name for name, h in harness_states.items() if h.get('status') != 'READY']
print(','.join(bad_ones))
" "$STATUS_JSON" "$WORKSHOP_ID")
  if [ "$NOT_READY" = "__PARSE_ERROR__" ]; then
    bad "agentcore status --json did not return parseable JSON"
  elif [[ "$NOT_READY" == __ONLY_*_HARNESSES__ ]]; then
    FOUND_COUNT=$(echo "$NOT_READY" | sed -E 's/__ONLY_([0-9]+)_HARNESSES__/\1/')
    bad "expected 2 harnesses (investorAgent + brokerAgent) for WORKSHOP_ID=$WORKSHOP_ID, found $FOUND_COUNT -- has 'make bootstrap WORKSHOP_ID=$WORKSHOP_ID' been run?"
  elif [ -n "$NOT_READY" ]; then
    bad "not READY: $NOT_READY -- check: agentcore logs --target $WORKSHOP_ID"
  else
    ok "investorAgent_$WORKSHOP_ID + brokerAgent_$WORKSHOP_ID both READY"
  fi
fi

check "backend/.env present"
if [ -f backend/.env ]; then
  ok "backend/.env exists"
else
  bad "backend/.env not found -- run: make wire-backend-env WORKSHOP_ID=$WORKSHOP_ID"
fi

check "backend/.env matches this WORKSHOP_ID"
if [ -f backend/.env ]; then
  ENV_WORKSHOP_ID=$(grep '^WORKSHOP_ID=' backend/.env | cut -d= -f2)
  if [ "$ENV_WORKSHOP_ID" = "$WORKSHOP_ID" ]; then
    ok "$ENV_WORKSHOP_ID"
  else
    bad "backend/.env has WORKSHOP_ID=$ENV_WORKSHOP_ID, not $WORKSHOP_ID -- re-run: make wire-backend-env WORKSHOP_ID=$WORKSHOP_ID"
  fi
else
  bad "backend/.env not found -- skipping"
fi

check "Backend imports cleanly with this config"
if [ -f backend/.env ] && [ -d backend/.venv ]; then
  IMPORT_ERROR=$(cd backend && set -a && source .env && set +a && \
    .venv/bin/python3 -c "import main" 2>&1)
  if [ -z "$IMPORT_ERROR" ]; then
    ok "backend/main.py imports OK"
  else
    bad "backend/main.py failed to import -- see below"
    echo "$IMPORT_ERROR" | tail -15
  fi
else
  bad "backend/.venv or backend/.env missing -- run 'make bootstrap' first"
fi

echo ""
if [ "$FAIL" = "1" ]; then
  echo "Verify FAILED -- fix the items above before 'make dev'."
  exit 1
else
  echo "Verify passed."
fi
