"""Resolves the two inline functions brokerAgent can pause on.

CHECKPOINT 4 STARTER -- both functions below raise NotImplementedError.
Fill them in per the workshop walkthrough. Both resolvers must use the
REAL, validated identity from the session (the `actor` username passed
in from main.py, which came from a verified Cognito JWT) -- NEVER
anything the model supplied. That is the actual trust boundary this
checkpoint depends on.

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
    verified JWT -- see auth.py. Never anything the model supplied.

    TODO(checkpoint 4): look up this actor's legacy-desk login from the
    `crexi-{WORKSHOP_ID}-legacy-creds` DynamoDB table (partition key
    "username") and return {"username": ..., "password": ...}. If no
    item exists for this actor, return an {"error": ...} dict instead
    of raising -- the model needs to see that as a tool result, not a
    crash.
    """
    raise NotImplementedError("checkpoint 4: resolve_legacy_credentials")


def mint_price_change_approval(actor: str, listing_id: str, old_price: int, new_price: int, session_id: str) -> dict:
    """Called only after the human has said yes.

    TODO(checkpoint 4): mint a short-lived, single-use approval token
    bound to this exact write, and store it in the
    `config.APPROVALS_TABLE` DynamoDB table so the listing-ops MCP tool
    (services/mcp_listing_ops/handler.py) can validate and consume it
    without ever needing to know who the caller is. At minimum, record:
    approvalToken (a fresh uuid4), listingId, oldPrice, newPrice, the
    listing's current version (read it fresh from
    config.LISTINGS_TABLE first -- do not trust a version the caller
    passed in), actor, sessionId, mintedAt, and an expiresAt using
    config.APPROVAL_TOKEN_TTL_SECONDS. Return
    {"approved": True, "approvalToken": token}. If the listing doesn't
    exist, return {"approved": False, "reason": ...} instead.
    """
    raise NotImplementedError("checkpoint 4: mint_price_change_approval")


def decline_price_change() -> dict:
    return {"approved": False, "reason": "declined by broker"}
