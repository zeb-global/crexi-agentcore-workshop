"""End-to-end driver for the broker harness: resolves inline-function
calls automatically using a resolver callback, so a whole multi-step
scenario (fetch credentials -> browser login -> confirm price ->
approval token -> write) can run as one script.

Handles the case where the model requests an inline function in
PARALLEL with other tool calls in the same turn: the harness cannot
auto-resolve past that boundary, so ALL pending toolUse blocks in the
final message must be answered together, in one toolResult-bearing
message, keyed by their own toolUseId.

This is the same round-trip logic backend/confirmation.py implements for
real against a live user; here the human side of confirm_listing_change
is answered by AUTO_APPROVE below, for testing only.
"""
import json
import time
import uuid
from decimal import Decimal

import boto3

REGION = "us-west-2"
HARNESS_ARN = "arn:aws:bedrock-agentcore:us-west-2:347272280436:harness/crexiWorkshopV2_brokerAgent-Zh8tLOhxvX"
AUTO_APPROVE = True

client = boto3.client("bedrock-agentcore", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)


def resolve_legacy_credentials(_input):
    return {"username": "marcus", "password": "Lg-0a37c7ec38b6c457"}


def resolve_confirm_listing_change(tool_input):
    listings = dynamodb.Table("crexi-dev01-listings")
    approvals = dynamodb.Table("crexi-dev01-approvals")

    listing = listings.get_item(Key={"listingId": tool_input["listingId"]}).get("Item")
    if not listing:
        return {"approved": False, "reason": "listing not found"}
    if not AUTO_APPROVE:
        return {"approved": False, "reason": "declined"}

    token = str(uuid.uuid4())
    approvals.put_item(Item={
        "approvalToken": token,
        "listingId": tool_input["listingId"],
        "newPrice": int(tool_input["newPrice"]),
        "oldPrice": int(tool_input["oldPrice"]),
        "version": int(listing["version"]),
        "actor": "marcus",
        "sessionId": "e2e-test",
        "mintedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "expiresAt": int(time.time()) + 120,
    })
    print(f"\n[TEST HARNESS: minted approval token {token} for "
          f"{tool_input['listingId']} {tool_input['oldPrice']} -> {tool_input['newPrice']}]")
    return {"approved": True, "approvalToken": token}


RESOLVERS = {
    "get_legacy_credentials": resolve_legacy_credentials,
    "confirm_listing_change": resolve_confirm_listing_change,
}


def _stream_once(session_id, messages):
    """Runs one invoke_harness call to completion, printing text as it
    streams. Content-block indices are PER-MESSAGE, not global, so we
    track tool-use blocks scoped to the CURRENT message only, resetting
    on every messageStart. If the stream ends with stopReason=tool_use,
    the pending set is exactly the toolUse blocks in the message that
    was open when the stream ended -- any EARLIER message's tool uses
    were necessarily auto-resolved already, or the stream would have
    ended there instead."""
    response = client.invoke_harness(harnessArn=HARNESS_ARN, runtimeSessionId=session_id, messages=messages)

    current_message_tools = {}  # contentBlockIndex -> {toolUseId, name, input_json}, this message only
    stop_reason = None

    for event in response["stream"]:
        if "messageStart" in event:
            current_message_tools = {}
        if "contentBlockStart" in event:
            start = event["contentBlockStart"].get("start", {})
            idx = event["contentBlockStart"]["contentBlockIndex"]
            if "toolUse" in start:
                current_message_tools[idx] = {
                    "toolUseId": start["toolUse"]["toolUseId"],
                    "name": start["toolUse"].get("name"),
                    "input_json": "",
                }
        if "contentBlockDelta" in event:
            delta = event["contentBlockDelta"].get("delta", {})
            idx = event["contentBlockDelta"].get("contentBlockIndex")
            if "text" in delta:
                print(delta["text"], end="", flush=True)
            if idx in current_message_tools and "toolUse" in delta:
                current_message_tools[idx]["input_json"] += delta["toolUse"].get("input", "")
        if "messageStop" in event:
            stop_reason = event["messageStop"].get("stopReason")
        if "runtimeClientError" in event:
            print("\n[runtimeClientError]", event["runtimeClientError"])

    print(f"\n[stream ended: stopReason={stop_reason}]")

    if stop_reason != "tool_use":
        return []
    return list(current_message_tools.values())


def run(prompt, session_id=None, max_turns=8):
    session_id = session_id or (str(uuid.uuid4()) + "-e2e")
    print(f"=== session {session_id} ===")
    messages = [{"role": "user", "content": [{"text": prompt}]}]

    for turn in range(max_turns):
        pending = _stream_once(session_id, messages)
        print(f"--- turn {turn}: {len(pending)} pending tool(s): {[p['name'] for p in pending]} ---")

        if not pending:
            return

        result_blocks = []
        for p in pending:
            resolver = RESOLVERS.get(p["name"])
            if resolver is None:
                print(f"[no resolver for {p['name']!r} -- stopping]")
                return
            tool_input = json.loads(p["input_json"]) if p["input_json"] else {}
            result = resolver(tool_input)
            result_blocks.append({"toolResult": {
                "toolUseId": p["toolUseId"], "content": [{"text": json.dumps(result)}], "status": "success",
            }})
        messages = [{"role": "user", "content": result_blocks}]

    print("[max_turns reached]")


if __name__ == "__main__":
    import sys
    prompt = sys.argv[1] if len(sys.argv) > 1 else (
        "Marcus needs to check the rent roll for hilliard-commons on the legacy deal desk first."
    )
    run(prompt)
