"""Resolves the two inline functions brokerAgent can pause on.

Both resolvers use the REAL, validated identity from the session (the
`actor` username passed in from main.py, which came from a verified
Cognito JWT) -- never anything the model supplied. This is the actual
trust boundary the whole Checkpoint 4 design depends on: see
scope-and-architecture.md §4.2 and docs/checkpoint4-results.md.

get_legacy_credentials now does a REAL per-user 3-legged OAuth exchange
against AgentCore Identity's Token Vault (Checkpoint 4 / Legacy Portal
OAuth), not a DynamoDB lookup. First call for a given broker: nothing is
cached yet, so this mints an authorization URL and hands it back as the
tool result -- the system prompt tells the model to relay that URL to the
broker and wait. Every later call (until the token expires): the Token
Vault already has it, so this returns a real access token immediately,
no repeat consent. Confirmed live against a real Cognito-backed OAuth2
credential provider, including the CompleteResourceTokenAuth step in
main.py's /oauth/legacy-callback route -- see that route for the other
half of this flow.

WORKSHOP SIMPLIFICATION (see the walkthrough and README's Known
Limitations): this uses GetWorkloadAccessTokenForUserId (the "quickstart"
path AWS's own docs describe for exactly this kind of demo), not the
production-recommended GetWorkloadAccessTokenForJWT, which would
propagate the broker's actual inbound Cognito JWT instead of a bare
username string AgentCore trusts us to have already verified.

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
_identity = boto3.client("bedrock-agentcore", region_name=config.AWS_REGION)

# session_uri -> the broker username who initiated that authorization
# request. Populated when we mint a fresh authorization URL, consumed by
# main.py's /oauth/legacy-callback to know which user to bind the
# completed session to. In-memory, same pattern and same limitation as
# main.py's _paused_runs/_active_runs -- fine for this single-process
# reference backend, not for a production deployment (see module docs
# in main.py). PRODUCTION NOTE: AWS's own guidance is to verify the
# identity from the actual browser session (a cookie) at the callback,
# not to trust a server-side mapping like this one -- this is the
# workshop's deliberate simplification, called out explicitly rather
# than silently relied on.
_pending_oauth_sessions: dict[str, str] = {}

# Session URIs whose authorization has completed -- lets the frontend poll
# /oauth/legacy-status and auto-resume the chat turn once the broker
# finishes in the new tab, instead of requiring them to come back and
# type something before the agent will retry.
_completed_oauth_sessions: set[str] = set()


def is_oauth_session_complete(session_uri: str) -> bool:
    return session_uri in _completed_oauth_sessions


def resolve_legacy_credentials(actor: str) -> dict:
    """actor: the real signed-in username (e.g. 'marcus'), from a
    verified JWT -- see auth.py. Never anything the model supplied."""
    workload_token = _identity.get_workload_access_token_for_user_id(
        workloadName=config.LEGACY_OAUTH_WORKLOAD_NAME,
        userId=actor,
    )["workloadAccessToken"]

    try:
        result = _identity.get_resource_oauth2_token(
            workloadIdentityToken=workload_token,
            resourceCredentialProviderName=config.LEGACY_OAUTH_PROVIDER_NAME,
            scopes=["openid"],
            oauth2Flow="USER_FEDERATION",
            resourceOauth2ReturnUrl=config.LEGACY_OAUTH_RETURN_URL,
        )
    except Exception as e:  # noqa: BLE001 -- surfaced to the model as a tool error, not a crash
        return {"error": f"Legacy portal authorization failed: {e}"}

    if "accessToken" in result:
        return {"accessToken": result["accessToken"]}

    # No cached token yet -- this is the first time this broker has
    # connected the legacy portal (or their last token expired). Record
    # who's waiting so /oauth/legacy-callback can bind the right user,
    # then hand the URL back as the tool result; the system prompt tells
    # the model to relay it to the broker and wait for them to come back.
    _pending_oauth_sessions[result["sessionUri"]] = actor
    return {
        "authorizationRequired": True,
        "authorizationUrl": result["authorizationUrl"],
    }


def complete_legacy_oauth(session_uri: str) -> dict:
    """Called by main.py's /oauth/legacy-callback route once the broker's
    browser lands back here after granting consent. See module docs for
    the production caveat on how the user identity is bound here."""
    actor = _pending_oauth_sessions.pop(session_uri, None)
    if actor is None:
        return {"error": f"Unknown or already-completed session {session_uri!r}."}
    _identity.complete_resource_token_auth(
        sessionUri=session_uri,
        userIdentifier={"userId": actor},
    )
    _completed_oauth_sessions.add(session_uri)
    return {"actor": actor}


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
