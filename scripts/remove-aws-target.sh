#!/usr/bin/env bash
# Counterpart to ensure-aws-target.sh, run by `make destroy` after that
# target's own CloudFormation stack has been deleted. Removes the target
# entry from aws-targets.json and its tracked state from
# agentcore/.cli/deployed-state.json so `agentcore status` and future
# tooling don't show a stale, already-deleted target.
set -euo pipefail
cd "$(dirname "$0")/.."

WORKSHOP_ID="${WORKSHOP_ID:?Usage: WORKSHOP_ID=<id> scripts/remove-aws-target.sh}"

python3 - "$WORKSHOP_ID" <<'PY'
import json
import sys

workshop_id = sys.argv[1]

targets_path = "agentcore/aws-targets.json"
with open(targets_path) as f:
    targets = json.load(f)
remaining = [t for t in targets if t["name"] != workshop_id]
with open(targets_path, "w") as f:
    json.dump(remaining, f, indent=2)
    f.write("\n")
print(f"Removed target '{workshop_id}' from {targets_path}.")

state_path = "agentcore/.cli/deployed-state.json"
try:
    with open(state_path) as f:
        state = json.load(f)
except FileNotFoundError:
    state = {"targets": {}}
if state.get("targets", {}).pop(workshop_id, None) is not None:
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")
    print(f"Removed target '{workshop_id}' from {state_path}.")
PY
