"""Gateway Lambda target for the 'listing-ops' MCP tools.

update_listing_price is the write path Marcus's confirmed price change
commits through -- matching the "agent proposes, MCP commits" pattern.

The trust problem this has to solve: a Gateway Lambda target gets no
reliable signal for who the real caller is (the invocation context carries
only gateway/target/tool IDs -- see AWS's Lambda-target boilerplate), so a
`brokerId` argument here would just be whatever the model was told to pass,
not real enforcement. The fix is an approval token, not a client-side
write:

  1. The broker harness's `confirm_listing_change` INLINE FUNCTION pauses
     the loop and hands control to the backend, which knows the real,
     validated Cognito identity for this session.
  2. On the human's "yes", the backend mints a short-lived, single-use
     token bound to (listingId, newPrice) and stores it in the approvals
     table, keyed by that identity -- this is the one place the real
     identity check happens.
  3. The backend's toolResult hands the model that token. The model calls
     update_listing_price(listingId, newPrice, approvalToken).
  4. This Lambda validates the token (exists, unexpired, unused, matches
     this exact listingId+newPrice) and consumes it atomically. It never
     needs to know who Marcus is -- the identity check already happened,
     once, correctly, at mint time.
"""
import os
import time
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr

dynamodb = boto3.resource("dynamodb")

CHANGELOG_TABLE = os.environ.get("CHANGELOG_TABLE", "")
LISTINGS_TABLE = os.environ.get("LISTINGS_TABLE", "")
APPROVALS_TABLE = os.environ.get("APPROVALS_TABLE", "")


def _tool_name(context) -> str:
    raw = context.client_context.custom["bedrockAgentCoreToolName"]
    delimiter = "___"
    idx = raw.find(delimiter)
    return raw[idx + len(delimiter):] if idx != -1 else raw


def _decimals_to_native(obj):
    if isinstance(obj, list):
        return [_decimals_to_native(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _decimals_to_native(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    return obj


def get_change_log(args: dict) -> dict:
    table = dynamodb.Table(CHANGELOG_TABLE)
    resp = table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("listingId").eq(args["listingId"]),
        ScanIndexForward=False,
        Limit=int(args.get("limit", 10)),
    )
    return {"listingId": args["listingId"], "changes": _decimals_to_native(resp.get("Items", []))}


def update_listing_price(args: dict) -> dict:
    listing_id = args["listingId"]
    new_price = int(args["newPrice"])
    token = args["approvalToken"]

    approvals = dynamodb.Table(APPROVALS_TABLE)
    approval = approvals.get_item(Key={"approvalToken": token}).get("Item")
    if not approval:
        return {"error": "Approval token not found or already used."}
    if approval.get("listingId") != listing_id or int(approval.get("newPrice", -1)) != new_price:
        return {"error": "Approval token does not match this listingId/newPrice."}
    if int(time.time()) > int(approval.get("expiresAt", 0)):
        return {"error": "Approval token has expired."}

    # Consume the token atomically -- a replayed or duplicate call fails here.
    try:
        approvals.delete_item(
            Key={"approvalToken": token},
            ConditionExpression=Attr("approvalToken").eq(token),
        )
    except Exception:
        return {"error": "Approval token already consumed."}

    listings = dynamodb.Table(LISTINGS_TABLE)
    try:
        result = listings.update_item(
            Key={"listingId": listing_id},
            UpdateExpression="SET askingPrice = :newPrice, version = version + :one",
            ConditionExpression=Attr("version").eq(int(approval["version"])),
            ExpressionAttributeValues={":newPrice": new_price, ":one": 1},
            ReturnValues="ALL_NEW",
        )
    except Exception as e:  # noqa: BLE001 -- e.g. a conditional-check failure on a stale version
        return {"error": f"Write failed: {e}"}

    changelog = dynamodb.Table(CHANGELOG_TABLE)
    changelog.put_item(Item={
        "listingId": listing_id,
        "changedAt": approval["mintedAt"],
        "actor": approval["actor"],
        "actorSource": "mcp",
        "field": "askingPrice",
        "oldValue": int(approval["oldPrice"]),
        "newValue": new_price,
        "sessionId": approval.get("sessionId", ""),
    })

    return {"listingId": listing_id, "newPrice": new_price, "status": "updated"}


_DISPATCH = {"get_change_log": get_change_log, "update_listing_price": update_listing_price}


def lambda_handler(event, context):
    tool_name = _tool_name(context)
    fn = _DISPATCH.get(tool_name)
    if fn is None:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        return fn(event or {})
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
