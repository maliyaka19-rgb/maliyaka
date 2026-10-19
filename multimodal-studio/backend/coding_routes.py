"""
Kodlama Yöneticisi API Rotaları
===============================
Kullanıcı -> Ana Yönetici -> Kodlama Yöneticisi -> Uzmanlar -> ... akışını dışa açar.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

import coding_manager as cm

router = APIRouter(prefix="/api/v1/coding", tags=["coding-manager"])


class CodingRunRequest(BaseModel):
    """Kodlama görevi isteği."""
    message: str = Field(..., min_length=1, max_length=8000)
    mode: str = Field(default="plan", description="'plan' (güvenli, yazmaz) veya 'execute'")
    confirm: bool = Field(default=False, description="execute modu için zorunlu onay")
    conversation_id: Optional[str] = None
    via_main_manager: bool = Field(default=True, description="Ana Yönetici Ajan üzerinden")
    verify_command: Optional[str] = Field(default=None, description="Kalite kapısı doğrulama komutu")
    max_retries: int = Field(default=2, ge=0, le=5)
    parallel_analysis: bool = Field(default=False, description="Bağımsız analiz adımlarını paralel çalıştır")
    working_dir: Optional[str] = Field(default=None, description="Görevin çalıştırılacağı dizin (varsayılan: proje kökü)")


@router.get("/health", summary="Kodlama yöneticisi durumu")
async def coding_health():
    """Modülün ve ajan kadrosunun durumu."""
    from custom_agents import load_agents
    ids = {a["id"] for a in load_agents()}
    roles = sorted({s["role"] for steps in cm.WORKFLOWS.values() for s in steps})
    missing = [r for r in roles if r not in ids]
    return {
        "success": True,
        "module": "coding-manager",
        "task_types": [t.value for t in cm.TaskType],
        "roles": roles,
        "missing_roles": missing,
        "roles_ready": not missing,
        "stored_tasks": len(cm.get_tasks()),
    }


@router.get("/workflows", summary="Görev türü -> uzman iş akışları")
async def coding_workflows():
    return {"success": True, "workflows": cm.get_workflows()}


@router.post("/run", summary="Kodlama görevini çalıştır")
async def coding_run(data: CodingRunRequest):
    """Görevi sınıflandırır, uzmanları seçer, kalite kapısını uygular ve rapor üretir."""
    try:
        result = await cm.run_coding_task(
            data.message,
            mode=data.mode,
            confirm=data.confirm,
            conversation_id=data.conversation_id,
            via_main_manager=data.via_main_manager,
            verify_command=data.verify_command,
            max_retries=data.max_retries,
            parallel_analysis=data.parallel_analysis,
            working_dir=data.working_dir,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks", summary="Görev kayıtlarını listele")
async def coding_tasks(limit: int = 50):
    tasks = cm.get_tasks()
    trimmed = []
    for t in tasks[-limit:][::-1]:
        trimmed.append({
            "task_id": t.get("task_id"),
            "created_at": t.get("created_at"),
            "request": (t.get("request") or "")[:160],
            "task_type": t.get("task_type"),
            "mode": t.get("mode"),
            "status": t.get("status"),
            "roles": t.get("roles"),
        })
    return {"success": True, "total": len(tasks), "tasks": trimmed}


@router.get("/tasks/{task_id}", summary="Tek görev kaydı")
async def coding_task_detail(task_id: str):
    task = cm.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Görev bulunamadı")
    return {"success": True, "task": task}


# ============================================================
# ÖĞRENME AJANI — denetimli içgörüler (geçmiş görev kayıtlarından)
# ============================================================

class InsightDecision(BaseModel):
    """İnsan kararı gerekçesi (opsiyonel)."""
    note: str = Field(default="", max_length=500, description="Karar gerekçesi")


@router.get("/insights", summary="Öğrenme Ajanı: denetimli içgörüler")
async def coding_insights_list(status: Optional[str] = None):
    """Saklanan içgörüleri listeler. `status` ile filtre: oneri/onaylandi/reddedildi."""
    import coding_insights as cins
    if status and status not in cins.VALID_STATUSES:
        raise HTTPException(status_code=400,
                            detail=f"Geçersiz durum: {status}. İzin verilenler: {sorted(cins.VALID_STATUSES)}")
    items = cins.list_insights(status=status)
    return {"success": True, "total": len(items), "insights": items}


@router.post("/insights/analyze", summary="Görev geçmişinden içgörü üret (denetimli)")
async def coding_insights_analyze():
    """
    Geçmiş görev kayıtlarını analiz eder ve ÖNERİ üretir.
    Hiçbir kodu/modeli/güvenlik kuralını değiştirmez; yalnızca öneri kaydeder.
    """
    import coding_insights as cins
    return cins.generate_insights()


@router.post("/insights/{insight_id}/approve", summary="İçgörüyü onayla (uygulamaz)")
async def coding_insights_approve(insight_id: str, data: Optional[InsightDecision] = None):
    """Onayı kaydeder. Not: onay OTOMATİK uygulama DEĞİLDİR; yalnızca karar kaydıdır."""
    import coding_insights as cins
    item = cins.set_status(insight_id, "onaylandi", (data.note if data else ""))
    if item is None:
        raise HTTPException(status_code=404, detail="İçgörü bulunamadı")
    return {"success": True, "insight": item}


@router.post("/insights/{insight_id}/reject", summary="İçgörüyü reddet")
async def coding_insights_reject(insight_id: str, data: Optional[InsightDecision] = None):
    """Red kararını kaydeder."""
    import coding_insights as cins
    item = cins.set_status(insight_id, "reddedildi", (data.note if data else ""))
    if item is None:
        raise HTTPException(status_code=404, detail="İçgörü bulunamadı")
    return {"success": True, "insight": item}
