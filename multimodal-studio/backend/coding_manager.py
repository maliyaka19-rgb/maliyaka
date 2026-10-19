"""
Kodlama Yöneticisi Ajanı (Coding Manager Agent)
===============================================
Gerçek, deterministik bir orkestrasyon motoru. 20 genel ajanı SİLMEZ; onları
uzman olarak yeniden kullanır ve kodlama alanı için eksik uzmanları devreye alır.

Akış (kullanıcı isteği):
    KULLANICI -> ANA YÖNETİCİ AJAN -> KODLAMA YÖNETİCİ AJANI
              -> UZMAN KODLAMA AJANLARI -> KODLAMA YÖNETİCİ AJANI
              -> ANA YÖNETİCİ AJAN -> KULLANICI

Bu modül şunları GERÇEKTEN yapar:
  * Görevi sınıflandırır (feature/bugfix/security/performance/api/research/refactor).
  * Görev türüne göre uzman iş akışını (workflow) seçer; gereksiz uzman çalıştırmaz.
  * Adım-bazlı EN AZ YETKİ: write gerektirmeyen adımlara salt-okuma araç listesi verir.
  * Görev mesajlarını (gönderen/alıcı/amaç/durum/kanıt) kaydeder.
  * Dosya çakışmasını FileLockRegistry ile engeller.
  * Kalite kapısı: test adımı + (varsa) gerçek doğrulama komutu; test başarısızsa
    uzmanı sınırlı sayıda (max_retries) yeniden çalıştırır.
  * Ana Yönetici Ajana yapılandırılmış SONUÇ RAPORU üretir.
  * Görev kayıtlarını kalıcı olarak saklar (coding_tasks.json).

DÜRÜSTLÜK NOTLARI:
  * `mode="plan"` (varsayılan) hiçbir dosyayı DEĞİŞTİRMEZ; yazma yetkili ajanlara
    salt-okuma araçları verilir ve yalnızca plan/öneri üretmeleri istenir.
  * `mode="execute"` gerçek yazma izni verir ve `confirm=True` gerektirir.
  * LLM'in "test geçti" iddiası KANIT sayılmaz; yalnızca gerçekten çalıştırılan
    doğrulama komutunun çıkış kodu kanıt olarak işaretlenir.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nexus-coding-manager")

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)          # multimodal-studio
TASKS_FILE = os.path.join(BACKEND_DIR, "coding_tasks.json")
MAX_STORED_TASKS = 100


# ============================================================
# TÜRLER
# ============================================================

class TaskType(str, Enum):
    FEATURE = "feature"
    BUGFIX = "bugfix"
    SECURITY = "security"
    PERFORMANCE = "performance"
    API = "api"
    FRONTEND = "frontend"
    DATABASE = "database"
    DEVOPS = "devops"
    RESEARCH = "research"
    REFACTOR = "refactor"
    GENERAL = "general"


class TaskStatus(str, Enum):
    PENDING = "bekliyor"
    RUNNING = "calisiyor"
    REVIEW = "inceleme_bekliyor"
    TEST_FAILED = "test_basarisiz"
    COMPLETED = "tamamlandi"
    FAILED = "basarisiz"
    NEEDS_APPROVAL = "onay_bekliyor"


class StepStatus(str, Enum):
    PENDING = "bekliyor"
    RUNNING = "calisiyor"
    COMPLETED = "tamamlandi"
    FAILED = "basarisiz"
    SKIPPED = "atlandi"


# Yalnızca okuma/analiz yapan araçlar. Yazma adımı olmayan bir adıma bu liste verilir.
READ_ONLY_TOOLS = [
    "read_file", "list_files", "search_files", "web_search", "calculate",
    "rag_search", "rag_list_documents", "search_learning", "answer_question",
    "generate_code", "generate_visual_prompt", "generate_video_prompt",
]
READ_ONLY_SET = set(READ_ONLY_TOOLS)

# Güvenli varsayılan: salt-okuma ajanın kendi listesinden hiç araç kalmadıysa
# en azından bunlarla çalışabilir.
MINIMAL_READ_TOOLS = ["read_file", "list_files", "search_files"]

# LLM'in "metin üretemedim" yanıtları: nihai yanıt bunlardan oluşamaz.
_LLM_FAIL_MARKERS = (
    "tam yanıt üretemiyorum",
    "bir yanıt üretemedim",
    "metin yanıt oluşturulamadı",
)


# ============================================================
# GÖREV SINIFLANDIRMA
# ============================================================

_TASK_KEYWORDS: Dict[TaskType, List[str]] = {
    TaskType.SECURITY: ["güvenlik", "guvenlik", "security", "zafiyet", "vulnerability",
                        "xss", "sql injection", "yetkilendirme", "authorization",
                        "şifreleme", "sifreleme", "secret", "token sız", "cve", "exploit"],
    TaskType.BUGFIX: ["hata", "bug", "düzelt", "duzelt", "fix", "çalışmıyor", "calismiyor",
                      "bozuk", "error", "exception", "crash", "traceback", "hatayı", "hatali"],
    TaskType.PERFORMANCE: ["performans", "performance", "yavaş", "yavas", "slow", "optimize",
                           "hızlandır", "hizlandir", "bellek", "memory", "cpu", "darboğaz",
                           "latency", "gecikme", "profiling"],
    TaskType.API: ["api", "endpoint", "rest", "uç nokta", "uc nokta", "backend", "sunucu",
                   "server", "route", "jwt", "fastapi", "flask", "socket", "webhook"],
    TaskType.FRONTEND: ["arayüz", "arayuz", "frontend", "ui", "ekran", "sayfa", "bileşen",
                        "bilesen", "component", "react", "css", "html", "layout", "stil"],
    TaskType.DATABASE: ["veritabanı", "veritabani", "database", "sql", "migration", "migrasyon",
                        "şema", "sema", "tablo", "postgres", "mysql", "sqlite", "sorgu"],
    TaskType.DEVOPS: ["deploy", "dağıt", "dagit", "docker", "kubernetes", "ci/cd", "pipeline",
                      "yayınla", "yayinla", "sunucuya", "render", "nginx", "systemd"],
    TaskType.REFACTOR: ["refactor", "yeniden düzenle", "yeniden duzenle", "temizle", "kod kalitesi",
                        "basitleştir", "basitlestir", "modüler", "moduler", "duplicate", "tekrar eden"],
    TaskType.FEATURE: ["yeni özellik", "yeni ozellik", "özellik ekle", "ozellik ekle", "ekle",
                       "oluştur", "olustur", "geliştir", "gelistir", "feature", "implement",
                       "yeni fonksiyon", "yeni sınıf", "yeni sinif", "entegre et"],
    TaskType.RESEARCH: ["araştır", "arastir", "research", "hangisi daha iyi", "karşılaştır",
                        "karsilastir", "neden", "nasıl yapılır", "nasil yapilir", "doküman",
                        "dokuman", "belirsiz", "en iyi yol", "best practice"],
}

# Eşitlik durumunda tercih sırası (riskli/özel türler önce).
_TASK_PRIORITY = [
    TaskType.SECURITY, TaskType.BUGFIX, TaskType.PERFORMANCE, TaskType.API,
    TaskType.FRONTEND, TaskType.DATABASE, TaskType.DEVOPS,
    TaskType.REFACTOR, TaskType.FEATURE, TaskType.RESEARCH, TaskType.GENERAL,
]


def classify_task(message: str) -> TaskType:
    """Mesajı kodlama görev türüne sınıflandırır (deterministik)."""
    text = (message or "").lower()
    scores: Dict[TaskType, int] = {}
    for ttype, keywords in _TASK_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if kw in text:
                score += len(kw.split()) * 2 + 1
        if score:
            scores[ttype] = score
    if not scores:
        return TaskType.GENERAL
    best = max(scores.values())
    for ttype in _TASK_PRIORITY:
        if scores.get(ttype, 0) == best:
            return ttype
    return TaskType.GENERAL


# ============================================================
# İŞ AKIŞLARI (görev türü -> uzman adımları)
# ============================================================
# write=True : adım dosya değiştirebilir (yalnızca mode="execute" ve confirm=True).
# optional   : adım çalışmasa da görev başarısız sayılmaz.

WORKFLOWS: Dict[TaskType, List[Dict[str, Any]]] = {
    TaskType.FEATURE: [
        {"role": "task-planner", "goal": "İsteği alt görevlere böl; sıra, bağımlılık ve kabul kriterlerini yaz.", "write": False, "optional": True},
        {"role": "code-analyst", "goal": "İlgili dosyaları ve mevcut kod yapısını incele; değişiklik alanlarını listele.", "write": False},
        {"role": "dependency-analyst", "goal": "Değişikliğin bağımlılık/ortam etkisini (paket, sürüm, platform) değerlendir.", "write": False, "optional": True},
        {"role": "architect", "goal": "Önerilen değişikliğin mimari etkisini ve risklerini değerlendir.", "write": False, "optional": True},
        {"role": "coder", "goal": "İstenen özelliği mevcut kod standartlarına uygun şekilde geliştir.", "write": True},
        {"role": "test-engineer", "goal": "Değişiklik için birim/entegrasyon testleri yaz ve çalıştır; gerçek çıktıyı raporla.", "write": True},
        {"role": "reviewer", "goal": "Değişikliği bağımsız incele; mantık hatası ve eksik test ara. Kanıtsız onay verme.", "write": False},
        {"role": "regression-tester", "goal": "Mevcut özelliklerin bozulmadığını doğrula (regresyon).", "write": False, "optional": True},
    ],
    TaskType.BUGFIX: [
        {"role": "debugger", "goal": "Hata mesajı/günlükleri incele; kök nedeni araştır (varsayımı bulgudan ayır).", "write": False},
        {"role": "code-analyst", "goal": "Hatayla ilgili kodu ve bağımlılıkları incele.", "write": False},
        {"role": "dependency-analyst", "goal": "Hatanın bağımlılık/sürüm/ortam kaynaklı olup olmadığını kontrol et.", "write": False, "optional": True},
        {"role": "bug-fixer", "goal": "Hedefe yönelik, ilgisiz koda dokunmayan güvenli düzeltme yap.", "write": True},
        {"role": "test-engineer", "goal": "Hatayı yeniden üreten test yaz, düzeltmeyi doğrula, gerçek çıktıyı raporla.", "write": True},
        {"role": "reviewer", "goal": "Düzeltmeyi bağımsız incele.", "write": False},
        {"role": "regression-tester", "goal": "Regresyon kontrolü yap.", "write": False, "optional": True},
    ],
    TaskType.SECURITY: [
        {"role": "code-analyst", "goal": "İlgili kodu ve giriş noktalarını incele.", "write": False},
        {"role": "security", "goal": "Yetkilendirme, sırlar, kullanıcı verisi ve güvenilmeyen girdileri risk derecesiyle raporla.", "write": False},
        {"role": "bug-fixer", "goal": "Kritik güvenlik bulgularını en az yetkiyle düzelt.", "write": True},
        {"role": "test-engineer", "goal": "Güvenlik düzeltmesini doğrulayan test yaz/çalıştır.", "write": True},
        {"role": "reviewer", "goal": "Düzeltmeyi bağımsız incele.", "write": False},
        {"role": "evidence-auditor", "goal": "İddia edilen işlemler ile kanıtları karşılaştır; eksik kanıtı bildir.", "write": False},
    ],
    TaskType.PERFORMANCE: [
        {"role": "code-analyst", "goal": "Sıcak yolları ve ilgili kodu incele.", "write": False},
        {"role": "performance-pro", "goal": "Bellek/CPU/ağ ve yanıt süresi darboğazlarını KANITLA (ölçüm olmadan iddia etme).", "write": False},
        {"role": "optimizer", "goal": "Ölçülebilir fayda sağlayan optimizasyonu uygula; doğruluğu bozma.", "write": True},
        {"role": "test-engineer", "goal": "Optimizasyon sonrası testleri çalıştır ve çıktıyı raporla.", "write": True},
        {"role": "regression-tester", "goal": "Regresyon kontrolü yap.", "write": False, "optional": True},
    ],
    TaskType.API: [
        {"role": "task-planner", "goal": "API görevini alt görevlere böl; sözleşme ve kabul kriterlerini yaz.", "write": False, "optional": True},
        {"role": "architect", "goal": "API sözleşmesini, veri modellerini ve uç nokta tasarımını belirle.", "write": False},
        {"role": "database-pro", "goal": "Veri modeli/şema ve sorgu etkisini değerlendir; gerekli değişikliği öner.", "write": False, "optional": True},
        {"role": "backend-pro", "goal": "Sunucu/API uç noktasını doğrulama, hata yanıtları ve yetkilendirmeyle geliştir.", "write": True},
        {"role": "integrator", "goal": "Yeni uç noktayı arayüz/istemcilerle entegre et; veri formatı uyumunu kontrol et.", "write": True},
        {"role": "security", "goal": "Yeni uç noktanın yetkilendirme ve girdi doğrulamasını incele.", "write": False},
        {"role": "test-engineer", "goal": "Uçtan uca/entegrasyon testi yaz ve çalıştır.", "write": True},
        {"role": "docs-writer", "goal": "Yeni uç noktanın kullanım/teknik belgesini güncelle (olmayan özellik ekleme).", "write": True, "optional": True},
    ],
    TaskType.RESEARCH: [
        {"role": "tech-researcher", "goal": "Belirsiz teknik noktayı izinli kaynaklarla araştır; bulgu ile varsayımı ayır.", "write": False},
        {"role": "code-analyst", "goal": "Projede ilgili mevcut kodu incele.", "write": False},
        {"role": "coder", "goal": "Araştırma sonucuna göre en uygun çözümü uygula.", "write": True},
        {"role": "reviewer", "goal": "Sonucu bağımsız incele.", "write": False},
    ],
    TaskType.REFACTOR: [
        {"role": "code-analyst", "goal": "Kod kokusunu ve tekrarları tespit et.", "write": False},
        {"role": "optimizer", "goal": "Davranışı koruyarak yeniden düzenle (refactor).", "write": True},
        {"role": "test-engineer", "goal": "Refactor sonrası testleri çalıştır.", "write": True},
        {"role": "regression-tester", "goal": "Regresyon kontrolü yap.", "write": False},
        {"role": "reviewer", "goal": "Bağımsız incele.", "write": False},
    ],
    TaskType.FRONTEND: [
        {"role": "code-analyst", "goal": "Mevcut arayüz kodunu ve bileşen yapısını incele.", "write": False},
        {"role": "frontend-pro", "goal": "İstenen arayüz değişikliğini erişilebilirlik ve mevcut stil kurallarına uygun uygula.", "write": True},
        {"role": "test-engineer", "goal": "Arayüz davranışını doğrulayan testi yaz/çalıştır; gerçek çıktıyı raporla.", "write": True},
        {"role": "reviewer", "goal": "Değişikliği bağımsız incele; kırık bağlantı ve erişilebilirlik sorunu ara.", "write": False},
        {"role": "regression-tester", "goal": "Mevcut ekranların bozulmadığını doğrula.", "write": False, "optional": True},
    ],
    TaskType.DATABASE: [
        {"role": "code-analyst", "goal": "Mevcut veri modelini ve sorguları incele.", "write": False},
        {"role": "dependency-analyst", "goal": "Veritabanı sürücüsü/bağımlılık ve sürüm uyumunu kontrol et.", "write": False, "optional": True},
        {"role": "database-pro", "goal": "Şema/migration ve sorgu değişikliğini geri alınabilir biçimde uygula.", "write": True},
        {"role": "test-engineer", "goal": "Veri katmanı testini yaz/çalıştır; gerçek çıktıyı raporla.", "write": True},
        {"role": "reviewer", "goal": "Veri kaybı ve geriye dönük uyumluluk riskini incele.", "write": False},
    ],
    TaskType.DEVOPS: [
        {"role": "dependency-analyst", "goal": "Çalışma zamanı/bağımlılık ve ortam gereksinimlerini çıkar.", "write": False},
        {"role": "devops", "goal": "Dağıtım/CI yapılandırmasını en az yetkiyle hazırla; sırları koda yazma.", "write": True},
        {"role": "test-engineer", "goal": "Yapılandırmayı doğrulayan komutu çalıştır; gerçek çıktıyı raporla.", "write": True},
        {"role": "reviewer", "goal": "Dağıtım risklerini (sır sızıntısı, eksik ortam değişkeni) incele.", "write": False},
        {"role": "evidence-auditor", "goal": "İddia edilen dağıtım adımları ile gerçek çıktıları karşılaştır.", "write": False, "optional": True},
    ],
    TaskType.GENERAL: [
        {"role": "code-analyst", "goal": "İlgili kodu incele ve durumu özetle.", "write": False},
        {"role": "coder", "goal": "İstenen değişikliği uygula.", "write": True},
        {"role": "reviewer", "goal": "Bağımsız incele.", "write": False},
    ],
}


def select_workflow(task_type: TaskType) -> List[Dict[str, Any]]:
    """Görev türüne karşılık gelen iş akışını döndürür (kopya)."""
    return [dict(step) for step in WORKFLOWS.get(task_type, WORKFLOWS[TaskType.GENERAL])]


def get_workflows() -> Dict[str, List[Dict[str, Any]]]:
    """Tüm iş akışlarının JSON-güvenli kopyası."""
    return {t.value: [dict(s) for s in steps] for t, steps in WORKFLOWS.items()}


# ============================================================
# DOSYA ÇAKIŞMA KİLİDİ
# ============================================================

class FileLockRegistry:
    """Aynı dosyayı iki ajanın eş zamanlı değiştirmesini engeller."""

    def __init__(self) -> None:
        self._locks: Dict[str, str] = {}
        self._conflicts: List[Dict[str, str]] = []

    @staticmethod
    def _norm(path: str) -> str:
        return os.path.normcase(os.path.abspath(path or ""))

    def acquire(self, path: str, owner: str) -> bool:
        key = self._norm(path)
        current = self._locks.get(key)
        if current is not None and current != owner:
            self._conflicts.append({"path": path, "owner": owner, "held_by": current})
            logger.warning("Dosya çakışması engellendi: %s (tut: %s, isteyen: %s)", path, current, owner)
            return False
        self._locks[key] = owner
        return True

    def release(self, path: str, owner: str) -> None:
        key = self._norm(path)
        if self._locks.get(key) == owner:
            self._locks.pop(key, None)

    def owner(self, path: str) -> Optional[str]:
        return self._locks.get(self._norm(path))

    @property
    def conflicts(self) -> List[Dict[str, str]]:
        return list(self._conflicts)


# ============================================================
# GÖREV MESAJI / KAYDI
# ============================================================

@dataclass
class TaskMessage:
    """Ajanlar arası tek bir görev/sonuç mesajı."""
    task_id: str
    sender: str
    recipient: str
    purpose: str
    status: str
    files: List[str] = field(default_factory=list)
    expected_output: str = ""
    tools_used: List[str] = field(default_factory=list)
    changes: List[str] = field(default_factory=list)
    test_results: str = ""
    evidence: List[str] = field(default_factory=list)
    remaining_issues: List[str] = field(default_factory=list)
    response: str = ""
    success: bool = False
    duration_ms: int = 0


# ============================================================
# YÖNETİCİ
# ============================================================

class CodingTaskManager:
    """Kodlama alanının merkezî yöneticisi (deterministik orkestratör)."""

    def __init__(self, working_dir: Optional[str] = None) -> None:
        self.working_dir = working_dir or PROJECT_ROOT
        self.locks = FileLockRegistry()

    # -- adım araç izni (en az yetki) --------------------------------------
    @staticmethod
    def resolve_tools(role_agent: Optional[Dict[str, Any]], step: Dict[str, Any], mode: str) -> List[str]:
        """Adıma verilecek araç listesini belirler.

        write=False VEYA mode != execute  ->  yalnızca salt-okuma araçları.
        write=True  VE mode == execute    ->  ajanın tanımlı araçları (yazma dahil).
        """
        declared = list((role_agent or {}).get("tools") or [])
        can_write = bool(step.get("write")) and mode == "execute"
        if can_write:
            allowed = declared or list(READ_ONLY_TOOLS)
            # generate_code yalnızca METİN üretir, dosyaya yazmaz. Yazma adımında
            # modele verilirse kodu sohbete döküp dosyayı hiç oluşturmuyor
            # (canlı kanıt: 2 başarısız koşu). Yazma adımında bu araç verilmez.
            return [t for t in allowed if t != "generate_code"]
        read_tools = [t for t in declared if t in READ_ONLY_SET]
        if not read_tools:
            read_tools = list(MINIMAL_READ_TOOLS)
        return read_tools

    # -- tek adım ----------------------------------------------------------
    async def _run_step(self, task_id: str, base_conv: str, index: int,
                        step: Dict[str, Any], mode: str, task_request: str,
                        extra_context: str = "") -> TaskMessage:
        from custom_agents import get_agent
        import ai_agent as _ai

        role = step["role"]
        agent = get_agent(role) or {}
        tools = self.resolve_tools(agent, step, mode)

        mode_note = (
            "ŞU AN 'PLAN' MODU: HİÇBİR dosyayı DEĞİŞTİRME/OLUŞTURMA; yalnızca "
            "analiz, plan veya önerilen değişikliği metin olarak sun."
            if mode != "execute" else
            "ŞU AN 'UYGULA' MODU: gerekli dosya değişikliklerini yapabilir ve "
            "komut çalıştırabilirsin. Dosya oluşturmak için write_file, mevcut "
            "dosyayı değiştirmek için edit_file aracını ÇAĞIR. generate_code "
            "dosyaya YAZMAZ (yalnızca kod önerisi üretir); kodu yanıt metnine "
            "dökme, gerçekten dosyayı yaz."
        )
        prefix = (
            f"[KODLAMA YÖNETİCİSİ GÖREVİ] Rol: {role}\n"
            f"Görev türü: {step.get('task_type', '-')}\n"
            f"Amaç: {step['goal']}\n{mode_note}\n"
        )
        prompt = (
            f"KULLANICI İSTEĞİ:\n{task_request}\n\n"
            f"BU ADIMDAKİ GÖREVİN:\n{step['goal']}\n"
            + (f"\nEK BAĞLAM:\n{extra_context}\n" if extra_context else "")
        )

        msg = TaskMessage(
            task_id=task_id, sender="coding-manager", recipient=role,
            purpose=step["goal"], status=StepStatus.RUNNING.value,
            expected_output=step["goal"], files=[],
        )
        started = time.time()
        try:
            result = await _ai.chat(
                prompt,
                conversation_id=f"{base_conv}-{index}",
                agent_id=role,
                tools_override=tools,
                system_prefix=prefix,
            )
        except Exception as exc:  # ajan çökerse görev sessizce kaybolmaz
            msg.status = StepStatus.FAILED.value
            msg.remaining_issues.append(f"Ajan çağrısı başarısız: {exc}")
            msg.duration_ms = int((time.time() - started) * 1000)
            logger.error("Adım hatası (%s): %s", role, exc)
            return msg

        msg.duration_ms = int((time.time() - started) * 1000)
        msg.response = (result or {}).get("response") or ""
        msg.tools_used = list((result or {}).get("tools_used") or [])
        # Ajanın GERÇEKTEN yazdığı dosyalar (araç sonucundan; iddia değil).
        msg.changes = list((result or {}).get("files_changed") or [])
        msg.success = bool((result or {}).get("success"))
        if msg.success:
            msg.status = StepStatus.COMPLETED.value
        else:
            msg.status = StepStatus.FAILED.value
            msg.remaining_issues.append((result or {}).get("error") or "bilinmeyen hata")
        return msg

    # -- gerçek doğrulama komutu -------------------------------------------
    def run_verification(self, command: str, timeout: int = 240) -> Dict[str, Any]:
        """Kalite kapısı: doğrulama komutunu GERÇEKTEN çalıştırır."""
        try:
            proc = subprocess.run(
                command, shell=True, cwd=self.working_dir, timeout=timeout,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            return {
                "command": command,
                "ran": True,
                "exit_code": proc.returncode,
                "passed": proc.returncode == 0,
                "stdout_tail": (proc.stdout or "")[-1500:],
                "stderr_tail": (proc.stderr or "")[-800:],
            }
        except Exception as exc:
            return {"command": command, "ran": False, "passed": None,
                    "error": str(exc)}

    # -- ana akış ----------------------------------------------------------
    async def run(self, *args, **kwargs) -> Dict[str, Any]:
        """Görevi GÖREV-YEREL çalışma dizininde çalıştırır.

        Araçların dosya yazımları ve komutları `working_dir`e hapsedilir
        (contextvar). Eşzamanlı görevler birbirini etkilemez; bitince eski
        değere döner (sızıntı yok).
        """
        from tool_executor import task_working_dir

        target = os.path.realpath(self.working_dir)
        if not os.path.isdir(target):
            raise ValueError(f"Çalışma dizini bulunamadı: {target}")

        token = task_working_dir.set(target)
        try:
            return await self._run(*args, **kwargs)
        finally:
            task_working_dir.reset(token)

    async def _run(self, message: str, mode: str = "plan", confirm: bool = False,
                  conversation_id: Optional[str] = None, via_main_manager: bool = True,
                  verify_command: Optional[str] = None, max_retries: int = 2,
                  parallel_analysis: bool = False) -> Dict[str, Any]:
        import ai_agent as _ai

        message = (message or "").strip()
        if not message:
            raise ValueError("Boş görev")

        approval_note = None
        if mode == "execute" and not confirm:
            approval_note = "execute modu için onay verilmedi; güvenli 'plan' moduna alındı."
            logger.warning(approval_note)
            mode = "plan"

        task_id = str(uuid.uuid4())[:12]
        base_conv = conversation_id or f"coding-{task_id}"
        task_type = classify_task(message)
        steps = select_workflow(task_type)
        for s in steps:
            s["task_type"] = task_type.value

        logger.info("Kodlama görevi %s: tür=%s, adım=%d, mod=%s",
                    task_id, task_type.value, len(steps), mode)

        record: Dict[str, Any] = {
            "task_id": task_id,
            "created_at": datetime.now().isoformat(),
            "request": message,
            "task_type": task_type.value,
            "mode": mode,
            "confirm": bool(confirm),
            "approval_note": approval_note,
            "status": TaskStatus.RUNNING.value,
            "conversation_id": base_conv,
            "messages": [],
            "files_changed": [],
            "tools_used": [],
            "verification": None,
            "retries": 0,
            "max_retries": max_retries,
            "conflicts": [],
            "review": None,
            "final_answer": "",
            "remaining_issues": [],
            "roles": [s["role"] for s in steps],
        }

        # ---- ANA YÖNETİCİ AJAN: görev kabulü / brief ----------------------
        if via_main_manager:
            intake = await self._run_step(
                task_id, f"{base_conv}-mm0", "mm0",
                {"role": "main-manager", "goal": "Kullanıcı isteğini kodlama görevi olarak netleştir ve tek paragraf görev tanımı (brief) üret.", "write": False, "task_type": task_type.value},
                "plan", message,
            )
            record["messages"].append(asdict(intake) | {"phase": "intake"})
            if intake.response:
                record["brief"] = intake.response[:1200]

        # ---- UZMAN ADIMLARI ----------------------------------------------
        step_results: List[TaskMessage] = []
        write_steps: List[TaskMessage] = []
        i = 0
        while i < len(steps):
            step = steps[i]
            # Analiz adımlarını (paralel_analysis açıksa) toplu çalıştır.
            if parallel_analysis and not step.get("write"):
                group = []
                j = i
                while j < len(steps) and not steps[j].get("write"):
                    group.append((j, steps[j]))
                    j += 1
                if len(group) > 1:
                    results = await asyncio.gather(*[
                        self._run_step(task_id, base_conv, idx, st, mode, message)
                        for idx, st in group
                    ])
                    for r in results:
                        record["messages"].append(asdict(r))
                        record["tools_used"].extend(r.tools_used)
                        record["files_changed"].extend(r.changes)
                        step_results.append(r)
                    i = j
                    continue

            # Dosya çakışma koruması (yazma adımı için seri kilit).
            lock_owner = f"{step['role']}"
            got = self.locks.acquire(f"__step_{i}__", lock_owner)
            if not got:
                record["conflicts"].append({"step": i, "role": step["role"]})

            rm = await self._run_step(task_id, base_conv, i, step, mode, message)
            self.locks.release(f"__step_{i}__", lock_owner)
            record["messages"].append(asdict(rm))
            record["tools_used"].extend(rm.tools_used)
            record["files_changed"].extend(rm.changes)
            step_results.append(rm)
            if step.get("write"):
                write_steps.append(rm)

            if not rm.success and not step.get("optional"):
                record["status"] = TaskStatus.FAILED.value
                record["remaining_issues"].append(f"Adım başarısız: {step['role']}")
            i += 1

        record["conflicts"].extend(self.locks.conflicts)
        record["tools_used"] = list(dict.fromkeys(record["tools_used"]))
        record["files_changed"] = list(dict.fromkeys(record["files_changed"]))

        # ---- KALİTE KAPISI: gerçek doğrulama komutu -----------------------
        if verify_command:
            attempt = 0
            while True:
                verification = self.run_verification(verify_command)
                record["verification"] = verification
                record["status"] = (
                    TaskStatus.COMPLETED.value if verification.get("passed")
                    else TaskStatus.TEST_FAILED.value
                )
                if verification.get("passed") or mode != "execute" or attempt >= max_retries:
                    break
                # Test başarısız -> son yazma adımını hata çıktısıyla yeniden çalıştır
                attempt += 1
                record["retries"] = attempt
                if not write_steps:
                    break
                last = write_steps[-1]
                fix_step = None
                for s in steps:
                    if s["role"] == last.recipient:
                        fix_step = dict(s)
                        break
                if not fix_step:
                    break
                err_ctx = (
                    f"Önceki doğrulama BAŞARISIZ (exit={verification.get('exit_code')}).\n"
                    f"stderr:\n{verification.get('stderr_tail','')}\n"
                    f"stdout:\n{verification.get('stdout_tail','')}\n"
                    "Bu hatayı GİDER ve görevi tamamla. Tekrar başarısız olma."
                )
                rm = await self._run_step(task_id, f"{base_conv}-retry{attempt}",
                                          f"retry{attempt}", fix_step, mode, message,
                                          extra_context=err_ctx)
                record["messages"].append(asdict(rm) | {"phase": f"retry{attempt}"})
                record["tools_used"].extend(rm.tools_used)
                record["files_changed"].extend(rm.changes)
                record["tools_used"] = list(dict.fromkeys(record["tools_used"]))
        else:
            # Doğrulama komutu yok -> test adımı gerçekten komut çalıştırdı mı?
            test_msgs = [m for m in step_results if m.recipient in ("test-engineer", "regression-tester", "reviewer")]
            ran_cmd = any("execute_command" in m.tools_used for m in test_msgs)
            record["verification"] = {
                "ran": ran_cmd,
                "passed": None,
                "note": "Doğrulama komutu verilmedi; test ajanının komut çalıştırdığına dair kanıt: "
                        + ("VAR" if ran_cmd else "YOK (iddia doğrulanmadı)"),
            }
            if record["status"] == TaskStatus.RUNNING.value:
                record["status"] = TaskStatus.COMPLETED.value

        # ---- KANITSIZ YAZMA ADIMI -----------------------------------------
        # Adım "başarılı" dönebilir ama tek dosya bile değiştirmemiş olabilir
        # (canlı E2E'de görüldü). Bu, sessizce yutulmaz; rapora risk olarak girer.
        # Nihai yanıt, doğrulama yoksa/başarısızsa kanıttan üretilir (aşağıda).
        if mode == "execute":
            for m in write_steps:
                if m.success and not m.changes:
                    record["remaining_issues"].append(
                        f"'{m.recipient}' adımı başarılı göründü ama hiçbir dosya "
                        "değiştirmedi (kanıtsız yazma)."
                    )

        # ---- Ana Yönetici için sonuç raporu -------------------------------
        report = self.build_report(record, step_results, task_type)
        record["report"] = report

        # ---- ANA YÖNETİCİ AJAN: rapor incelemesi + nihai yanıt -----------
        if via_main_manager:
            review = await self._run_step(
                task_id, f"{base_conv}-mm1", "mm1",
                {"role": "main-manager", "goal": "Kodlama Yöneticisi raporunu incele; test edilmemiş işi doğrulanmış sayma. Kullanıcıya net nihai yanıtı ve kalan riskleri yaz.", "write": False, "task_type": task_type.value},
                "plan", message,
                extra_context=json.dumps(report, ensure_ascii=False)[:4000],
            )
            record["messages"].append(asdict(review) | {"phase": "main-review"})
            record["final_answer"] = review.response or step_results[-1].response if step_results else ""
            record["review"] = {"verdict": "ONAY" if review.success else "INCELEME GEREKLİ",
                                "notes": review.response[:2000]}
        else:
            record["final_answer"] = step_results[-1].response if step_results else ""

        # LLM metni üretemediyse VEYA doğrulama başarısızsa VEYA hiç dosya
        # değişmediyse nihai yanıtı KANITTAN üret (uydurma yok).
        # Doğrulama exit!=0 iken LLM'in "tamam" metni geçersizdir.
        _v = record.get("verification") or {}
        _low = (record["final_answer"] or "").lower()
        _verify_failed = bool(_v.get("ran")) and _v.get("passed") is not True
        _no_changes = mode == "execute" and not record.get("files_changed")
        if ((not record["final_answer"].strip()) or _verify_failed or _no_changes
                or any(m in _low for m in _LLM_FAIL_MARKERS)):
            if _v.get("passed") is True:
                _files = ", ".join(record.get("files_changed") or []) or "yok"
                record["final_answer"] = (
                    "Görev tamamlandı (kanıtlı). "
                    f"Doğrulama: `{_v.get('command')}` → exit={_v.get('exit_code')}. "
                    f"Değişen dosyalar: {_files}."
                )
            elif _v.get("ran"):
                record["final_answer"] = (
                    "Görev tamamlanmadı: doğrulama "
                    f"`{_v.get('command')}` → exit={_v.get('exit_code')}."
                )
            elif _no_changes:
                record["final_answer"] = (
                    "Görev tamamlanmadı: hiçbir dosya oluşturulmadı/değiştirilmedi; "
                    "doğrulama komutu da yok."
                )
            else:
                record["final_answer"] = (
                    "Görev yürütüldü ancak LLM nihai metin üretemedi ve doğrulama komutu "
                    "yok; sonuç kanıtsız."
                )
            record["final_answer_note"] = "Nihai özet yalnızca gerçek kanıttan üretildi (LLM metni kullanılmadı)."

        if record["status"] == TaskStatus.RUNNING.value:
            record["status"] = TaskStatus.COMPLETED.value

        self._save_task(record)

        # ---- ÖĞRENME (otomatik, denetimli) --------------------------------
        # Görev geçmişinden deterministik içgörü üretir. LLM kullanmaz, kod/model/
        # güvenlik kuralı DEĞİŞTİRMEZ; yalnızca coding_insights.json yazar.
        # Hata olursa görev raporu yine döner (asla görevi düşürmez).
        insight_summary = self._refresh_insights()

        return {
            "success": record["status"] in (TaskStatus.COMPLETED.value, TaskStatus.TEST_FAILED.value),
            "task_id": task_id,
            "task_type": task_type.value,
            "mode": mode,
            "status": record["status"],
            "final_answer": record["final_answer"],
            "final_answer_note": record.get("final_answer_note"),
            "report": report,
            "review": record["review"],
            "insights": insight_summary,
        }

    # -- öğrenme döngüsü (otomatik, denetimli) -------------------------------
    @staticmethod
    def _auto_insights_enabled() -> bool:
        """NEXUS_AUTO_INSIGHTS=0/false/no/off ile kapatılabilir (varsayılan AÇIK)."""
        raw = (os.getenv("NEXUS_AUTO_INSIGHTS", "1") or "").strip().lower()
        return raw not in ("0", "false", "no", "off")

    @classmethod
    def _refresh_insights(cls) -> Dict[str, Any]:
        """
        Görev kaydından içgörü üretir (Öğrenme Ajanı'nın denetimli katmanı).

        * LLM KULLANMAZ; sonuç deterministik.
        * Yalnızca ``coding_insights.json`` yazar; ``applied`` daima ``False``.
        * Hiçbir kodu/modeli/güvenlik kuralını değiştirmez.
        """
        if not cls._auto_insights_enabled():
            return {"ok": True, "skipped": "NEXUS_AUTO_INSIGHTS kapalı", "applied": False}
        try:
            import coding_insights as cins

            result = cins.generate_insights()
            items = result.get("insights") or []
            proposal = getattr(cins, "STATUS_PROPOSAL", "oneri")
            return {
                "ok": True,
                "created": int(result.get("created", 0)),
                "total": int(result.get("total", len(items))),
                "tasks_analyzed": int(result.get("tasks_analyzed", 0)),
                "open": sum(1 for i in items if i.get("status") == proposal),
                "agent": "learning-agent",
                "applied": False,
            }
        except Exception as exc:  # öğrenme katmanı görevi asla düşürmez
            logger.warning("Otomatik içgörü üretilemedi: %s", exc)
            return {"ok": False, "error": type(exc).__name__, "applied": False}

    # -- yapılandırılmış rapor (11 alan) -----------------------------------
    @staticmethod
    def build_report(record: Dict[str, Any], step_results: List[TaskMessage],
                     task_type: TaskType) -> Dict[str, Any]:
        changed = sorted(set(record.get("files_changed") or []))
        tools = list(dict.fromkeys(record.get("tools_used", [])))
        verification = record.get("verification") or {}
        return {
            "1_gorev_kimligi": {
                "task_id": record["task_id"],
                "istek_ozeti": record["request"][:300],
                "gorev_turu": task_type.value,
                "mod": record["mode"],
            },
            "2_uygulanan_cozum": record.get("final_answer", "")[:1500],
            "3_kullanilan_uzmanlar": [m.recipient for m in step_results],
            "4_degistirilen_dosyalar": changed,
            "5_calistirilan_araclar": tools,
            "6_test_sonuclari": {
                "dogrulama": verification,
                "iddia_eden_adimlar": [m.recipient for m in step_results
                                       if m.recipient in ("test-engineer", "regression-tester")],
            },
            "7_inceleme_ve_guvenlik": [m.response[:600] for m in step_results
                                        if m.recipient in ("reviewer", "security", "evidence-auditor")],
            "8_basarisiz_islemler": [m.purpose for m in step_results if not m.success],
            "9_kalan_riskler": record.get("remaining_issues", []),
            "10_geri_donus_durumu": {
                "git_tag": "pre-coding-agents",
                "not": "Değişiklikler geri alınabilir; yedek geri dönüş noktası mevcut.",
            },
            "11_ana_yoneticiden_beklenen": "Raporu incele, gerekirse ek test/düzeltme iste, kullanıcıya sun.",
        }

    # -- kalıcılık ---------------------------------------------------------
    def _save_task(self, record: Dict[str, Any]) -> None:
        try:
            tasks = []
            if os.path.exists(TASKS_FILE):
                try:
                    with open(TASKS_FILE, "r", encoding="utf-8") as f:
                        tasks = json.load(f)
                except Exception:
                    tasks = []
            tasks.append(record)
            if len(tasks) > MAX_STORED_TASKS:
                tasks = tasks[-MAX_STORED_TASKS:]
            with open(TASKS_FILE, "w", encoding="utf-8") as f:
                json.dump(tasks, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.error("Görev kaydedilemedi: %s", exc)


# ============================================================
# MODÜL SEVİYESİ KISAYOLLAR
# ============================================================

_manager: Optional[CodingTaskManager] = None


def get_manager() -> CodingTaskManager:
    global _manager
    if _manager is None:
        _manager = CodingTaskManager()
    return _manager


async def run_coding_task(message: str, working_dir: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """working_dir verilirse o dizinde çalışan taze bir yönetici kullanılır."""
    if working_dir:
        return await CodingTaskManager(working_dir).run(message, **kwargs)
    return await get_manager().run(message, **kwargs)


def get_tasks() -> List[Dict[str, Any]]:
    if not os.path.exists(TASKS_FILE):
        return []
    try:
        with open(TASKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    for t in get_tasks():
        if t.get("task_id") == task_id:
            return t
    return None
