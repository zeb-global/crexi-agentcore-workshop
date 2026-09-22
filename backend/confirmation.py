"""Resolves the two inline functions brokerAgent can pause on.

Both resolvers use the REAL, validated identity from the session (the
`actor` username passed in from main.py, which came from a verified
Cognito JWT) -- never anything the model supplied. This is the actual
trust boundary the whole Checkpoint 4 design depends on: see
scope-and-architecture.md §4.2 and docs/checkpoint4-results.md.

get_legacy_credentials is auto-resolved with no human step at all.
confirm_listing_change is the one genuine AG-UI Interrupt: the human's
answer arrives later, via a ResumeEntry, so minting the approval token
happens in resolve_confirm_listing_change() only after that answer is
in hand (see main.py's resume handler).
"""
import time
import uuid

import boto3

import config

_dynamodb = boto3.resource("dynamodb", region_name=config.AWS_REGION)


def resolve_legacy_credentials(actor: str) -> dict:
    """actor: the real signed-in username (e.g. 'marcus'), from a
    verified JWT -- see auth.py. Never anything the model supplied."""
    creds_table = _dynamodb.Table(f"crexi-{config.WORKSHOP_ID}-legacy-creds")
    item = creds_table.get_item(Key={"username": actor}).get("Item")
    if not item:
        return {"error": f"No legacy-desk account on file for {actor!r}."}
    return {"username": item["username"], "password": item["password"]}


def mint_price_change_approval(actor: str, listing_id: str, old_price: int, new_price: int, session_id: str) -> dict:
    """Called only after the human has said yes. Mints a short-lived,
    single-use token bound to this exact write -- the MCP tool
    (services/mcp_listing_ops/handler.py) validates and consumes it,
    and never needs to know who the caller is."""
    listings = _dynamodb.Table(config.LISTINGS_TABLE)
    approvals = _dynamodb.Table(config.APPROVALS_TABLE)

    listing = listings.get_item(Key={"listingId": listing_id}).get("Item")
    if not listing:
        return {"approved": False, "reason": f"No listing {listing_id!r} found."}

    token = str(uuid.uuid4())
    approvals.put_item(Item={
        "approvalToken": token,
        "listingId": listing_id,
        "newPrice": int(new_price),
        "oldPrice": int(old_price),
        "version": int(listing["version"]),
        "actor": actor,
        "sessionId": session_id,
        "mintedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "expiresAt": int(time.time()) + config.APPROVAL_TOKEN_TTL_SECONDS,
    })
    return {"approved": True, "approvalToken": token}


def decline_price_change() -> dict:
    return {"approved": False, "reason": "declined by broker"}
