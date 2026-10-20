"""Kimlik soruları: model/anahtar arızasından bağımsız doğru tanıtım."""
import asyncio

import ai_agent


def _bare_agent():
    agent = ai_agent.NexusAIAgent.__new__(ai_agent.NexusAIAgent)
    agent.memory = ai_agent.ConversationMemory(max_history=5)
    agent.llm_config = ai_agent.LLMConfig()
    agent.provider = "openrouter"
    return agent


def test_identity_chat_never_calls_llm(monkeypatch):
    agent = _bare_agent()
    calls = {"n": 0}

    async def fail(*args, **kwargs):
        calls["n"] += 1
        raise AssertionError("kimlik sorusunda LLM çağrılmamalı")

    monkeypatch.setattr(agent, "_call_llm", fail)
    result = asyncio.run(agent.chat("Sen hangi modelsin? Kısaca kendini tanıt."))

    assert result["success"] is True
    assert "NEXUS-CORE" in result["response"]
    assert "qwen2.5:3b" in result["response"]
    assert "Üzgünüm" not in result["response"]
    assert calls["n"] == 0


def test_identity_fallback_has_no_api_error_text():
    agent = _bare_agent()
    text = agent._answer_question("hangi model")

    assert "NEXUS-CORE" in text
    assert "NEXUS-CORE" in agent._answer_question("kendini tanıt")
    assert "Üzgünüm" not in text
    assert "LLM API" not in text
