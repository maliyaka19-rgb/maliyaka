"""
Öğrenme Ajanı — denetimli içgörü motoru testleri.

Test edilen davranışlar:
  * görev geçmişinden deterministik içgörü çıkarımı (boş, oran, kanıtsız, retry,
    başarısız rol, tekrarlayan kalan risk)
  * kanıt eşiği: tek görevden yargı üretilmez
  * kalıcılık + tekrar analizde DEDUP (çift kayıt yok)
  * insan kararının (onay/red) yeniden analizde KORUNMASI
  * "onay"ın otomatik uygulama OLMAMASI (applied her zaman False)
  * GÜVENLİK SINIRI: modül yalnızca coding_insights.json yazar
  * HTTP rotaları
  * search_learning aracının GET kullanması (405 regresyonu)
"""
import asyncio
import builtins
import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import coding_insights as ci
import coding_manager as cm
import coding_routes as cr


# ---------------------------------------------------------------- yardımcı

def _task(task_id, task_type="bugfix", status="tamamlandi", retries=0,
          verification=None, messages=None, remaining_issues=None):
    return {
        "task_id": task_id,
        "task_type": task_type,
        "status": status,
        "retries": retries,
        "verification": verification if verification is not None
        else {"ran": True, "passed": True, "exit_code": 0},
        "messages": messages or [],
        "remaining_issues": remaining_issues or [],
    }


def _kinds(insights):
    return {i["kind"] for i in insights}


@pytest.fixture(autouse=True)
def _isolated_files(monkeypatch, tmp_path):
    monkeypatch.setattr(ci, "INSIGHTS_FILE", str(tmp_path / "coding_insights.json"))


# ---------------------------------------------------------------- birim: analiz

def test_empty_history_yields_info_insight():
    ins = ci.analyze_history([])
    assert len(ins) == 1
    assert ins[0]["kind"] == "veri_yok"
    assert ins[0]["severity"] == "bilgi"
    assert ins[0]["status"] == "oneri"
    assert ins[0]["applied"] is False


def test_high_failure_rate_produces_risk_insight():
    tasks = [_task("t1", "bugfix", "basarisiz"), _task("t2", "bugfix", "test_basarisiz")]
    ins = ci.analyze_history(tasks)
    assert "basarisizlik_orani" in _kinds(ins)
    rate = next(i for i in ins if i["kind"] == "basarisizlik_orani")
    assert rate["severity"] == "risk"
    assert rate["evidence"]["oran_yuzde"] == 100.0
    assert set(rate["evidence"]["task_ids"]) == {"t1", "t2"}


def test_single_task_is_not_enough_evidence():
    ins = ci.analyze_history([_task("t1", "bugfix", "basarisiz")])
    assert "basarisizlik_orani" not in _kinds(ins), "tek görevden oran yargısı çıkmamalı"


def test_unproven_completion_is_flagged():
    unproven = _task("t1", verification={"ran": False, "passed": None, "note": "komut yok"})
    ins = ci.analyze_history([unproven])
    flagged = [i for i in ins if i["kind"] == "kanitsiz_tamamlama"]
    assert flagged and flagged[0]["evidence"]["task_ids"] == ["t1"]

    # Gerçek doğrulama kanıtı (passed=True) varsa uyarı ÇIKMAZ
    assert "kanitsiz_tamamlama" not in _kinds(ci.analyze_history([_task("t2")]))


def test_retry_usage_is_reported():
    ins = ci.analyze_history([_task("t1", retries=2)])
    retry = [i for i in ins if i["kind"] == "retry_yogunlugu"]
    assert retry and retry[0]["evidence"]["task_ids"] == ["t1"]


def test_repeatedly_failing_role_is_reported():
    tasks = [
        _task("t1", messages=[{"sender": "coder", "status": "basarisiz"}]),
        _task("t2", messages=[{"sender": "coder", "success": False}]),
    ]
    ins = ci.analyze_history(tasks)
    role = [i for i in ins if i["kind"] == "basarisiz_rol"]
    assert role and role[0]["evidence"]["rol"] == "coder"
    assert role[0]["evidence"]["sayi"] == 2


def test_single_failing_role_is_not_reported():
    ins = ci.analyze_history([_task("t1", messages=[{"sender": "coder", "status": "basarisiz"}])])
    assert "basarisiz_rol" not in _kinds(ins)


def test_recurring_remaining_risk_is_reported():
    tasks = [
        _task("t1", remaining_issues=["Engine timeout"]),
        _task("t2", remaining_issues=["  engine   TIMEOUT "]),
    ]
    ins = ci.analyze_history(tasks)
    risk = [i for i in ins if i["kind"] == "tekrarlayan_kalan_risk"]
    assert risk, "normalize edilmiş tekrar eden risk yakalanmalı"
    assert risk[0]["evidence"]["sayi"] == 2


# ---------------------------------------------------------------- kalıcılık/dedup

def test_generate_persists_and_dedups():
    tasks = [_task("t1", "bugfix", "basarisiz"), _task("t2", "bugfix", "test_basarisiz")]

    first = ci.generate_insights(tasks)
    assert first["created"] >= 1
    stored = ci.list_insights()
    assert stored, "öneriler kalıcı olmalı"

    second = ci.generate_insights(tasks)
    assert second["created"] == 0, "aynı kanıt tekrar öneri üretmemeli"
    assert len(ci.list_insights()) == len(stored)


def test_human_decision_survives_reanalysis():
    tasks = [_task("t1", "bugfix", "basarisiz"), _task("t2", "bugfix", "test_basarisiz")]
    ci.generate_insights(tasks)
    target = ci.list_insights()[0]

    updated = ci.set_status(target["insight_id"], "onaylandi", "incelendi")
    assert updated["status"] == "onaylandi"
    assert updated["applied"] is False, "onay otomatik uygulama DEĞİLDİR"

    ci.generate_insights(tasks)  # yeniden analiz kararı ezmemeli
    after = ci.get_insight(target["insight_id"])
    assert after["status"] == "onaylandi"
    assert after["decision_note"] == "incelendi"
    assert after["applied"] is False


def test_set_status_rejects_invalid_decision():
    ci.generate_insights([_task("t1", "bugfix", "basarisiz"), _task("t2", "bugfix", "test_basarisiz")])
    iid = ci.list_insights()[0]["insight_id"]
    with pytest.raises(ValueError):
        ci.set_status(iid, "uygulandi")  # böyle bir karar yok


def test_set_status_unknown_id_returns_none():
    assert ci.set_status("ins-yok", "onaylandi") is None


def test_module_writes_only_the_insights_file(monkeypatch, tmp_path):
    """GÜVENLİK SINIRI: kaynak kod/model/güvenlik dosyası YAZILMAMALI."""
    writes = []
    real_open = builtins.open

    def spy_open(file, mode="r", *args, **kwargs):
        if isinstance(mode, str) and any(c in mode for c in "wax+"):
            writes.append(os.path.abspath(str(file)))
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy_open)
    ci.generate_insights([_task("t1", "bugfix", "basarisiz"), _task("t2", "bugfix", "test_basarisiz")])
    cid = ci.list_insights()[0]["insight_id"]
    ci.set_status(cid, "onaylandi", "ok")

    expected = os.path.abspath(str(tmp_path / "coding_insights.json"))
    assert writes, "en az bir yazma bekleniyordu"
    assert all(w == expected for w in writes), f"beklenmeyen yazma: {writes}"


# ---------------------------------------------------------------- HTTP rotaları

def _client(monkeypatch, tmp_path):
    monkeypatch.setattr(cm, "TASKS_FILE", str(tmp_path / "coding_tasks.json"))
    app = FastAPI()
    app.include_router(cr.router)
    return TestClient(app)


def test_insight_routes_end_to_end(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    (tmp_path / "coding_tasks.json").write_text(
        json.dumps([_task("t1", "bugfix", "basarisiz"), _task("t2", "bugfix", "test_basarisiz")],
                   ensure_ascii=False),
        encoding="utf-8",
    )

    analyze = client.post("/api/v1/coding/insights/analyze")
    assert analyze.status_code == 200 and analyze.json()["success"] is True
    items = analyze.json()["insights"]
    assert items and items[0]["status"] == "oneri"

    listing = client.get("/api/v1/coding/insights")
    assert listing.status_code == 200 and listing.json()["total"] == len(items)

    iid = items[0]["insight_id"]
    approved = client.post(f"/api/v1/coding/insights/{iid}/approve", json={"note": "uygun"})
    assert approved.status_code == 200
    assert approved.json()["insight"]["status"] == "onaylandi"
    assert approved.json()["insight"]["applied"] is False

    rejected = client.post(f"/api/v1/coding/insights/{iid}/reject", json={})
    assert rejected.json()["insight"]["status"] == "reddedildi"

    assert client.post("/api/v1/coding/insights/ins-yok/approve", json={}).status_code == 404
    assert client.get("/api/v1/coding/insights?status=gecersiz").status_code == 400


# ---------------------------------------------------------------- araç regresyonu

def test_search_learning_tool_uses_get(tmp_path, monkeypatch):
    """Regresyon: araç POST atıyordu, endpoint GET -> gerçek sunucuda 405."""
    import tool_executor as te

    calls = []

    class _Resp:
        status_code = 200

        def json(self):
            return {"rapor": "ok-rapor"}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            calls.append(("GET", url, params))
            return _Resp()

        async def post(self, url, **kwargs):
            calls.append(("POST", url, kwargs))
            return _Resp()

    monkeypatch.setattr(te.httpx, "AsyncClient", _Client)

    ex = te.ToolExecutor(working_dir=str(tmp_path))
    res = asyncio.run(ex.execute("search_learning", {"query": "hata kalıpları"}))

    assert res["success"] is True
    assert res["report"] == "ok-rapor"
    assert calls and calls[0][0] == "GET", f"araç GET kullanmalı, çağrılar: {calls}"
