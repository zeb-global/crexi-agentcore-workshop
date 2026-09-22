"""Gateway Lambda target for the read-only 'market-data' MCP tools.

Registered on the investor harness's gw-readonly gateway. Investor and
broker harnesses hold different IAM permissions on the two gateways, so
a cross-role tool call (investor -> gw-ops) fails as a real IAM denial in
CloudTrail rather than a model politely declining -- see Checkpoint 3.

Gateway invokes with a flat event = the tool's input properties, and passes
the tool name (prefixed "<target>___<tool>") via
context.client_context.custom['bedrockAgentCoreToolName'].
"""
import json
import os
from decimal import Decimal

import boto3
from pypdf import PdfReader
import io

dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3")

LISTINGS_TABLE = os.environ.get("LISTINGS_TABLE", "")
DOCS_BUCKET = os.environ.get("DOCS_BUCKET", "")


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


def search_listings(args: dict) -> dict:
    table = dynamodb.Table(LISTINGS_TABLE)
    resp = table.scan()
    items = resp.get("Items", [])

    market = args.get("market")
    asset_type = args.get("assetType")
    units_min = args.get("unitsMin")
    units_max = args.get("unitsMax")
    price_max = args.get("priceMax")
    value_add = args.get("valueAdd")

    def keep(item):
        if market and item.get("market") != market:
            return False
        if asset_type and item.get("assetType") != asset_type:
            return False
        if units_min is not None and int(item.get("units", 0)) < int(units_min):
            return False
        if units_max is not None and int(item.get("units", 0)) > int(units_max):
            return False
        if price_max is not None and int(item.get("askingPrice", 0)) > int(price_max):
            return False
        if value_add is not None and bool(item.get("valueAdd")) != bool(value_add):
            return False
        return True

    results = [
        {k: v for k, v in item.items() if k != "noi"}  # NOI is not exposed here -- get_document_text only
        for item in items if keep(item)
    ]
    return {"listings": _decimals_to_native(results)}


def get_listing(args: dict) -> dict:
    table = dynamodb.Table(LISTINGS_TABLE)
    item = table.get_item(Key={"listingId": args["listingId"]}).get("Item")
    if not item:
        return {"error": f"No listing with id {args['listingId']!r}"}
    item.pop("noi", None)
    return _decimals_to_native(item)


def get_market_comps(args: dict) -> dict:
    obj = s3.get_object(Bucket=DOCS_BUCKET, Key="comps/columbus-multifamily-2025.json")
    return json.loads(obj["Body"].read())


def list_property_documents(args: dict) -> dict:
    listing_id = args["listingId"]
    prefix = f"documents/{listing_id}/"
    resp = s3.list_objects_v2(Bucket=DOCS_BUCKET, Prefix=prefix)
    docs = [obj["Key"].rsplit("/", 1)[-1] for obj in resp.get("Contents", [])]
    return {"listingId": listing_id, "documents": docs}


def get_document_text(args: dict) -> dict:
    listing_id = args["listingId"]
    doc_name = args["documentName"]
    key = f"documents/{listing_id}/{doc_name}"
    obj = s3.get_object(Bucket=DOCS_BUCKET, Key=key)
    reader = PdfReader(io.BytesIO(obj["Body"].read()))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return {"listingId": listing_id, "documentName": doc_name, "text": text}


_DISPATCH = {
    "search_listings": search_listings,
    "get_listing": get_listing,
    "get_market_comps": get_market_comps,
    "list_property_documents": list_property_documents,
    "get_document_text": get_document_text,
}


def lambda_handler(event, context):
    tool_name = _tool_name(context)
    fn = _DISPATCH.get(tool_name)
    if fn is None:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        return fn(event or {})
    except Exception as e:  # noqa: BLE001 -- surfaced to the model as a tool error
        return {"error": str(e)}
