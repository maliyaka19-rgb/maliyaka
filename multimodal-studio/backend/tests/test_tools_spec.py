"""
Tools Spec Tests
================
Validates the TOOLS LLM tool definitions structure.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools_spec import TOOLS


class TestToolsSpec:
    def test_tools_is_list(self):
        assert isinstance(TOOLS, list)

    def test_tools_count(self):
        assert len(TOOLS) >= 15, f"Expected 15+ tools, got {len(TOOLS)}"

    def test_all_tools_have_function_schema(self):
        for t in TOOLS:
            assert t["type"] == "function"
            assert "function" in t
            fn = t["function"]
            assert "name" in fn
            assert "description" in fn
            assert "parameters" in fn

    def test_tool_names_unique(self):
        names = [t["function"]["name"] for t in TOOLS]
        assert len(names) == len(set(names)), "Duplicate tool names found"

    def test_core_tools_present(self):
        names = [t["function"]["name"] for t in TOOLS]
        for required in ("web_search", "calculate", "generate_code"):
            assert required in names, f"Missing core tool: {required}"

    def test_rag_tools_present(self):
        names = [t["function"]["name"] for t in TOOLS]
        for required in ("rag_add_document", "rag_search", "rag_list_documents"):
            assert required in names, f"Missing RAG tool: {required}"

    def test_parameters_schema_format(self):
        for t in TOOLS:
            params = t["function"]["parameters"]
            assert params.get("type") == "object"
            assert "properties" in params
