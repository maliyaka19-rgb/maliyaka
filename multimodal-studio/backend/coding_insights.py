"""
Kodlama Görev Geçmişi -> Denetimli İçgörü Motoru
================================================
"Öğrenme ve Gelişim Uzmanı" (learning-agent) için DETERMİNİSTİK öğrenme katmanı.

Amaç: geçmiş kodlama görev kayıtlarından (``coding_tasks.json``) kanıta dayalı
içgörüler çıkarır ve bunları **öneri** olarak saklar.

GÜVENLİK SINIRI (denetimli öğrenme - zorunlu):
  * Bu modül YALNIZCA ``coding_insights.json`` dosyasını yazar.
  * Kaynak kodu, ``model_config.json`` (model/anahtar yapılandırması) veya
    güvenlik kuralları ASLA değiştirilmez; dosya sistemi yazma aracı yoktur.
  * Üretilen her içgörü ``status="oneri"`` ile başlar. Onaylansa bile ``applied``
    her zaman ``False`` kalır: hiçbir değişiklik OTOMATİK uygulanmaz, yalnızca
    insan kararı kayıt altına alınır.
  * LLM kullanılmaz; çıktı tamamen girdi kayıtlarından yeniden üretilebilir
    (bu yüzden test edilebilir ve yanıltıcı olamaz).

Akış:
    coding_tasks.json --(analyze_history)--> içgörü önerileri
                      --(generate_insights)--> coding_insights.json (dedup + karar korunur)
    insan/Ana Yönetici --(set_status)--> onaylandi / reddedildi  (uygulama YOK)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import coding_manager as cm

logger = logging.getLogger("nexus-coding-insights")

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
INSIGHTS_FILE = os.path.join(BACKEND_DIR, "coding_insights.json")
MAX_STORED_INSIGHTS = 200

SUCCESS_STATUS = {"tamamlandi"}
FAILURE_STATUS = {"basarisiz", "test_basarisiz"}

# İnsan kararları. "oneri" başlangıç durumudur; karar verilmiş içgörü silinmez.
STATUS_PROPOSAL = "oneri"
VALID_DECISIONS = {"onaylandi", "reddedildi"}
VALID_STATUSES = {STATUS_PROPOSAL} | VALID_DECISIONS

_SEVERITY_ORDER = {"risk": 0, "uyari": 1, "bilgi": 2}


# ============================================================
# YARDIMCILAR
# ============================================================

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _fingerprint(kind: str, key: str) -> str:
    """Aynı tür+anahtar için kararlı kimlik -> tekrar analizde çift kayıt olmaz."""
    raw = f"{kind}|{key}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:12]


def _make_insight(kind: str, severity: str, finding: str, evidence: Dict[str, Any],
                  recommendation: str, key: str) -> Dict[str, Any]:
    fp = _fingerprint(kind, key)
    return {
        "insight_id": f"ins-{fp}",
        "imza": fp,
        "kind": kind,
        "severity": severity,
        "finding": finding,
        "evidence": evidence,
        "recommendation": recommendation,
        "status": STATUS_PROPOSAL,
        "agent": "learning-agent",  # üreten uzman (denetimli, uygulamaz)
        "applied": False,          # denetimli: hiçbir zaman otomatik uygulanmaz
        "created_at": _now(),
        "updated_at": _now(),
        "decided_at": None,
        "decision_note": "",
        "source": "coding_tasks",
    }


def _norm(text: str) -> str:
    return " ".join(str(text).split()).lower()


def _is_proven(task: Dict[str, Any]) -> bool:
    """Yalnızca GERÇEKTEN çalışan doğrulama komutunun exit_code==0'ı kanıttır."""
    v = task.get("verification")
    return isinstance(v, dict) and v.get("passed") is True


# ============================================================
# ANALİZ (saf/deterministik fonksiyon)
# ============================================================

def analyze_history(tasks: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Görev kayıtlarından içgörü ÖNERİLERİ üretir. Yan etkisi yoktur."""
    tasks = [t for t in (tasks or []) if isinstance(t, dict)]
    total = len(tasks)
    if total == 0:
        return [_make_insight(
            "veri_yok", "bilgi",
            "Henüz kayıtlı kodlama görevi yok; içgörü üretmek için veri gerekiyor.",
            {"toplam_gorev": 0},
            "Görevler tamamlandıkça analizi yeniden çalıştırın.",
            key="global",
        )]

    insights: List[Dict[str, Any]] = []

    # 1) Görev türüne göre başarısızlık oranı
    by_type: Dict[str, Dict[str, Any]] = {}
    for t in tasks:
        tt = t.get("task_type") or "general"
        st = by_type.setdefault(tt, {"basarili": 0, "basarisiz": 0, "failed_ids": []})
        status = t.get("status")
        if status in SUCCESS_STATUS:
            st["basarili"] += 1
        elif status in FAILURE_STATUS:
            st["basarisiz"] += 1
            st["failed_ids"].append(t.get("task_id"))

    for tt, st in sorted(by_type.items()):
        denom = st["basarili"] + st["basarisiz"]
        if denom >= 2 and st["basarisiz"] / denom >= 0.5:
            oran = round(st["basarisiz"] / denom * 100, 1)
            insights.append(_make_insight(
                "basarisizlik_orani", "risk",
                f"'{tt}' türündeki görevlerde başarısızlık oranı yüksek: "
                f"%{oran} ({st['basarisiz']}/{denom}).",
                {
                    "gorev_turu": tt, "basarili": st["basarili"],
                    "basarisiz": st["basarisiz"], "oran_yuzde": oran,
                    "task_ids": st["failed_ids"],
                },
                f"'{tt}' türü için iş akışını/test adımını güçlendirin; "
                f"başarısız adımların kayıtlarını inceleyin.",
                key=tt,
            ))

    # 2) Kanıtsız "tamamlandi" görevler (LLM iddiası kanıt değildir)
    kanitsiz = [t.get("task_id") for t in tasks
                if t.get("status") in SUCCESS_STATUS and not _is_proven(t)]
    if kanitsiz:
        insights.append(_make_insight(
            "kanitsiz_tamamlama", "uyari",
            f"{len(kanitsiz)} görev 'tamamlandi' işaretli ama doğrulama kanıtı yok.",
            {"sayi": len(kanitsiz), "task_ids": kanitsiz},
            "Görev tamamlandı sayılmadan önce gerçek bir doğrulama komutu "
            "(kalite kapısı) çalıştırılmalı; ajan iddiası kanıt değildir.",
            key="kanitsiz",
        ))

    # 3) Retry yoğunluğu
    retry_tasks = [t.get("task_id") for t in tasks if (t.get("retries") or 0) > 0]
    if retry_tasks:
        insights.append(_make_insight(
            "retry_yogunlugu", "bilgi",
            f"{len(retry_tasks)} görevde sınırlı yeniden deneme (retry) kullanıldı.",
            {"sayi": len(retry_tasks), "task_ids": retry_tasks},
            "Sık retry alan görev türlerinde kalite kapısı ilk denemede geçecek "
            "şekilde iyileştirilebilir.",
            key="retry",
        ))

    # 4) Başarısız adım üreten roller
    role_fail: Dict[str, set] = {}
    for t in tasks:
        for m in t.get("messages") or []:
            if not isinstance(m, dict):
                continue
            failed = str(m.get("status")) == "basarisiz" or m.get("success") is False
            if failed:
                role = m.get("sender") or "bilinmeyen"
                role_fail.setdefault(role, set()).add(t.get("task_id"))
    for role, tids in sorted(role_fail.items()):
        if len(tids) >= 2:
            insights.append(_make_insight(
                "basarisiz_rol", "uyari",
                f"'{role}' rolü {len(tids)} farklı görevde başarısız adım üretti.",
                {"rol": role, "sayi": len(tids), "task_ids": sorted(t for t in tids if t)},
                f"'{role}' rolünün sistem promptu/araç izni ve model seçimi gözden geçirilsin.",
                key=role,
            ))

    # 5) Tekrarlayan kalan riskler
    issue_count: Dict[str, int] = {}
    issue_tasks: Dict[str, set] = {}
    for t in tasks:
        for issue in t.get("remaining_issues") or []:
            if not isinstance(issue, str):
                continue
            norm = _norm(issue)
            if not norm:
                continue
            issue_count[norm] = issue_count.get(norm, 0) + 1
            issue_tasks.setdefault(norm, set()).add(t.get("task_id"))
    recurring = sorted(((k, v) for k, v in issue_count.items() if v >= 2),
                       key=lambda x: (-x[1], x[0]))
    for norm, count in recurring:
        insights.append(_make_insight(
            "tekrarlayan_kalan_risk", "uyari",
            f"Tekrarlayan kalan risk ({count} görev): \"{norm[:120]}\"",
            {"sayi": count, "metin": norm[:300],
             "task_ids": sorted(t for t in issue_tasks[norm] if t)},
            "Bu riski kalıcı olarak gideren bir düzeltme + regresyon testi eklenmeli.",
            key=norm,
        ))

    return insights


# ============================================================
# KALICILIK
# ============================================================

def _load_all() -> List[Dict[str, Any]]:
    if not os.path.exists(INSIGHTS_FILE):
        return []
    try:
        with open(INSIGHTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as exc:  # bozuk dosya uygulamayı düşürmesin
        logger.error("İçgörü dosyası okunamadı: %s", exc)
        return []


def _save_all(items: List[Dict[str, Any]]) -> None:
    try:
        with open(INSIGHTS_FILE, "w", encoding="utf-8") as f:
            json.dump(items[-MAX_STORED_INSIGHTS:], f, indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.error("İçgörü dosyası yazılamadı: %s", exc)


def _sort_key(item: Dict[str, Any]):
    return (_SEVERITY_ORDER.get(item.get("severity"), 3), item.get("insight_id") or "")


# ============================================================
# GENEL API
# ============================================================

def generate_insights(tasks: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Analizi çalıştırır, önerileri kalıcılaştırır (dedup), kararları KORUR."""
    if tasks is None:
        tasks = cm.get_tasks()

    fresh = analyze_history(tasks)
    stored = _load_all()
    by_sig = {i.get("imza"): i for i in stored if isinstance(i, dict) and i.get("imza")}

    merged: List[Dict[str, Any]] = []
    created = 0
    for ins in fresh:
        old = by_sig.pop(ins["imza"], None)
        if old is not None:
            # Karar (onay/red) ve kimlik korunur; yalnızca kanıt/gerekçe tazelenir.
            old.update({
                "severity": ins["severity"],
                "finding": ins["finding"],
                "evidence": ins["evidence"],
                "recommendation": ins["recommendation"],
                "updated_at": _now(),
            })
            merged.append(old)
        else:
            created += 1
            merged.append(ins)

    # Kanıtı kalmayan ÖNERİLER düşürülür; insan kararı verilmiş kayıtlar saklanır.
    for leftover in by_sig.values():
        if leftover.get("status") != STATUS_PROPOSAL:
            merged.append(leftover)

    merged.sort(key=_sort_key)
    _save_all(merged)
    return {
        "success": True,
        "created": created,
        "total": len(merged),
        "tasks_analyzed": len(tasks),
        "insights": merged,
    }


def list_insights(status: Optional[str] = None) -> List[Dict[str, Any]]:
    items = [i for i in _load_all() if isinstance(i, dict)]
    if status:
        items = [i for i in items if i.get("status") == status]
    items.sort(key=_sort_key)
    return items


def get_insight(insight_id: str) -> Optional[Dict[str, Any]]:
    for i in _load_all():
        if isinstance(i, dict) and i.get("insight_id") == insight_id:
            return i
    return None


def set_status(insight_id: str, status: str, note: str = "") -> Optional[Dict[str, Any]]:
    """İnsan kararını kaydeder. DEĞİŞİKLİK UYGULAMAZ (``applied`` daima False)."""
    if status not in VALID_DECISIONS:
        raise ValueError(f"Geçersiz karar: {status!r}. İzin verilenler: {sorted(VALID_DECISIONS)}")

    items = _load_all()
    found: Optional[Dict[str, Any]] = None
    for item in items:
        if item.get("insight_id") == insight_id:
            item["status"] = status
            item["decided_at"] = _now()
            item["decision_note"] = (note or "")[:500]
            item["applied"] = False  # onay dahi otomatik uygulama değildir
            found = item
            break

    if found is None:
        return None
    _save_all(items)
    return found


def new_insight_id() -> str:
    """Yardımcı: insan eliyle eklenen kayıtlar için benzersiz kimlik."""
    return f"ins-{uuid.uuid4().hex[:12]}"
