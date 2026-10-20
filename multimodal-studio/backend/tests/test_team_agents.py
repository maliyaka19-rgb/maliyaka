"""Tests for the official 22-agent roster and keyword fallback."""
import custom_agents as ca


def test_default_roster_is_exactly_official_22():
    """Ana Yönetici + Kodlama Yöneticisi + 20 uzman; başka ajan yok."""
    ids = [a["id"] for a in ca.DEFAULT_AGENTS]
    assert len(ids) == len(set(ids)) == 22
    expected = ["main-manager", "coding-manager"] + [
        s["id"] for s in ca.CODING_SPECIALISTS
    ]
    assert ids == expected
    assert not (set(ids) & ca.REMOVED_AGENT_IDS)


def test_official_agents_have_narrow_toolboxes():
    by_id = {a["id"]: a for a in ca.DEFAULT_AGENTS}
    assert "write_file" in by_id["frontend-pro"]["tools"]
    assert "execute_command" in by_id["coder"]["tools"]
    assert "execute_command" not in by_id["code-analyst"]["tools"]
    assert "write_file" not in by_id["code-analyst"]["tools"]
    for a in ca.DEFAULT_AGENTS:
        assert a["system_prompt"] and len(a["system_prompt"]) > 100
        assert a["tools"]  # no agent left tool-less


def test_keyword_select_routes_to_official_specialists():
    """Yedek anahtar kelime seçici yalnızca resmî kadrodaki ajanları döndürür."""
    assert ca.keyword_select_agent("python ile bir script yaz") == "coder"
    assert ca.keyword_select_agent("bana bir video üret, mp4 olsun") == "main-manager"
    assert ca.keyword_select_agent("görsel üret, illüstrasyon yap") == "main-manager"
    assert ca.keyword_select_agent("bu kodu denetle, hata var mı?") == "reviewer"
    assert ca.keyword_select_agent("ekip olarak hepsini yap, komple site") == "coding-manager"
    for message in ["python ile bir script yaz", "video üret", "görsel üret"]:
        assert ca.keyword_select_agent(message) in ca.OFFICIAL_AGENT_IDS
