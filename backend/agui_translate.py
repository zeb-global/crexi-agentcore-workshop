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


def _extract_underwriting_comparison(text: str):
    """Finds and parses the underwriting_comparison JSON object embedded
    anywhere in `text`.

    code-interpreter's toolResult does NOT arrive as clean JSON text --
    it is Bedrock's own str()/repr() of the tool's return value, e.g.
    "[{'type': 'text', 'text': '{\"type\":\"underwriting_comparison\",...}'}]"
    (single-quoted Python list/dict wrapper around a double-quoted JSON
    string). Feeding that whole string to json.loads() always fails, so
    this scans for a balanced {...} substring instead of assuming the
    payload is valid JSON on its own -- confirmed against the real
    deployed harness's actual stream, not assumed.
    """
    start = text.find('"underwriting_comparison"')
    if start == -1:
        return None
    # Walk backward from the match to the opening brace of the object
    # that contains "type":"underwriting_comparison", then forward with
    # brace-depth counting to find where that same object closes.
    obj_start = text.rfind("{", 0, start)
    if obj_start == -1:
        return None
    depth = 0
    for i in range(obj_start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[obj_start:i + 1]
                try:
                    parsed = json.loads(candidate)
                except (ValueError, json.JSONDecodeError):
                    return None
                if isinstance(parsed, dict) and parsed.get("type") == "underwriting_comparison" and "properties" in parsed:
                    return parsed
                return None
    return None


# Gateway tool names (after the "<target>___" prefix is stripped) whose
# result contains listing-shaped data the browse grid should mirror live
# -- see main.py's _active_listings state and the STATE_DELTA this module
# emits under "/activeListings" whenever one of these completes.
_LISTINGS_TOOL_SUFFIXES = ("search_listings", "get_listing")


def _listing_tool_suffix(full_tool_name: str) -> str | None:
    for suffix in _LISTINGS_TOOL_SUFFIXES:
        if full_tool_name == suffix or full_tool_name.endswith("___" + suffix):
            return suffix
    return None


def _extract_listings(text: str, tool_suffix: str):
    """Parses a search_listings/get_listing toolResult into a plain list
    of listing dicts, regardless of which of the two shapes it is:
      search_listings -> {"listings": [ {...}, ... ]}
      get_listing      -> {...}  (a single listing) or {"error": ...}
    Tries a direct json.loads() first (the real, observed shape for
    these two tools); falls back to the same brace-scan
    _extract_underwriting_comparison() uses, in case Gateway ever
    wraps this result the way it wraps code-interpreter's.
    """
    try:
        parsed = json.loads(text)
    except (ValueError, json.JSONDecodeError):
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        parsed = None
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[start:i + 1])
                    except (ValueError, json.JSONDecodeError):
                        return None
                    break
        if parsed is None:
            return None

    if not isinstance(parsed, dict):
        return None
    if tool_suffix == "search_listings":
        listings = parsed.get("listings")
        return listings if isinstance(listings, list) else None
    # get_listing: a single listing dict, unless it errored
    if "error" in parsed:
        return None
    return [parsed] if "listingId" in parsed else None


def translate_stream(harness_stream, thread_id: str, run_id: str, *, emit_run_started: bool = True):
    """Generator: yields AG-UI BaseEvent instances as the harness stream
    arrives. The LAST item yielded is always a plain dict:
      {"outcome": "finished", "usage": {...}, "code_interpreter_completed": bool, "full_text": str, "underwriting_comparison": dict | None}
      {"outcome": "pending_tools", "pending": [{"toolUseId","name","input"}, ...], "usage": {...}, "code_interpreter_completed": bool, "underwriting_comparison": dict | None}
      {"outcome": "error", "message": "..."}
    RUN_FINISHED framing is NOT emitted here for "finished" or
    "pending_tools" -- main.py needs to inspect the outcome first (e.g.
    to decide whether an underwriting answer that skipped code-interpreter
    entirely needs a corrective retry before the run is really done).
    """
    if emit_run_started:
        yield RunStartedEvent(thread_id=thread_id, run_id=run_id)

    text_message_id = None
    tool_names_by_id = {}  # toolUseId -> name, for resolving toolResult origin below
    current_message_tools = {}  # idx -> {"toolUseId", "name", "input_json"}
    # Content-block indices are per-message and do NOT line up between an
    # assistant message's tool_use blocks and the harness's OWN toolResult
    # message that follows -- confirmed live: a tool_use message with a
    # leading text block puts its first tool call at idx=1, but the
    # following toolResult message (no text block of its own) reports
    # that same call's result at idx=0. The two message's indices are
    # unrelated; what IS reliable is that results come back in the same
    # order the calls were issued. So each time a tool_use message ends,
    # its calls are snapshotted here in issue order; the next toolResult
    # message's local index is used purely as a position into this list,
    # never as a shared key with the tool_use message it came from.
    pending_tool_order = []  # [toolUseId, ...] in the order they were issued
    result_index_to_position = {}  # contentBlockIndex (within the CURRENT
    # result message) -> position in pending_tool_order. Assigned once,
    # the FIRST time that index is seen -- toolResult content for one
    # tool call arrives as MULTIPLE contentBlockDelta events sharing the
    # same contentBlockIndex (confirmed live: a search_listings result
    # split cleanly into two delta events, both idx=0), so position
    # must be keyed by index, not incremented per delta event.
    result_text_by_position = {}  # position -> accumulated text so far,
    # for the same reason argument JSON is accumulated into input_json
    # below: a single chunk alone is not valid JSON on its own.
    total_usage = {"inputTokens": 0, "outputTokens": 0}
    stop_reason = None
    # Set only when a code-interpreter tool call actually COMPLETES (a
    # result comes back this stream) -- not merely started, since a
    # parallel tool-use batch can end the stream before an auto-executed
    # call finishes. This is the signal main.py's own compliance check
    # (a turn that answered in prose without calling any tool at all) is
    # checked against.
    code_interpreter_completed = False
    underwriting_comparison = None  # parsed JSON pulled straight from
    # code-interpreter's own stdout, the moment its result streams back --
    # no second tool call needed to hand the same JSON back to us.
    active_listings_by_id = {}  # listingId -> listing dict, accumulated
    # across EVERY search_listings/get_listing call this stream saw, not
    # just the last one -- a returning user with N specific properties in
    # mind very often triggers N separate get_listing calls (confirmed
    # live: 4 separate get_listing calls for 4 named properties), and
    # keeping only the last one would show just 1 property on the grid
    # instead of all 4. A search_listings call REPLACES the accumulated
    # set instead of merging into it, since it already returns a complete,
    # self-contained result set of its own.
    active_listings_seen = False  # True the instant ANY listings tool
    # call landed this stream -- distinguishes "saw listings tools but
    # they returned zero results" from "no listings tool was called at
    # all", which main.py needs to know whether to touch the grid.
    full_text = ""  # accumulated assistant text, so main.py can detect a
    # turn that answered a comparison request in plain prose without ever
    # touching code-interpreter at all -- this catches a model that skips
    # tool-calling entirely, which is a real, observed failure mode.

    for event in harness_stream:
        if "messageStart" in event:
            if event["messageStart"].get("role") == "user":
                # A user-role message from the harness carries toolResult
                # blocks for the tool_use blocks the assistant JUST issued.
                # Reset the per-message index->position map and text
                # accumulator, but do NOT touch pending_tool_order, which
                # is what we resolve against.
                result_index_to_position = {}
                result_text_by_position = {}
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
                # Resolve by POSITION, keyed by contentBlockIndex WITHIN
                # THIS result message, against pending_tool_order (the
                # previous tool_use message's calls, in issue order) --
                # NOT by treating contentBlockIndex as a shared key with
                # the tool_use message it came from, which does not
                # correlate across the two messages (see the note above
                # pending_tool_order's declaration). The index IS stable
                # for repeated deltas of the SAME result, so it is
                # assigned a position only the first time it's seen.
                if idx not in result_index_to_position:
                    result_index_to_position[idx] = len(result_index_to_position)
                position = result_index_to_position[idx]
                tool_use_id = (
                    pending_tool_order[position]
                    if position < len(pending_tool_order)
                    else None
                )
                # The model always calls this tool by AWS's fixed built-in
                # name "code_interpreter" (underscore) at the actual
                # Converse/tool_use layer -- regardless of the "code-interpreter"
                # (hyphen) name we gave it in harness.json's tools[] array,
                # which only matters for allowedTools matching (as "@code-interpreter").
                is_code_interpreter = tool_names_by_id.get(tool_use_id) == "code_interpreter"
                if is_code_interpreter:
                    code_interpreter_completed = True
                listing_suffix = _listing_tool_suffix(tool_names_by_id.get(tool_use_id) or "")
                for block in delta["toolResult"]:
                    text = block.get("text", "")
                    if is_code_interpreter or listing_suffix:
                        accumulated = result_text_by_position.get(position, "") + text
                        result_text_by_position[position] = accumulated
                        if is_code_interpreter:
                            parsed = _extract_underwriting_comparison(accumulated)
                            if parsed is not None:
                                underwriting_comparison = parsed
                        elif listing_suffix:
                            parsed_listings = _extract_listings(accumulated, listing_suffix)
                            if parsed_listings is not None:
                                active_listings_seen = True
                                if listing_suffix == "search_listings":
                                    # A complete result set on its own --
                                    # replaces whatever get_listing calls
                                    # accumulated earlier in this stream,
                                    # rather than merging with them.
                                    active_listings_by_id = {
                                        l["listingId"]: l for l in parsed_listings if l.get("listingId")
                                    }
                                else:
                                    for l in parsed_listings:
                                        if l.get("listingId"):
                                            active_listings_by_id[l["listingId"]] = l
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
            if stop_reason == "tool_use" and current_message_tools:
                # Snapshot this message's tool calls in ISSUE ORDER (i.e.
                # by ascending contentBlockIndex within this one message,
                # which IS reliable) so the next toolResult message's
                # positions can be resolved against them.
                pending_tool_order = [
                    current_message_tools[i]["toolUseId"] for i in sorted(current_message_tools)
                ]

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
            "underwriting_comparison": underwriting_comparison,
            "active_listings": list(active_listings_by_id.values()) if active_listings_seen else None,
        }
        return

    yield {
        "outcome": "finished",
        "usage": total_usage,
        "code_interpreter_completed": code_interpreter_completed,
        "full_text": full_text,
        "underwriting_comparison": underwriting_comparison,
        "active_listings": list(active_listings_by_id.values()) if active_listings_seen else None,
    }
