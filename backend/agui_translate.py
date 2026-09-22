"""Translates a live InvokeHarness event stream into real AG-UI protocol
events, one at a time, as they arrive -- this is the actual SSE path,
so it must not buffer the whole turn before emitting anything.

Deliberately mechanical: this module only translates and reports which
tool-use blocks are left pending when the stream ends. Whether a pending
tool is silently auto-resolved (get_legacy_credentials) or surfaced to
the human as a real AG-UI Interrupt (confirm_listing_change) is a
POLICY decision that belongs to main.py, not here.

Mechanics proven live against the real deployed harnesses in
scripts/broker_e2e_test.py:
  - Harness-executed tools (Gateway/Browser/Code Interpreter) resolve
    and continue WITHIN the same stream: messageStop(tool_use) is
    immediately followed by a new messageStart(role=user) carrying the
    toolResult, then the assistant continues.
  - content-block indices are per-message, not global.
  - The only case where the stream truly ENDS on stopReason=tool_use is
    an inline function -- nothing else is left for the harness to
    auto-resolve.
"""
import json
import uuid

from ag_ui.core import (
    CustomEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunFinishedSuccessOutcome,
    RunStartedEvent,
    StateDeltaEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)

import pricing


def translate_stream(harness_stream, thread_id: str, run_id: str, *, emit_run_started: bool = True):
    """Generator: yields AG-UI BaseEvent instances as the harness stream
    arrives. The LAST item yielded is always a plain dict:
      {"outcome": "finished", "usage": {...}}
      {"outcome": "pending_tools", "pending": [{"toolUseId","name","input"}, ...], "usage": {...}}
      {"outcome": "error", "message": "..."}
    RUN_FINISHED/RUN_STARTED framing for the "finished"/"error" cases is
    emitted here; for "pending_tools" the caller (main.py) decides what
    AG-UI framing to send once it knows which tools are auto-resolvable.
    """
    if emit_run_started:
        yield RunStartedEvent(thread_id=thread_id, run_id=run_id)

    text_message_id = None
    tool_call_ids_by_index = {}
    current_message_tools = {}  # idx -> {"toolUseId", "name", "input_json"}
    total_usage = {"inputTokens": 0, "outputTokens": 0}
    stop_reason = None

    for event in harness_stream:
        if "messageStart" in event:
            current_message_tools = {}

        elif "contentBlockStart" in event:
            start = event["contentBlockStart"].get("start", {})
            idx = event["contentBlockStart"]["contentBlockIndex"]
            if "toolUse" in start:
                tool_use_id = start["toolUse"]["toolUseId"]
                tool_name = start["toolUse"].get("name", "")
                current_message_tools[idx] = {
                    "toolUseId": tool_use_id, "name": tool_name, "input_json": ""
                }
                tool_call_ids_by_index[idx] = tool_use_id
                yield ToolCallStartEvent(tool_call_id=tool_use_id, tool_call_name=tool_name)

        elif "contentBlockDelta" in event:
            delta = event["contentBlockDelta"].get("delta", {})
            idx = event["contentBlockDelta"].get("contentBlockIndex")

            if "text" in delta:
                if text_message_id is None:
                    text_message_id = str(uuid.uuid4())
                    yield TextMessageStartEvent(message_id=text_message_id, role="assistant")
                yield TextMessageContentEvent(message_id=text_message_id, delta=delta["text"])

            elif idx in current_message_tools and "toolUse" in delta:
                piece = delta["toolUse"].get("input", "")
                current_message_tools[idx]["input_json"] += piece
                yield ToolCallArgsEvent(tool_call_id=current_message_tools[idx]["toolUseId"], delta=piece)

            elif "toolResult" in delta:
                tool_use_id = tool_call_ids_by_index.get(idx)
                for block in delta["toolResult"]:
                    text = block.get("text", "")
                    yield ToolCallResultEvent(
                        message_id=str(uuid.uuid4()),
                        tool_call_id=tool_use_id or "",
                        content=text,
                        role="tool",
                    )
                    # The investor underwriting contract: the tool result
                    # text IS the structured comparison payload when it
                    # parses as JSON with type=underwriting_comparison.
                    try:
                        parsed = json.loads(text)
                        if isinstance(parsed, dict) and parsed.get("type") == "underwriting_comparison":
                            yield StateDeltaEvent(delta=[{"op": "replace", "path": "/comparison", "value": parsed}])
                    except (json.JSONDecodeError, TypeError):
                        pass

        elif "contentBlockStop" in event:
            idx = event["contentBlockStop"]["contentBlockIndex"]
            if idx in current_message_tools:
                yield ToolCallEndEvent(tool_call_id=current_message_tools[idx]["toolUseId"])
            elif text_message_id is not None:
                yield TextMessageEndEvent(message_id=text_message_id)
                text_message_id = None

        elif "messageStop" in event:
            stop_reason = event["messageStop"].get("stopReason")

        elif "metadata" in event:
            usage = event["metadata"].get("usage", {})
            total_usage["inputTokens"] += usage.get("inputTokens", 0)
            total_usage["outputTokens"] += usage.get("outputTokens", 0)
            yield CustomEvent(name="cost_delta", value=pricing.usage_to_cost(usage))

        elif "runtimeClientError" in event:
            message = event["runtimeClientError"].get("message", "Unknown harness error")
            yield RunErrorEvent(message=message)
            yield {"outcome": "error", "message": message}
            return

    if text_message_id is not None:
        yield TextMessageEndEvent(message_id=text_message_id)

    if stop_reason == "tool_use" and current_message_tools:
        pending = list(current_message_tools.values())
        for p in pending:
            p["input"] = json.loads(p["input_json"]) if p["input_json"] else {}
        yield {"outcome": "pending_tools", "pending": pending, "usage": total_usage}
        return

    yield RunFinishedEvent(thread_id=thread_id, run_id=run_id, outcome=RunFinishedSuccessOutcome())
    yield {"outcome": "finished", "usage": total_usage}
