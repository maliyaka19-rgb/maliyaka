"""Tests for per-agent tool allow-list enforcement (agent strengthening)."""
from ai_agent import NexusAIAgent
from tools_spec import TOOLS


def _bare_agent():
    """Build a NexusAIAgent without running the heavy __init__."""
    a = object.__new__(NexusAIAgent)
    a._active_tools = None
    return a


def test_tools_payload_all_when_unset():
    assert _bare_agent()._tools_payload() == TOOLS


def test_tools_payload_filters_by_agent_allowlist():
    a = _bare_agent()
    a._active_tools = ["read_file", "list_files"]
    names = {t["function"]["name"] for t in a._tools_payload()}
    assert names == {"read_file", "list_files"}


def test_tools_payload_unknown_names_fall_back_to_all():
    a = _bare_agent()
    a._active_tools = ["does_not_exist"]
    assert a._tools_payload() == TOOLS


# --- _safe_window: keeps requests within provider token limits (413 guard) ---

def test_safe_window_short_conversation_unchanged():
    a = _bare_agent()
    msgs = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "yo"},
    ]
    assert a._safe_window(msgs) == msgs


def test_safe_window_never_starts_on_orphan_tool_message():
    a = _bare_agent()
    msgs = [{"role": "system", "content": "s"}]
    for i in range(15):
        msgs.append({"role": "user", "content": f"q{i}"})
        msgs.append({"role": "assistant", "content": None,
                     "tool_calls": [{"id": f"c{i}", "type": "function",
                                     "function": {"name": "read_file", "arguments": "{}"}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": "x" * 100})
    out = a._safe_window(msgs, max_messages=8)
    assert out[0]["role"] == "system"
    assert out[1]["role"] == "user"          # valid boundary
    assert out[1].get("role") != "tool"
    assert len(out) < len(msgs)


def test_safe_window_enforces_character_cap():
    import json as _json
    a = _bare_agent()
    msgs = [{"role": "system", "content": "s"}]
    for i in range(10):
        msgs.append({"role": "user", "content": f"q{i}"})
        msgs.append({"role": "assistant", "content": "y" * 8000})
    out = a._safe_window(msgs, max_messages=50)
    total = sum(len(_json.dumps(m, ensure_ascii=False)) for m in out)
    assert total <= 37000          # cap (28k) + one oversized trailing turn
    assert len(out) < len(msgs)
