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
    RunStartedEvent,
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
      {"outcome": "finished", "usage": {...}, "code_interpreter_completed": bool, "full_text": str}
      {"outcome": "pending_tools", "pending": [{"toolUseId","name","input"}, ...], "usage": {...}, "code_interpreter_completed": bool}
      {"outcome": "error", "message": "..."}
    RUN_FINISHED framing is NOT emitted here for "finished" or
    "pending_tools" -- main.py needs to inspect the outcome first (e.g.
    to decide whether an underwriting answer that skipped code-interpreter
    entirely needs a corrective retry before the run is really done).
    """
    if emit_run_started:
        yield RunStartedEvent(thread_id=thread_id, run_id=run_id)

    text_message_id = None
    tool_call_ids_by_index = {}
    tool_names_by_id = {}  # toolUseId -> name, for resolving toolResult origin below
    current_message_tools = {}  # idx -> {"toolUseId", "name", "input_json"}
    total_usage = {"inputTokens": 0, "outputTokens": 0}
    stop_reason = None
    # Set only when a code-interpreter tool call actually COMPLETES (a
    # result comes back this stream) -- not merely started, since a
    # parallel tool-use batch can end the stream before an auto-executed
    # call finishes. This is the real signal submit_underwriting_result
    # -- and, for a turn that ends WITHOUT calling any tool at all, main.py's
    # own compliance check -- is checked against.
    code_interpreter_completed = False
    full_text = ""  # accumulated assistant text, so main.py can detect a
    # turn that answered a comparison request in plain prose without ever
    # touching code-interpreter or submit_underwriting_result at all --
    # the gate in main.py only catches a model that CALLS
    # submit_underwriting_result; it does nothing if the model skips
    # tool-calling entirely, which is a real, observed failure mode.

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
                tool_names_by_id[tool_use_id] = tool_name
                yield ToolCallStartEvent(tool_call_id=tool_use_id, tool_call_name=tool_name)

        elif "contentBlockDelta" in event:
            delta = event["contentBlockDelta"].get("delta", {})
            idx = event["contentBlockDelta"].get("contentBlockIndex")

            if "text" in delta:
                if text_message_id is None:
                    text_message_id = str(uuid.uuid4())
                    yield TextMessageStartEvent(message_id=text_message_id, role="assistant")
                full_text += delta["text"]
                yield TextMessageContentEvent(message_id=text_message_id, delta=delta["text"])

            elif idx in current_message_tools and "toolUse" in delta:
                piece = delta["toolUse"].get("input", "")
                current_message_tools[idx]["input_json"] += piece
                yield ToolCallArgsEvent(tool_call_id=current_message_tools[idx]["toolUseId"], delta=piece)

            elif "toolResult" in delta:
                tool_use_id = tool_call_ids_by_index.get(idx)
                # The model always calls this tool by AWS's fixed built-in
                # name "code_interpreter" (underscore) at the actual
                # Converse/tool_use layer -- regardless of the "code-interpreter"
                # (hyphen) name we gave it in harness.json's tools[] array,
                # which only matters for allowedTools matching (as "@code-interpreter").
                if tool_names_by_id.get(tool_use_id) == "code_interpreter":
                    code_interpreter_completed = True
                for block in delta["toolResult"]:
                    text = block.get("text", "")
                    yield ToolCallResultEvent(
                        message_id=str(uuid.uuid4()),
                        tool_call_id=tool_use_id or "",
                        content=text,
                        role="tool",
                    )

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
        yield {
            "outcome": "pending_tools",
            "pending": pending,
            "usage": total_usage,
            "code_interpreter_completed": code_interpreter_completed,
        }
        return

    yield {
        "outcome": "finished",
        "usage": total_usage,
        "code_interpreter_completed": code_interpreter_completed,
        "full_text": full_text,
    }
