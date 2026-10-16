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
