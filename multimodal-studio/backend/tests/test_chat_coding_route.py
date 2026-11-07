"""Sohbet üzerinden kodlama devri (D-024'ten execute'a geçiş).

SoHBET ucesinden gelen istekte ``mode``/``confirm`` alanlari artik istemciden
gelir; varsayilan 'plan' modu eski davranisi korur (dosya degistirmez).
``mode="execute"`` + ``confirm=True`` ile uzman adimlari GERCEK dosya yazar ve
``files_changed`` kaniti yanita doner.

Ayrıca: ``coding-manager``'a DOGRUDAN gelen istek de kodlama zincirine
gitmeli (eski akista sadece main-manager devrediyordu; coding-manager bos
sohbete dusuyordu).
"""

import asyncio

from coding_manager import CodingTaskManager, TaskType, classify_task

import ai_agent_routes as routes


def _fake_run_factory(seen: dict, files=None):
    async def fake_run(self, message, mode="plan", confirm=False,
                       conversation_id=None, via_main_manager=True, **kw):
        seen.update(mode=mode, confirm=confirm, via_main_manager=via_main_manager)
        return {
            "success": True,
            "task_id": "t-1",
            "status": "tamamlandi",
            "mode": mode,
            "final_answer": "Görev tamamlandı.",
            "report": {},
            "files_changed": list(files or []),
        }
    return fake_run


class _Raw:
    """chat_endpoint'ın doğrudan test çağrıları için başlık sarıcı."""

    def __init__(self, headers=None):
        self.headers = dict(headers or {})


def _chat(message: str, **kwargs):
    req = routes.ChatRequest(message=message, **kwargs)
    return asyncio.run(routes.chat_endpoint(req, raw_request=_Raw(), current_user=None))


def test_chat_request_defaults_to_plan_mode():
    """Eski istemciler (mode gondermeyenler) plan modunda kalir."""
    req = routes.ChatRequest(message="merhaba")
    assert req.mode == "plan"
    assert req.confirm is False


def test_classifier_sees_real_coding_task():
    """Kodlama görevi siniflandirmasi execute akisini tetikleyebilmeli."""
    assert classify_task("login formuna beni hatirla checkbox'i ekle") != TaskType.GENERAL


def test_execute_mode_is_passed_through_and_files_reported(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(CodingTaskManager, "run",
                        _fake_run_factory(seen, files=["src/app.py"]))

    resp = _chat("login formuna beni hatirla checkbox'i ekle",
                 agent_id="main-manager", mode="execute", confirm=True)

    assert seen["mode"] == "execute"
    assert seen["confirm"] is True
    assert seen["via_main_manager"] is True       # Ana Yönetici üzerinden devredildi
    assert resp.success is True
    assert resp.files_changed == ["src/app.py"]   # dosya kaniti yanitta
    assert resp.coding["mode"] == "execute"


def test_direct_coding_manager_request_runs_chain(monkeypatch):
    """coding-manager'a doğrudan istek zincire gitmeli (boş sohbete değil)."""
    seen: dict = {}
    monkeypatch.setattr(CodingTaskManager, "run", _fake_run_factory(seen))

    resp = _chat("merhaba diyen bir fonksiyon yaz", agent_id="coding-manager",
                 mode="execute", confirm=True)

    assert seen["mode"] == "execute"
    assert seen["via_main_manager"] is False     # zaten Kodlama Yöneticisi
    assert resp.success is True


def test_default_plan_mode_requests_no_writing(monkeypatch):
    """Varsayılan istek (mode gondermeyen istemci) dosya yazdırmaz."""
    seen: dict = {}
    monkeypatch.setattr(CodingTaskManager, "run", _fake_run_factory(seen))

    resp = _chat("yeni bir modul olustur", agent_id="main-manager")

    assert seen["mode"] == "plan"
    assert seen["confirm"] is False
    assert resp.files_changed == []
