"""Manual test harness for the inline-function pause/resume protocol,
following AWS's documented pattern exactly (capture toolUseId + input at
the handoff boundary, then resume with a matching toolResult on the SAME
runtimeSessionId). This is also the reference logic backend/confirmation.py
implements for real once the FastAPI server exists.

Usage:
    python scripts/test_inline_function_roundtrip.py
"""
import json
import sys
import uuid

import boto3

REGION = "us-west-2"
HARNESS_ARN = "arn:aws:bedrock-agentcore:us-west-2:347272280436:harness/crexiWorkshopV2_brokerAgent-Zh8tLOhxvX"

client = boto3.client("bedrock-agentcore", region_name=REGION)


def stream_and_capture(session_id, messages, tools=None):
    """Sends one InvokeHarness call, prints assistant text as it streams,
    and returns (last_stop_reason, pending_tool_use) where pending_tool_use
    is {"name", "toolUseId", "input"} if the harness handed off a tool
    call at the end of the stream, else None.
    """
    kwargs = dict(harnessArn=HARNESS_ARN, runtimeSessionId=session_id, messages=messages)
    if tools is not None:
        kwargs["tools"] = tools
    response = client.invoke_harness(**kwargs)

    last_stop_reason = None
    tool_use_id = None
    tool_name = None
    tool_block_index = None
    tool_input_json = ""

    for event in response["stream"]:
        if "contentBlockStart" in event:
            start = event["contentBlockStart"].get("start", {})
            if "toolUse" in start:
                tool_use_id = start["toolUse"]["toolUseId"]
                tool_name = start["toolUse"].get("name")
                tool_block_index = event["contentBlockStart"]["contentBlockIndex"]
        if "contentBlockDelta" in event:
            delta = event["contentBlockDelta"].get("delta", {})
            if "text" in delta:
                print(delta["text"], end="", flush=True)
            if (
                event["contentBlockDelta"].get("contentBlockIndex") == tool_block_index
                and "toolUse" in delta
            ):
                tool_input_json += delta["toolUse"].get("input", "")
        if "messageStop" in event:
            last_stop_reason = event["messageStop"].get("stopReason")
        if "runtimeClientError" in event:
            print("\n[runtimeClientError]", event["runtimeClientError"])

    print()  # newline after streamed text

    pending = None
    if last_stop_reason == "tool_use" and tool_use_id:
        pending = {
            "name": tool_name,
            "toolUseId": tool_use_id,
            "input": json.loads(tool_input_json) if tool_input_json else {},
        }
    return last_stop_reason, pending


def send_tool_result(session_id, tool_use_id, result_dict, tools=None, status="success"):
    messages = [{
        "role": "user",
        "content": [{
            "toolResult": {
                "toolUseId": tool_use_id,
                "content": [{"text": json.dumps(result_dict)}],
                "status": status,
            }
        }],
    }]
    return stream_and_capture(session_id, messages, tools=tools)


if __name__ == "__main__":
    session_id = str(uuid.uuid4()) + "-broker-test"
    prompt = sys.argv[1] if len(sys.argv) > 1 else "What is the login for the legacy deal desk?"
    print(f"--- session {session_id} ---")
    print(f"--- prompt: {prompt} ---\n")
    stop_reason, pending = stream_and_capture(
        session_id, [{"role": "user", "content": [{"text": prompt}]}]
    )
    print(f"\n--- stopReason={stop_reason} pending={pending} ---")
