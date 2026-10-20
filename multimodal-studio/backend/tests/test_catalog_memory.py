"""
Model Catalog & Memory Tests
============================
Tests MODEL_CATALOG integrity and ConversationMemory behavior.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model_routes import MODEL_CATALOG
from memory import Message, Conversation, ConversationMemory, LearningMemory


# ============================================================
# MODEL CATALOG
# ============================================================

class TestModelCatalog:
    def test_catalog_has_only_openrouter(self):
        assert set(MODEL_CATALOG) == {"openrouter"}

    def test_removed_providers_are_absent(self):
        for p in ("groq", "openai", "anthropic", "gemini", "together"):
            assert p not in MODEL_CATALOG, f"Removed provider still present: {p}"

    def test_openrouter_has_deepseek_qwen_kimi(self):
        ids = [m["id"] for m in MODEL_CATALOG["openrouter"]["models"]]
        assert any("deepseek" in i for i in ids), "No DeepSeek models"
        assert any("qwen" in i for i in ids), "No Qwen models"
        assert any("kimi" in i for i in ids), "No Kimi models"

    def test_openrouter_model_count(self):
        assert len(MODEL_CATALOG["openrouter"]["models"]) == 17

    def test_all_models_have_required_fields(self):
        for pid, pinfo in MODEL_CATALOG.items():
            for m in pinfo["models"]:
                assert "id" in m, f"{pid}: model missing id"
                assert "name" in m, f"{pid}: model missing name"

    def test_provider_structure(self):
        for pid, pinfo in MODEL_CATALOG.items():
            assert "name" in pinfo
            assert "base_url" in pinfo
            assert "env_key" in pinfo
            assert "models" in pinfo
            assert len(pinfo["models"]) > 0


# ============================================================
# CONVERSATION MEMORY
# ============================================================

class TestConversationMemory:
    def test_add_and_get(self):
        mem = ConversationMemory(max_history=10)
        mem.get_or_create("test-conv-1")
        mem.add_message("test-conv-1", Message(role="user", content="Merhaba"))
        mem.add_message("test-conv-1", Message(role="assistant", content="Selam!"))
        history = mem.get_history("test-conv-1")
        assert len(history) == 2
        assert history[0]["content"] == "Merhaba"

    def test_max_history_limit(self):
        mem = ConversationMemory(max_history=3)
        mem.get_or_create("lim-conv")
        for i in range(10):
            mem.add_message("lim-conv", Message(role="user", content=f"msg {i}"))
        history = mem.get_history("lim-conv", include_system=False)
        assert len(history) <= 3
        assert history[-1]["content"] == "msg 9"

    def test_get_or_create_returns_same(self):
        mem = ConversationMemory(max_history=10)
        c1 = mem.get_or_create("same-id")
        c2 = mem.get_or_create("same-id")
        assert c1 is c2

    def test_history_roles(self):
        mem = ConversationMemory(max_history=10)
        mem.get_or_create("roles-conv")
        mem.add_message("roles-conv", Message(role="user", content="soru"))
        mem.add_message("roles-conv", Message(role="assistant", content="cevap"))
        history = mem.get_history("roles-conv")
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"


# ============================================================
# LEARNING MEMORY
# ============================================================

class TestLearningMemory:
    def test_record_and_retrieve(self):
        lm = LearningMemory()
        lm.record(
            query="Python async nedir?",
            tools_used=["web_search"],
            success=True,
            response_summary="Async/await açıklaması"
        )
        assert len(lm.lessons) > 0

    def test_similar_retrieval(self):
        lm = LearningMemory()
        lm.record(query="Python async nedir?", tools_used=["web_search"],
                  success=True, response_summary="açıklama")
        similar = lm.get_similar("Python async")
        assert isinstance(similar, list)

    def test_lessons_capped(self):
        lm = LearningMemory()
        for i in range(200):
            lm.record(query=f"q{i}", tools_used=["t"], success=True, response_summary="r")
        assert len(lm.lessons) <= 500
