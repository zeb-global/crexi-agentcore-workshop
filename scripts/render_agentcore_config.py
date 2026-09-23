#!/usr/bin/env python3
"""Renders agentcore.json (+ the two harness.json files) for one participant's
WORKSHOP_ID, so that harness/gateway names -- which are literal, ACCOUNT-GLOBAL
physical AWS identifiers (Gateway Name, Harness Name, and the harness's own
IAM Role name), not namespaced by `--target` the way a CFN stack's *state* is
-- don't collide across participants sharing this account.

Two real, load-bearing facts this script exists to work around:

1. `agentcore deploy --target <id>` gives each participant an independently
   tracked CloudFormation stack (AgentCore-crexiWorkshopV2-<id>), but every
   physical name inside that stack (Gateway Name, Harness Name -> IAM Role
   name) is still derived directly from agentcore.json's plain `name` fields.
   Two participants both deploying a harness named "investorAgent" collide on
   the SAME IAM Role, even in separate stacks/targets. So every name gets
   suffixed with WORKSHOP_ID here.

2. A harness's `agentcore_gateway` tool config embeds a LITERAL resolved
   `gatewayArn` string -- confirmed by reading the synthesized CFN template --
   it is NOT an in-stack CDK reference to the gateway resource sitting right
   next to it. AWS assigns that ARN's random suffix at gateway-creation time,
   so a brand-new participant's gateway ARN literally cannot be known before
   it exists. That forces a two-phase deploy for a participant's FIRST
   bootstrap: deploy the (uniquely-named) gateways alone, read back their real
   ARNs from agentcore/.cli/deployed-state.json, THEN render+deploy the
   harnesses referencing those ARNs.

3. `agentcore validate` derives a harness's config directory from its
   registry `name` as `app/<name>/harness.json` -- confirmed live -- even
   though agentcore.json's own harness registry has a separate `path` field
   documented as "project-relative harness config directory". A uniquely
   named harness therefore needs its own directory, so this script generates
   one (app/<base>_<workshop_id>/) by copying the canonical
   app/<base>/{harness.json,system-prompt.md} rather than requiring anyone to
   hand-maintain per-participant copies; these generated dirs are gitignored.

4. app/brokerAgent/system-prompt.md names the legacy deal desk's Lambda
   Function URL as literal text for the model to navigate the Browser tool
   to. Found live: a second participant's broker harness tried to log into
   the FIRST participant's legacy desk with their OWN credentials and
   failed ("Invalid username or password"), because that URL was hardcoded
   to whichever workshop deployed first. This script patches in the real
   per-participant URL (from Crexi<id>Legacy's LegacyDeskUrl output) when
   generating the harness dir.

Usage:
    python3 scripts/render_agentcore_config.py <WORKSHOP_ID> gateways
    python3 scripts/render_agentcore_config.py <WORKSHOP_ID> harnesses
"""
import json
import re
import subprocess
import sys
from pathlib import Path

# This project has exactly these four AgentCore-native resources; there is no
# need for this to be generic since a new one is only ever added by hand.
GATEWAYS = [
    # (base gateway name, its single target name, Lambda CFN output key)
    ("gw-readonly", "market-data", "MarketDataFunctionArn"),
    ("gw-ops", "listing-ops", "ListingOpsFunctionArn"),
]
HARNESSES = ["investorAgent", "brokerAgent"]
LEGACY_DESK_URL_RE = re.compile(r"https://[a-z0-9]+\.lambda-url\.[a-z0-9-]+\.on\.aws/")
# harness name charset is ^[a-zA-Z][a-zA-Z0-9_]{0,39}$ -- no hyphens.
HARNESS_SEP = "_"
# gateway names may use hyphens.
GATEWAY_SEP = "-"

AGENTCORE_JSON = "agentcore/agentcore.json"
STATE_JSON = "agentcore/.cli/deployed-state.json"


def cfn_output(stack: str, key: str) -> str:
    result = subprocess.run(
        [
            "aws", "cloudformation", "describe-stacks", "--stack-name", stack,
            "--query", f"Stacks[0].Outputs[?OutputKey=='{key}'].OutputValue",
            "--output", "text",
        ],
        capture_output=True, text=True, check=True,
    )
    arn = result.stdout.strip()
    if not arn:
        raise SystemExit(f"No output '{key}' on stack {stack} -- was 'cdk deploy' run for this WORKSHOP_ID?")
    return arn


def gateway_name(base: str, workshop_id: str) -> str:
    return f"{base}{GATEWAY_SEP}{workshop_id}"


def harness_name(base: str, workshop_id: str) -> str:
    return f"{base}{HARNESS_SEP}{workshop_id}"


def render_gateways(config: dict, workshop_id: str) -> None:
    tools_stack = f"Crexi{workshop_id}Tools"
    by_base = {base: (target_name, output_key) for base, target_name, output_key in GATEWAYS}
    for gw in config["agentCoreGateways"]:
        base = next(b for b in by_base if gw["name"] == b or gw["name"].startswith(b + GATEWAY_SEP))
        target_name, output_key = by_base[base]
        gw["name"] = gateway_name(base, workshop_id)
        arn = cfn_output(tools_stack, output_key)
        for target in gw["targets"]:
            if target["name"] == target_name:
                target["lambdaFunctionArn"]["lambdaArn"] = arn


def deployed_gateway_arn(workshop_id: str, base: str) -> str:
    with open(STATE_JSON) as f:
        state = json.load(f)
    gateways = state.get("targets", {}).get(workshop_id, {}).get("resources", {}).get("mcp", {}).get("gateways", {})
    entry = gateways.get(gateway_name(base, workshop_id))
    if not entry:
        raise SystemExit(
            f"No deployed gateway '{gateway_name(base, workshop_id)}' found for target '{workshop_id}' in "
            f"{STATE_JSON} -- run the 'gateways' phase and 'agentcore deploy --target {workshop_id}' first."
        )
    return entry["gatewayArn"]


def render_harnesses(config: dict, workshop_id: str) -> None:
    target_to_base = {target_name: base for base, target_name, _ in GATEWAYS}
    config["harnesses"] = []
    for base in HARNESSES:
        name = harness_name(base, workshop_id)
        src_dir = Path("app") / base
        dst_dir = Path("app") / f"{base}_{workshop_id}"
        dst_dir.mkdir(exist_ok=True)

        system_prompt = (src_dir / "system-prompt.md").read_text()
        if base == "brokerAgent":
            legacy_url = cfn_output(f"Crexi{workshop_id}Legacy", "LegacyDeskUrl")
            system_prompt = LEGACY_DESK_URL_RE.sub(legacy_url, system_prompt)
        (dst_dir / "system-prompt.md").write_text(system_prompt)

        config["harnesses"].append({"name": name, "path": str(dst_dir)})

        with open(src_dir / "harness.json") as f:
            harness = json.load(f)
        harness["name"] = name
        for tool in harness["tools"]:
            if tool["type"] == "agentcore_gateway":
                gw_base = target_to_base[tool["name"]]
                tool["config"]["agentCoreGateway"]["gatewayArn"] = deployed_gateway_arn(workshop_id, gw_base)
        with open(dst_dir / "harness.json", "w") as f:
            json.dump(harness, f, indent=2)
            f.write("\n")


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[2] not in ("gateways", "harnesses"):
        raise SystemExit(__doc__)
    workshop_id, phase = sys.argv[1], sys.argv[2]

    with open(AGENTCORE_JSON) as f:
        config = json.load(f)

    render_gateways(config, workshop_id)
    if phase == "gateways":
        config["harnesses"] = []
    else:
        render_harnesses(config, workshop_id)

    with open(AGENTCORE_JSON, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    print(f"Rendered {AGENTCORE_JSON} for target '{workshop_id}', phase '{phase}'.")


if __name__ == "__main__":
    main()
