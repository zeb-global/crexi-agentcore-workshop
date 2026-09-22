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
import time
import uuid

from ag_ui.core import Interrupt, RunFinishedEvent, RunFinishedInterruptOutcome
from ag_ui.encoder import EventEncoder
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

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
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_encoder = EventEncoder()

# run_id -> {"harness_arn", "session_id", "actor", "group", "pending_tool_use_id",
#            "listing_id", "old_price", "new_price"}
# Populated when a run pauses on confirm_listing_change; consumed on resume.
_paused_runs: dict[str, dict] = {}


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


def _drain_and_resolve(harness_arn: str, session_id: str, thread_id: str, actor: dict, run_id: str, harness_stream, *, emit_run_started: bool):
    """Runs translate_stream over one harness call, forwarding every
    AG-UI event as an SSE-ready dict. Auto-resolves get_legacy_credentials
    transparently (loops back into the harness with the credential and
    keeps draining); stops for real -- emitting a genuine Interrupt --
    on confirm_listing_change, which needs an actual human answer.
    """
    gen = translate_stream(harness_stream, thread_id=thread_id, run_id=run_id, emit_run_started=emit_run_started)
    result = None
    for item in gen:
        if isinstance(item, dict):
            result = item
            break
        yield _encoder.encode(item)

    if result is None or result.get("outcome") != "pending_tools":
        if result and result.get("outcome") == "error":
            log.error("Harness error for run %s: %s", run_id, result.get("message"))
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
        yield from _drain_and_resolve(harness_arn, session_id, thread_id, actor, run_id, next_stream, emit_run_started=False)
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

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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


@app.get("/health")
async def health():
    return {"status": "ok"}
