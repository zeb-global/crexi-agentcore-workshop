"""Gateway Lambda target for the 'listing-ops' MCP tools -- read-only.

Deliberately does NOT include a price-write tool. A Gateway Lambda target
has no reliable signal for who the real caller is: the invocation context
carries only gateway/target/tool IDs (see AWS's own boilerplate for Lambda
targets), never the end user's identity. A `brokerId` argument here would
just be whatever the model was told to pass -- not enforcement.

The actual price write is an AgentCore Harness INLINE FUNCTION, handled by
backend/confirmation.py, which validated the caller's Cognito JWT itself
when the session started. That is the real trust boundary, and it writes
to the same changelog table this tool reads from.
"""
import os
from decimal import Decimal

import boto3

dynamodb = boto3.resource("dynamodb")

CHANGELOG_TABLE = os.environ.get("CHANGELOG_TABLE", "")


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


_DISPATCH = {"get_change_log": get_change_log}


def lambda_handler(event, context):
    tool_name = _tool_name(context)
    fn = _DISPATCH.get(tool_name)
    if fn is None:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        return fn(event or {})
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
