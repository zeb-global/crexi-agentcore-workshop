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
