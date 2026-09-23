#!/usr/bin/env bash
# `agentcore deploy --target <name>` deploys the SAME harness/gateway
# definitions from agentcore.json into an independently-named CloudFormation
# stack (AgentCore-<project>-<target>) with its own tracked state -- it does
# NOT touch any other target's already-deployed stack. That's the real,
# CLI-native mechanism for per-participant isolation at the harness/gateway
# layer (there is no separate "workshop_id" concept -- WORKSHOP_ID simply
# IS the target name here), so every participant just needs their own entry
# in aws-targets.json before their first deploy. Idempotent: does nothing if
# WORKSHOP_ID is already a registered target.
set -euo pipefail
cd "$(dirname "$0")/.."

WORKSHOP_ID="${WORKSHOP_ID:?Usage: WORKSHOP_ID=<id> scripts/ensure-aws-target.sh}"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION="${AWS_REGION:-us-west-2}"

python3 - "$WORKSHOP_ID" "$ACCOUNT" "$REGION" <<'PY'
import json
import sys

workshop_id, account, region = sys.argv[1], sys.argv[2], sys.argv[3]
path = "agentcore/aws-targets.json"
with open(path) as f:
    targets = json.load(f)

if any(t["name"] == workshop_id for t in targets):
    print(f"Target '{workshop_id}' already registered in {path}.")
else:
    targets.append({
        "name": workshop_id,
        "description": f"Workshop participant {workshop_id}",
        "account": account,
        "region": region,
    })
    with open(path, "w") as f:
        json.dump(targets, f, indent=2)
        f.write("\n")
    print(f"Added target '{workshop_id}' to {path}.")
PY
