"""Regresyon testleri: LLM yanıt doğrulama (araç çağrısı) + mükerrer kullanıcı mesajı.

Bu testler iki GERÇEK hatayı korur:
1. `_validate_response`, asistan yalnızca araç çağrısı ürettiğinde (content alanı
   hiç gönderilmediğinde — ör. Groq gpt-oss-120b) geçerli yanıtı reddediyordu.
2. `chat()`, kullanıcı mesajını LLM'e iki kez gönderiyordu (hafızaya erken ekleme
   + get_history() + tekrar append).
"""
import asyncio

import ai_agent


def _msg(role, **kw):
    m = {"role": role}
    m.update(kw)
    return m


# --------------------------------------------------------------------------
# 1) _validate_response
# --------------------------------------------------------------------------

def test_validate_plain_content_response():
    data = {"choices": [{"message": _msg("assistant", content="merhaba")}]}
    assert ai_agent._validate_response(data) is True


def test_validate_tool_call_without_content():
    """Groq gpt-oss araç çağrısında 'content' alanını tamamen atlar."""
    data = {"choices": [{"message": {
        "role": "assistant",
        "tool_calls": [{"id": "c1", "type": "function",
                        "function": {"name": "calculate", "arguments": "{\"expression\":\"2+2\"}"}}],
    }}]}
    assert ai_agent._validate_response(data) is True


def test_validate_tool_call_with_content():
    data = {"choices": [{"message": {
        "role": "assistant", "content": None,
        "tool_calls": [{"id": "c1", "type": "function",
                        "function": {"name": "calculate", "arguments": "{}"}}],
    }}]}
    assert ai_agent._validate_response(data) is True


def test_validate_rejects_empty_message():
    data = {"choices": [{"message": _msg("assistant")}]}  # ne content ne tool_calls
    assert ai_agent._validate_response(data) is False


def test_validate_rejects_non_assistant_role():
    data = {"choices": [{"message": _msg("user", content="x")}]}
    assert ai_agent._validate_response(data) is False


def test_validate_rejects_bad_tool_call_type():
    data = {"choices": [{"message": {
        "role": "assistant",
        "tool_calls": [{"id": "c1", "type": "wrong",
                        "function": {"name": "f", "arguments": "{}"}}],
    }}]}
    assert ai_agent._validate_response(data) is False


def test_validate_rejects_missing_choices():
    assert ai_agent._validate_response({}) is False
    assert ai_agent._validate_response({"choices": []}) is False


# --------------------------------------------------------------------------
# 2) Mükerrer kullanıcı mesajı (kaynağa bağlı, LLM çağrısı mock'lanır)
# --------------------------------------------------------------------------

def test_user_message_sent_once_to_llm():
    agent = ai_agent.get_agent_v6()
    captured = {}
    orig = ai_agent.NexusAIAgent._call_llm

    async def fake_call(self, messages):
        captured["messages"] = [dict(m) for m in messages]
        return {"success": True,
                "data": {"choices": [{"message": _msg("assistant", content="tamam")}]}}

    ai_agent.NexusAIAgent._call_llm = fake_call
    try:
        asyncio.run(agent.chat("MUKERRER-KONTROL-MESAJI-XYZ"))
    finally:
        ai_agent.NexusAIAgent._call_llm = orig

    msgs = captured.get("messages", [])
    count = sum(
        1 for m in msgs
        if m.get("role") == "user" and "MUKERRER-KONTROL-MESAJI-XYZ" in str(m.get("content", ""))
    )
    assert count == 1, f"kullanıcı mesajı LLM'e {count} kez gönderildi (1 olmalı)"
