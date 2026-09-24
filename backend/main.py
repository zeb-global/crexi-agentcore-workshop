"""FastAPI backend: Cognito auth, the /agui SSE endpoint (AG-UI protocol
over InvokeHarness), and small supporting endpoints for artifacts and
the Browser live view.

Session state for a paused run (confirm_listing_change awaiting a human
answer) is kept in memory, keyed by run_id -- acceptable for this
single-process reference/workshop backend; a production version would
persist it (e.g. DynamoDB) so a restart doesn't strand a pending run.
"""
import json
import logging
import re
import time
import uuid

from ag_ui.core import (
    Interrupt,
    RunFinishedEvent,
    RunFinishedInterruptOutcome,
    RunFinishedSuccessOutcome,
    StateDeltaEvent,
)
from ag_ui.encoder import EventEncoder
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse

import auth
import config
import confirmation
import harness_client
import pricing
from agui_translate import translate_stream

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("crexi-backend")

app = FastAPI(title="CREXi Workshop Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

_encoder = EventEncoder()

# run_id -> {"harness_arn", "session_id", "actor", "group", "pending_tool_use_id",
#            "listing_id", "old_price", "new_price"}
# Populated when a run pauses on confirm_listing_change; consumed on resume.
_paused_runs: dict[str, dict] = {}

# run_id -> {"harness_arn", "session_id"}. Populated the instant a run
# starts streaming, popped when it finishes/errors/is stopped. This is
# what /agui/stop looks up to know WHICH harness session to actually
# halt server-side via StopRuntimeSession -- the run_id the frontend
# already tracks is not itself a valid AWS identifier for that call.
_active_runs: dict[str, dict] = {}

# Catches a model that answers an underwriting-style comparison in plain
# prose without ever calling code-interpreter at all -- the comparison
# card only renders if code-interpreter's own stdout contains the JSON
# payload, which is not guaranteed (observed live: the model can
# just narrate an answer and end the turn with stopReason=end_turn,
# touching no tool whatsoever). Requiring BOTH "cap rate" and a second,
# more specific underwriting term keeps this from false-positiving on a
# reply that merely mentions a cap rate figure a tool already returned.
_UNVERIFIED_UNDERWRITING_RE = re.compile(
    r"cap[\s-]?rate", re.IGNORECASE
), re.compile(r"dscr|cash[\s-]?on[\s-]?cash", re.IGNORECASE)


def _looks_like_unverified_underwriting(text: str) -> bool:
    cap_rate_re, other_re = _UNVERIFIED_UNDERWRITING_RE
    return bool(cap_rate_re.search(text) and other_re.search(text))


def _require_actor(request: Request) -> dict:
    authz = request.headers.get("authorization", "")
    if not authz.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token.")
    try:
        claims = auth.verify_token(authz[len("Bearer "):])
    except auth.AuthError as e:
        raise HTTPException(401, str(e))
    group = auth.group_for_claims(claims)
    if group is None:
        raise HTTPException(403, "User is not in the investors or brokers group.")
    return {"sub": claims["sub"], "username": claims.get("username", claims["sub"]), "group": group}


@app.post("/auth/login")
async def login(body: dict):
    username = body.get("username", "")
    password = body.get("password", "")
    try:
        result = auth.login(username, password)
    except auth.AuthError as e:
        raise HTTPException(401, str(e))
    claims = auth.verify_token(result["AccessToken"])
    group = auth.group_for_claims(claims)
    return {
        "accessToken": result["AccessToken"],
        "idToken": result["IdToken"],
        "expiresIn": result["ExpiresIn"],
        "group": group,
        "username": claims.get("username", username),
    }


def _drain_and_resolve(
    harness_arn: str, session_id: str, thread_id: str, actor: dict, run_id: str, harness_stream,
    *, emit_run_started: bool, underwriting_retries_left: int = 1,
):
    """Runs translate_stream over one harness call, forwarding every
    AG-UI event as an SSE-ready dict. Auto-resolves get_legacy_credentials
    transparently (loops back into the harness with the credential and
    keeps draining); stops for real -- emitting a genuine Interrupt --
    on confirm_listing_change, which needs an actual human answer.

    Underwriting comparisons need no separate confirmation tool call:
    translate_stream() parses the JSON straight out of code-interpreter's
    own stdout the moment its result streams back, so there is no second
    tool call whose sequencing could be gotten wrong, rejected, and
    retried -- the whole class of "submit_underwriting_result called
    before code-interpreter finished" failure no longer has a place to
    occur.
    """
    gen = translate_stream(harness_stream, thread_id=thread_id, run_id=run_id, emit_run_started=emit_run_started)
    result = None
    for item in gen:
        if isinstance(item, dict):
            result = item
            break
        yield _encoder.encode(item)

    if result is None:
        return

    comparison = result.get("underwriting_comparison")
    if comparison:
        yield _encoder.encode(StateDeltaEvent(
            delta=[{"op": "replace", "path": "/comparison", "value": comparison}]
        ))

    active_listings = result.get("active_listings")
    if active_listings is not None:
        # Mirrors whatever the agent's own search_listings/get_listing
        # call just returned into the browse grid, live -- the grid
        # reacts to the conversation, it is not an independent filter UI.
        yield _encoder.encode(StateDeltaEvent(
            delta=[{"op": "replace", "path": "/activeListings", "value": active_listings}]
        ))

    if result.get("outcome") == "error":
        log.error("Harness error for run %s: %s", run_id, result.get("message"))
        return

    if result.get("outcome") == "finished":
        if (
            underwriting_retries_left > 0
            and not comparison
            and not result.get("code_interpreter_completed")
            and _looks_like_unverified_underwriting(result.get("full_text", ""))
        ):
            log.warning(
                "Run %s answered an underwriting-style request without calling "
                "code-interpreter at all -- forcing one corrective retry.", run_id,
            )
            correction = (
                "Your last response gave cap rate / DSCR / cash-on-cash figures without "
                "calling any tool at all. That is not permitted. Using the same "
                "properties and NOI figures you already have, call the code-interpreter "
                "tool to actually execute the underwriting calculation and print its "
                "result. Do not repeat the same figures as prose again."
            )
            next_stream = harness_client.invoke(
                harness_arn, session_id, actor["sub"],
                messages=[{"role": "user", "content": [{"text": correction}]}],
            )
            yield from _drain_and_resolve(
                harness_arn, session_id, thread_id, actor, run_id, next_stream,
                emit_run_started=False, underwriting_retries_left=underwriting_retries_left - 1,
            )
            return
        yield _encoder.encode(RunFinishedEvent(thread_id=thread_id, run_id=run_id, outcome=RunFinishedSuccessOutcome()))
        return

    if result.get("outcome") != "pending_tools":
        return

    pending = result["pending"]
    auto_results = []
    human_needed = []
    for p in pending:
        if p["name"] == "get_legacy_credentials":
            cred = confirmation.resolve_legacy_credentials(actor["username"])
            auto_results.append({"toolUseId": p["toolUseId"], "result": cred, "status": "success"})

        else:
            human_needed.append(p)

    if human_needed and auto_results:
        # Rare (model batched an auto-resolvable call with a human-needed
        # one in parallel) -- resolve what we can now and let the model
        # re-request the human one on its own in the next turn, rather
        # than trying to interrupt and auto-resolve in the same breath.
        pass

    if auto_results:
        next_stream = harness_client.resume_with_tool_results(harness_arn, session_id, actor["sub"], auto_results)
        yield from _drain_and_resolve(
            harness_arn, session_id, thread_id, actor, run_id, next_stream,
            emit_run_started=False, underwriting_retries_left=underwriting_retries_left,
        )
        return

    if human_needed:
        p = human_needed[0]  # confirm_listing_change is instructed to run alone
        _paused_runs[run_id] = {
            "harness_arn": harness_arn,
            "session_id": session_id,
            "actor": actor,
            "pending_tool_use_id": p["toolUseId"],
            "listing_id": p["input"].get("listingId"),
            "old_price": p["input"].get("oldPrice"),
            "new_price": p["input"].get("newPrice"),
        }
        old_p, new_p = p["input"].get("oldPrice"), p["input"].get("newPrice")
        message = f"Change {p['input'].get('listingId')} from ${old_p:,.0f} to ${new_p:,.0f} — confirm?"
        interrupt = Interrupt(
            id=str(uuid.uuid4()),
            tool_call_id=p["toolUseId"],
            reason=p["name"],
            message=message,
            response_schema={"type": "object", "properties": {"approved": {"type": "boolean"}}},
            expires_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + config.APPROVAL_TOKEN_TTL_SECONDS)),
        )
        yield _encoder.encode(RunFinishedEvent(
            thread_id=thread_id, run_id=run_id,
            outcome=RunFinishedInterruptOutcome(interrupts=[interrupt]),
        ))


@app.post("/agui")
async def agui_endpoint(request: Request):
    actor = _require_actor(request)
    body = await request.json()

    harness_arn = config.GROUP_TO_HARNESS_ARN[actor["group"]]
    thread_id = body.get("thread_id") or str(uuid.uuid4())
    run_id = body.get("run_id") or str(uuid.uuid4())
    # runtimeSessionId must be >=33 chars; pad thread_id if needed.
    session_id = (thread_id + "-" * 40)[:40]

    resume = body.get("resume")

    def event_stream():
        _active_runs[run_id] = {"harness_arn": harness_arn, "session_id": session_id}
        try:
            if resume:
                paused = _paused_runs.pop(run_id, None)
                if paused is None:
                    yield _encoder.encode(RunFinishedEvent(thread_id=thread_id, run_id=run_id, outcome={"type": "error"}))
                    return
                entry = resume[0]
                if entry.get("status") == "resolved" and entry.get("payload", {}).get("approved"):
                    result = confirmation.mint_price_change_approval(
                        actor=paused["actor"]["username"],
                        listing_id=paused["listing_id"],
                        old_price=paused["old_price"],
                        new_price=paused["new_price"],
                        session_id=paused["session_id"],
                    )
                else:
                    result = confirmation.decline_price_change()
                next_stream = harness_client.resume_with_tool_results(
                    paused["harness_arn"], paused["session_id"], paused["actor"]["sub"],
                    [{"toolUseId": paused["pending_tool_use_id"], "result": result, "status": "success"}],
                )
                yield from _drain_and_resolve(
                    paused["harness_arn"], paused["session_id"], thread_id, paused["actor"], run_id, next_stream,
                    emit_run_started=False,
                )
                return

            messages_in = body.get("messages", [])
            user_text = ""
            for m in reversed(messages_in):
                if m.get("role") == "user":
                    content = m.get("content", "")
                    user_text = content if isinstance(content, str) else next(
                        (c.get("text", "") for c in content if isinstance(c, dict)), ""
                    )
                    break

            model_override = body.get("forwarded_props", {}).get("modelOverride")
            pricing.set_current_model((model_override or {}).get("bedrockModelConfig", {}).get("modelId"))

            raw_stream = harness_client.invoke(
                harness_arn, session_id, actor["sub"],
                messages=[{"role": "user", "content": [{"text": user_text}]}],
                model_override=model_override,
            )
            yield from _drain_and_resolve(harness_arn, session_id, thread_id, actor, run_id, raw_stream, emit_run_started=True)
        finally:
            _active_runs.pop(run_id, None)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/agui/stop")
async def agui_stop(request: Request):
    """Genuinely halts an in-flight run server-side via
    StopRuntimeSession -- not merely the client abandoning the SSE
    stream, which would leave the harness (and its billed compute)
    running unattended. Looks the run up in _active_runs, which is only
    populated while a stream from THIS run_id is actually in flight.
    """
    _require_actor(request)
    body = await request.json()
    run_id = body.get("run_id")
    active = _active_runs.get(run_id)
    if active is None:
        raise HTTPException(404, "No active run with that run_id (it may have already finished).")
    try:
        harness_client.stop_session(active["harness_arn"], active["session_id"])
    except Exception as e:
        log.warning("StopRuntimeSession failed for run %s: %s", run_id, e)
        raise HTTPException(502, f"Failed to stop the run: {e}")
    return {"stopped": True}


@app.get("/artifacts/{key:path}")
async def get_artifact(key: str, request: Request):
    _require_actor(request)
    import boto3
    s3 = boto3.client("s3", region_name=config.AWS_REGION)
    url = s3.generate_presigned_url(
        "get_object", Params={"Bucket": config.ARTIFACTS_BUCKET, "Key": key}, ExpiresIn=300
    )
    return {"url": url}


@app.get("/browser/live-view")
async def browser_live_view(request: Request):
    _require_actor(request)
    # TODO: AgentCore Browser live-view requires an active browser
    # session ID, which the harness manages internally and does not
    # currently surface to InvokeHarness callers. Wiring this through
    # needs either a Browser session started explicitly by the backend
    # (bypassing the harness's own auto-managed session) or a future
    # AgentCore API exposing the harness's in-flight session ID. Not
    # implemented in this reference build.
    raise HTTPException(501, "Browser live-view is not wired up in this reference build.")


@app.get("/oauth/legacy-callback")
async def legacy_oauth_callback(request: Request):
    """Where AgentCore Identity redirects the broker's own browser after
    they grant consent on the legacy portal's OAuth provider (Checkpoint
    4 / Legacy Portal OAuth) -- see confirmation.py's module docs for the
    full flow and the production caveat on how the user identity is
    bound here. This route is hit by a plain browser redirect, not an
    XHR from the SPA, so there is no Authorization header to check --
    `_require_actor` does not apply here.
    """
    session_id = request.query_params.get("session_id")
    if not session_id:
        return HTMLResponse("<p>Missing session_id.</p>", status_code=400)
    result = confirmation.complete_legacy_oauth(session_id)
    if "error" in result:
        return HTMLResponse(f"<p>{result['error']}</p>", status_code=400)
    return HTMLResponse(
        "<p>Authorization complete. You can close this tab and return to the chat.</p>"
    )


@app.get("/oauth/legacy-status")
async def legacy_oauth_status(session_uri: str):
    """Polled by the frontend while a Legacy Portal OAuth authorization
    link is outstanding, so the chat can auto-resume the moment the
    broker finishes in the new tab instead of requiring them to come
    back and type something first. Same no-auth-header situation as
    /oauth/legacy-callback above -- session_uri is an opaque, single-use
    PAR identifier the client already holds, not a secret to protect
    further."""
    return {"completed": confirmation.is_oauth_session_complete(session_uri)}


@app.get("/health")
async def health():
    return {"status": "ok"}


def _decimals_to_native(obj):
    from decimal import Decimal
    if isinstance(obj, list):
        return [_decimals_to_native(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _decimals_to_native(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    return obj


@app.get("/listings")
async def list_listings(request: Request):
    """Default grid population on login, straight from DynamoDB -- same
    table the market-data MCP's own search_listings reads, and the same
    privacy rule applied (NOI is never exposed here; it only exists in
    a listing's T-12 PDF, retrievable only via get_document_text).

    Investors see the whole market; brokers default to just their own
    listings (brokerId == their username) -- mirrors how a broker
    actually uses the product: managing what they own, not browsing
    the whole market like an investor does.
    """
    actor = _require_actor(request)
    import boto3
    dynamodb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
    table = dynamodb.Table(config.LISTINGS_TABLE)
    items = table.scan().get("Items", [])
    items = [{k: v for k, v in item.items() if k != "noi"} for item in items]
    if actor["group"] == "brokers":
        items = [item for item in items if item.get("brokerId") == actor["username"]]
    return {"listings": _decimals_to_native(items)}
