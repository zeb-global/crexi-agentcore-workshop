"""Thin InvokeHarness wrapper. Kept deliberately low-level -- real-time
translation to AG-UI events happens in agui_translate.py, which needs
to process the raw stream AS IT ARRIVES, not after full buffering.
"""
import boto3

import config

_client = boto3.client("bedrock-agentcore", region_name=config.AWS_REGION)


def invoke(
    harness_arn: str,
    session_id: str,
    actor_id: str,
    messages: list,
    *,
    model_override: dict | None = None,
    tools_override: list | None = None,
):
    """Calls InvokeHarness and returns the raw boto3 event stream
    (a lazy iterator -- nothing is fetched until you iterate it)."""
    kwargs = dict(
        harnessArn=harness_arn,
        runtimeSessionId=session_id,
        actorId=actor_id,
        messages=messages,
    )
    if model_override is not None:
        kwargs["model"] = model_override
    if tools_override is not None:
        kwargs["tools"] = tools_override
    response = _client.invoke_harness(**kwargs)
    return response["stream"]


def resume_with_tool_results(
    harness_arn: str,
    session_id: str,
    actor_id: str,
    results: list[dict],
    *,
    tools_override: list | None = None,
):
    """results: [{"toolUseId": ..., "result": <json-serializable>, "status": "success"|"error"}]"""
    import json

    content = [{
        "toolResult": {
            "toolUseId": r["toolUseId"],
            "content": [{"text": json.dumps(r["result"])}],
            "status": r.get("status", "success"),
        }
    } for r in results]

    return invoke(
        harness_arn, session_id, actor_id,
        messages=[{"role": "user", "content": content}],
        tools_override=tools_override,
    )


def stop_session(harness_arn: str, session_id: str) -> dict:
    """Stops an in-flight harness run server-side via StopRuntimeSession --
    a genuine AWS-side halt, not merely the client giving up on reading
    the stream.

    Confirmed live against the real deployed harness: StopRuntimeSession's
    agentRuntimeArn parameter must be the HARNESS's own ARN (the same one
    passed to invoke_harness above), not the separate, similarly-named
    'agentRuntimeArn' field agentcore status reports nested under each
    harness -- passing THAT one is explicitly rejected by AWS with
    "is managed by a harness and cannot be invoked directly. Use the
    StopRuntimeSession API with the relevant harness ID instead", which
    is exactly what this does. An earlier version of this code plumbed
    that separate nested ARN through as a distinct config value; it was
    unnecessary and wrong -- removed after this was verified live,
    3 consecutive runs.
    """
    return _client.stop_runtime_session(
        agentRuntimeArn=harness_arn,
        runtimeSessionId=session_id,
    )
