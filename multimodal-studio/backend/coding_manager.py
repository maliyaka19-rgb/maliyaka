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
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

try:
    from coding_knowledge import get_standards_for as _get_standards_for
except Exception:  # bilgi tabani yoksa sessizce gec (graceful)
    def _get_standards_for(_text: str) -> str:
        return ""

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
    PARTIAL = "kismi"
    BLOCKED = "engellendi"
    FAILED = "basarisiz"
    NEEDS_APPROVAL = "onay_bekliyor"


class StepStatus(str, Enum):
    PENDING = "bekliyor"
    RUNNING = "calisiyor"
    COMPLETED = "tamamlandi"
    PARTIAL = "kismi"
    BLOCKED = "engellendi"
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

# Sağlayıcı arızasında ai_agent'ın ürettiği yardımcı metin BAŞARI DEĞİLDİR.
_LOCAL_PROVIDER_FAILURE_MARKERS = (
    "yerel model (`",
    "su anda yanit uretemedi",
    "yerel model yanıt üretemedi",
)

# Doğrulama komutunda onaysız çalıştırılması yıkıcı olabilecek kalıplar.
_DANGEROUS_COMMAND_MARKERS = (
    "rm -rf", "rmdir /s", "del /s", "del /f", "format ", "diskpart",
    "shutdown", "reboot", "mkfs", "dd if=", ":(){", "fork bomb",
    "curl | sh", "curl | bash", "wget | sh", "wget | bash",
    "> /dev/sda", "chmod -r 777 /", "takeown /f",
)

# Sır taraması: değer rapora YAZILMAZ, yalnızca dosya/satır/tür raporlanır.
_SECRET_PATTERNS = (
    ("openrouter_key", re.compile(r"sk-or-v1-[A-Za-z0-9_-]{8,}")),
    ("generic_api_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("credential_literal", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|password|passwd|token)\b\s*[=:]\s*"
        r"[\"'][^\"'\s]{8,}[\"']"
    )),
)

_MAX_SCAN_BYTES = 1_000_000


def dangerous_verification_reason(command: str) -> Optional[str]:
    """Yıkıcı doğrulama komutunu tespit eder (açık onay olmadan engellenir)."""
    text = (command or "").casefold()
    for marker in _DANGEROUS_COMMAND_MARKERS:
        if marker in text:
            return f"Yıkıcı komut kalıbı engellendi: {marker!r}"
    return None


def scan_changed_files(files: List[str], working_dir: str) -> List[Dict[str, Any]]:
    """Değişen dosyalarda sır/anahtar sızıntısı arar.

    Yalnızca proje çalışma dizini içindeki düzenli dosyalar okunur. Bulunan
    sır değeri asla döndürülmez; yalnızca dosya, satır ve tür bildirilir.
    """
    findings: List[Dict[str, Any]] = []
    root = os.path.realpath(working_dir)
    root_prefix = root + os.sep
    for rel in files or []:
        candidate = rel if os.path.isabs(rel) else os.path.join(root, rel)
        path = os.path.realpath(candidate)
        if path != root and not path.startswith(root_prefix):
            continue
        if not os.path.isfile(path):
            continue
        try:
            if os.path.getsize(path) > _MAX_SCAN_BYTES:
                continue
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except Exception:
            continue
        rel_display = os.path.relpath(path, root).replace(os.sep, "/")
        for lineno, line in enumerate(lines, 1):
            for kind, pattern in _SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append({
                        "file": rel_display,
                        "line": lineno,
                        "kind": kind,
                        "severity": "critical" if kind in ("openrouter_key", "private_key") else "high",
                    })
                    break
    return findings


def compute_file_conflicts(step_results: List[TaskMessage]) -> List[Dict[str, Any]]:
    """Aynı dosyayı birden fazla farklı ajanın değiştirmesini raporlar."""
    owners: Dict[str, List[str]] = {}
    for msg in step_results:
        for path in msg.changes or []:
            owners.setdefault(path, []).append(msg.recipient)
    conflicts = []
    for path, agents in sorted(owners.items()):
        unique = sorted(set(agents))
        if len(unique) > 1:
            conflicts.append({"file": path, "agents": unique, "writes": len(agents)})
    return conflicts


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
    # Hızlı akış: yerel model her adımda bir LLM çağrısı yaptığı için adım
    # sayısı doğrudan görev süresidir. Akışlar 4-6 adıma sıkıştırıldı
    # (analiz + plan tek adımda); uzman kapsamı ve kalite kapıları korundu.
    TaskType.FEATURE: [
        {"role": "code-analyst", "goal": "İlgili dosyaları ve mevcut kod yapısını incele; alt görevleri, sırayı, değişiklik alanlarını ve kabul kriterlerini tek planda yaz.", "write": False},
        {"role": "coder", "goal": "İstenen özelliği mevcut kod standartlarına uygun şekilde geliştir; değişen dosyaları kaydet.", "write": True},
        {"role": "test-engineer", "goal": "Değişiklik için birim/entegrasyon testleri yaz ve çalıştır; gerçek çıktıyı raporla.", "write": True},
        {"role": "reviewer", "goal": "Değişikliği bağımsız incele; mantık hatası ve eksik test ara. Kanıtsız onay verme.", "write": False},
    ],
    TaskType.BUGFIX: [
        {"role": "debugger", "goal": "Hata mesajı/günlükleri ve hatayla ilgili kodu incele; kök nedeni bul (varsayımı bulgudan ayır).", "write": False},
        {"role": "bug-fixer", "goal": "Hedefe yönelik, ilgisiz koda dokunmayan güvenli düzeltme yap.", "write": True},
        {"role": "test-engineer", "goal": "Hatayı yeniden üreten test yaz, düzeltmeyi doğrula, gerçek çıktıyı raporla.", "write": True},
        {"role": "reviewer", "goal": "Düzeltmeyi bağımsız incele.", "write": False},
    ],
    TaskType.SECURITY: [
        {"role": "security", "goal": "Yetkilendirme, sırlar, kullanıcı verisi ve güvenilmeyen girdileri risk derecesiyle raporla.", "write": False},
        {"role": "bug-fixer", "goal": "Kritik güvenlik bulgularını en az yetkiyle düzelt.", "write": True},
        {"role": "test-engineer", "goal": "Güvenlik düzeltmesini doğrulayan test yaz/çalıştır.", "write": True},
        {"role": "reviewer", "goal": "Düzeltmeyi bağımsız incele.", "write": False},
    ],
    TaskType.PERFORMANCE: [
        {"role": "performance-pro", "goal": "Sıcak yollarda bellek/CPU/ağ ve yanıt süresi darboğazlarını KANITLA (ölçüm olmadan iddia etme).", "write": False},
        {"role": "optimizer", "goal": "Ölçülebilir fayda sağlayan optimizasyonu uygula; doğruluğu bozma.", "write": True},
        {"role": "test-engineer", "goal": "Optimizasyon sonrası testleri çalıştır ve çıktıyı raporla.", "write": True},
        {"role": "regression-tester", "goal": "Regresyon kontrolü yap.", "write": False},
    ],
    TaskType.API: [
        {"role": "task-planner", "goal": "API görevini alt görevlere böl; sözleşme ve kabul kriterlerini yaz.", "write": False},
        {"role": "architect", "goal": "API sözleşmesini, veri modellerini ve uç nokta tasarımını belirle.", "write": False},
        {"role": "backend-pro", "goal": "Sunucu/API uç noktasını doğrulama, hata yanıtları ve yetkilendirmeyle geliştir.", "write": True},
        {"role": "integrator", "goal": "Yeni uç noktayı arayüz/istemcilerle entegre et; veri formatı uyumunu kontrol et.", "write": True},
        {"role": "test-engineer", "goal": "Uçtan uca/entegrasyon testi yaz ve çalıştır.", "write": True},
        {"role": "docs-writer", "goal": "Yeni uç noktanın kullanım/teknik belgesini güncelle (olmayan özellik ekleme).", "write": True},
    ],
    TaskType.RESEARCH: [
        {"role": "architect", "goal": "Belirsiz teknik noktayı izinli kaynaklarla araştır; bulgu ile varsayımı ayır.", "write": False},
        {"role": "code-analyst", "goal": "Projede ilgili mevcut kodu incele.", "write": False},
        {"role": "coder", "goal": "Araştırma sonucuna göre en uygun çözümü uygula.", "write": True},
        {"role": "reviewer", "goal": "Sonucu bağımsız incele.", "write": False},
    ],
    TaskType.REFACTOR: [
        {"role": "code-analyst", "goal": "Kod kokusunu ve tekrarları tespit et.", "write": False},
        {"role": "optimizer", "goal": "Davranışı koruyarak yeniden düzenle (refactor).", "write": True},
        {"role": "test-engineer", "goal": "Refactor sonrası testleri çalıştır.", "write": True},
        {"role": "reviewer", "goal": "Bağımsız incele.", "write": False},
    ],
    TaskType.FRONTEND: [
        {"role": "code-analyst", "goal": "Mevcut arayüz kodunu ve bileşen yapısını incele.", "write": False},
        {"role": "frontend-pro", "goal": "İstenen arayüz değişikliğini erişilebilirlik ve mevcut stil kurallarına uygun uygula.", "write": True},
        {"role": "test-engineer", "goal": "Arayüz davranışını doğrulayan testi yaz/çalıştır; gerçek çıktıyı raporla.", "write": True},
        {"role": "reviewer", "goal": "Değişikliği bağımsız incele; kırık bağlantı ve erişilebilirlik sorunu ara.", "write": False},
    ],
    TaskType.DATABASE: [
        {"role": "database-pro", "goal": "Mevcut veri modelini ve sorguları incele; şema/migration değişikliğini geri alınabilir biçimde uygula.", "write": True},
        {"role": "test-engineer", "goal": "Veri katmanı testini yaz/çalıştır; gerçek çıktıyı raporla.", "write": True},
        {"role": "reviewer", "goal": "Veri kaybı ve geriye dönük uyumluluk riskini incele.", "write": False},
    ],
    TaskType.DEVOPS: [
        {"role": "dependency-analyst", "goal": "Çalışma zamanı/bağımlılık ve ortam gereksinimlerini çıkar.", "write": False},
        {"role": "devops", "goal": "Dağıtım/CI yapılandırmasını en az yetkiyle hazırla; sırları koda yazma.", "write": True},
        {"role": "test-engineer", "goal": "Yapılandırmayı doğrulayan komutu çalıştır; gerçek çıktıyı raporla.", "write": True},
        {"role": "reviewer", "goal": "Dağıtım risklerini (sır sızıntısı, eksik ortam değişkeni) incele.", "write": False},
    ],
    TaskType.GENERAL: [
        {"role": "code-analyst", "goal": "İlgili kodu incele ve durumu özetle.", "write": False},
        {"role": "coder", "goal": "İstenen değişikliği uygula.", "write": True},
        {"role": "reviewer", "goal": "Bağımsız incele.", "write": False},
    ],
}


def select_workflow(task_type: TaskType) -> List[Dict[str, Any]]:
    """Görev türüne karşılık gelen iş akışını döndürür (kopya)."""
    out = []
    for step in WORKFLOWS.get(task_type, WORKFLOWS[TaskType.GENERAL]):
        step = dict(step)
        # Salt-okuma (analiz) adimlari yerel model yanit uretemese bile
        # gorevi dusurmesin; yazma adimlari zorunlu kalir.
        if not step.get("write", False):
            step.setdefault("optional", True)
        out.append(step)
    return out


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
    """Ajanlar arası tek bir görev/sonuç mesajı.

    Alanlar master prompt sözleşmesini taşır: görev adı, bağımlılıklar,
    kabul ölçütleri, yetki sınırı, kanıt, kısmi/eksik iş ve seçili model.
    """
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
    task_name: str = ""
    dependencies: List[str] = field(default_factory=list)
    acceptance_criteria: List[str] = field(default_factory=list)
    known_risks: List[str] = field(default_factory=list)
    missing_work: List[str] = field(default_factory=list)
    contract_version: str = ""
    provider: str = ""
    model: str = ""


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
        contract = (role_agent or {}).get("contract") or {}
        contract_allows_write = contract.get("can_write", True) is not False
        can_write = bool(step.get("write")) and mode == "execute" and contract_allows_write
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
        from custom_agents import get_agent, get_agent_contract
        import ai_agent as _ai

        role = step["role"]
        agent = get_agent(role) or {}
        contract = get_agent_contract(role) or agent.get("contract") or {}
        tools = self.resolve_tools(agent, step, mode)
        # Salt-okuma (analiz) adimlarinda yerel modelin arac dongusune
        # girmesini ve bos yanit vermesini onlemek icin arac verilmez;
        # adimlar optional oldugundan basarisiz olsa bile gorev surer.
        if not step.get("write"):
            tools = []

        mode_note = (
            "ŞU AN 'PLAN' MODU: HİÇBİR dosyayı DEĞİŞTİRME/OLUŞTURMA; yalnızca "
            "analiz, plan veya önerilen değişikliği metin olarak sun."
            if mode != "execute" else
            "ŞU AN 'UYGULA' MODU: gerekli dosya değişikliklerini yapabilir ve "
            "komut çalıştırabilirsin. Dosya oluşturmak için write_file, mevcut "
            "dosyayı değiştirmek için edit_file aracını ÇAĞIR. generate_code "
            "dosyaya YAZMAZ (yalnızca kod önerisi üretir); kodu yanıt metnine "
            "dökme, gerçekten dosyayı yaz. Görevde birden fazla dosya isteniyorsa "
            "HEPSİNİ oluştur; her dosya için ayrı write_file çağrısı yap ve ilk "
            "dosyayla yetinme. Bitirmeden yanıt verme."
        )
        acceptance = list(contract.get("acceptance") or [])
        forbidden = list(contract.get("forbidden") or [])
        expected_output = (contract.get("outputs") or [step["goal"]])[0]
        contract_lines = "".join(f"- {item}\n" for item in acceptance) or "- Görev amacına ulaş.\n"
        forbidden_lines = "".join(f"- {item}\n" for item in forbidden) or "- Yetki sınırını aşma.\n"
        prefix = (
            f"[KODLAMA YÖNETİCİSİ GÖREVİ] Rol: {role}\n"
            f"Sözleşme: v{contract.get('version', '-')} | Kapsam: {contract.get('scope', '-')}\n"
            f"Görev türü: {step.get('task_type', '-')}\n"
            f"Amaç: {step['goal']}\n"
            f"Kabul ölçütleri:\n{contract_lines}"
            f"Yasaklar:\n{forbidden_lines}"
            f"Beklenen çıktı: {expected_output}\n"
            f"Kanıt zorunlu: {'evet' if contract.get('evidence_required', True) else 'hayır'}\n"
            f"{mode_note}\n"
            + _get_standards_for(task_request)
            + "\n"
        )
        prompt = (
            f"KULLANICI İSTEĞİ:\n{task_request}\n\n"
            f"BU ADIMDAKİ GÖREVİN:\n{step['goal']}\n"
            f"BEKLENEN ÇIKTI:\n{expected_output}\n"
            + (f"\nEK BAĞLAM:\n{extra_context}\n" if extra_context else "")
        )

        msg = TaskMessage(
            task_id=task_id, sender="coding-manager", recipient=role,
            purpose=step["goal"], status=StepStatus.RUNNING.value,
            expected_output=expected_output, files=list(step.get("files") or []),
            task_name=step.get("name") or step["goal"][:80],
            dependencies=list(step.get("depends_on") or []),
            acceptance_criteria=acceptance,
            known_risks=list(step.get("risks") or []),
            contract_version=str(contract.get("version", "")),
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
            msg.missing_work.append("Ajan çalıştırılamadı; adım tamamlanmadı.")
            msg.duration_ms = int((time.time() - started) * 1000)
            logger.error("Adım hatası (%s): %s", role, exc)
            return msg

        msg.duration_ms = int((time.time() - started) * 1000)
        msg.response = (result or {}).get("response") or ""
        msg.tools_used = list((result or {}).get("tools_used") or [])
        # Ajanın GERÇEKTEN yazdığı dosyalar (araç sonucundan; iddia değil).
        msg.changes = list((result or {}).get("files_changed") or [])
        msg.provider = (result or {}).get("provider") or ""
        msg.model = (result or {}).get("model") or ""
        msg.success = bool((result or {}).get("success"))
        msg.evidence = [f"dosya:{p}" for p in msg.changes]
        msg.evidence += [f"araç:{t}" for t in msg.tools_used]
        response_lower = msg.response.casefold()
        local_provider_failed = (
            "yerel model (`" in response_lower
            and any(marker in response_lower
                    for marker in _LOCAL_PROVIDER_FAILURE_MARKERS[1:])
        )
        if local_provider_failed:
            msg.success = False
            msg.status = StepStatus.FAILED.value
            msg.remaining_issues.append(
                "Seçili yerel model yanıt üretemedi; sağlayıcı arızası başarı sayılmaz."
            )
            msg.missing_work.append("Sağlayıcı yanıtı yok; adım tamamlanmadı.")
        elif msg.success:
            if mode == "execute" and step.get("write") and not msg.changes:
                msg.status = StepStatus.PARTIAL.value
                msg.missing_work.append(
                    "Yazma adımı başarılı göründü ancak hiçbir dosya değişmedi."
                )
            elif not msg.response.strip() and not msg.changes:
                msg.status = StepStatus.PARTIAL.value
                msg.missing_work.append("Ajan metin yanıtı ve dosya kanıtı üretmedi.")
            else:
                msg.status = StepStatus.COMPLETED.value
        else:
            msg.status = StepStatus.FAILED.value
            msg.remaining_issues.append((result or {}).get("error") or "bilinmeyen hata")
            msg.missing_work.append("Adım başarısız; bağımlı işler tamamlanmadı.")
        return msg

    # -- gerçek doğrulama komutu -------------------------------------------
    def run_verification(self, command: str, timeout: int = 240) -> Dict[str, Any]:
        """Kalite kapısı: doğrulama komutunu GERÇEKTEN çalıştırır.

        Çalışma dizini proje ile sınırlıdır. Açıkça yıkıcı komutlar, kullanıcı
        ``NEXUS_CODING_ALLOW_DANGEROUS=1`` vermedikçe engellenir.
        """
        command = (command or "").strip()
        if not command:
            return {"command": command, "ran": False, "passed": None,
                    "error": "Boş doğrulama komutu"}

        danger = dangerous_verification_reason(command)
        if danger and os.getenv("NEXUS_CODING_ALLOW_DANGEROUS", "0") != "1":
            return {
                "command": command,
                "ran": False,
                "passed": False,
                "blocked": True,
                "error": danger,
            }

        try:
            timeout = max(1, min(int(timeout), 600))
            proc = subprocess.run(
                command, shell=True, cwd=self.working_dir, timeout=timeout,
                check=False, capture_output=True, text=True, encoding="utf-8",
                errors="replace",
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

    @staticmethod
    def _apply_security_gate(record: Dict[str, Any]) -> None:
        """Kritik sır bulgusunu tamamlanmış görev olarak bırakmaz."""
        critical = [f for f in (record.get("security") or [])
                    if f.get("severity") == "critical"]
        if not critical:
            return
        record["status"] = TaskStatus.BLOCKED.value
        record["remaining_issues"].append(
            "Güvenlik kapısı: değişen dosyalarda kritik sır/anahtar kalıbı bulundu "
            f"({len(critical)} bulgu). Değerler rapora yazılmadı; dosyaları temizleyin."
        )

    @staticmethod
    def _is_build_like(message: str) -> bool:
        """İstek site/uygulama/proje inşası mı? (ai_agent niyet sınıflandırıcısı)"""
        try:
            from ai_agent import NexusAIAgent, _norm_tr

            return bool(NexusAIAgent._is_build_request(_norm_tr(message)))
        except Exception:
            return False

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
                  verify_command: Optional[str] = None, max_retries: int = 3,
                  parallel_analysis: bool = False) -> Dict[str, Any]:
        message = (message or "").strip()
        if not message:
            raise ValueError("Boş görev")

        # Master prompt sınırı: en fazla 3 düzeltme denemesi.
        max_retries = max(0, min(int(max_retries), 3))

        approval_note = None
        if mode == "execute" and not confirm:
            approval_note = "execute modu için onay verilmedi; güvenli 'plan' moduna alındı."
            logger.warning(approval_note)
            mode = "plan"

        task_id = str(uuid.uuid4())[:12]
        base_conv = conversation_id or f"coding-{task_id}"
        task_type = classify_task(message)
        steps = select_workflow(task_type)
        previous_role: Optional[str] = None
        for s in steps:
            s["task_type"] = task_type.value
            # Bağımlılık: yazma adımları kendinden önceki yazma adımına bağlıdır.
            # Analiz adımları bağımsızdır (paralel çalışabilir).
            s["depends_on"] = [previous_role] if (s.get("write") and previous_role) else []
            if s.get("write"):
                previous_role = s["role"]

        # Seçili model/sağlayıcı, görev kaydına ve rapora girer.
        selected = {}
        try:
            from model_routes import _load_config
            cfg = _load_config()
            selected = {
                "provider": cfg.get("active_provider"),
                "model": cfg.get("active_model"),
            }
        except Exception:
            selected = {"provider": None, "model": None}

        logger.info("Kodlama görevi %s: tür=%s, adım=%d, mod=%s, model=%s",
                    task_id, task_type.value, len(steps), mode,
                    selected.get("model"))

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
            "security": [],
            "final_answer": "",
            "remaining_issues": [],
            "roles": [s["role"] for s in steps],
            "workflow": [{"role": s["role"], "goal": s["goal"],
                          "write": bool(s.get("write")),
                          "depends_on": s.get("depends_on", [])} for s in steps],
            "selected_provider": selected.get("provider"),
            "selected_model": selected.get("model"),
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
                        if not r.success:
                            record["status"] = TaskStatus.FAILED.value
                            record["remaining_issues"].append(
                                f"Adım başarısız: {r.recipient}"
                            )
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
            elif rm.status == StepStatus.PARTIAL.value:
                if step.get("write") and mode == "execute":
                    if record["status"] == TaskStatus.RUNNING.value:
                        record["status"] = TaskStatus.PARTIAL.value
                    record["remaining_issues"].extend(
                        f"{step['role']}: {item}" for item in rm.missing_work
                    )
            i += 1

        record["conflicts"].extend(self.locks.conflicts)
        record["conflicts"].extend(compute_file_conflicts(step_results))
        record["tools_used"] = list(dict.fromkeys(record["tools_used"]))
        record["files_changed"] = list(dict.fromkeys(record["files_changed"]))

        # Değişen dosyalarda sır/anahtar taraması (değer sızdırmadan).
        record["security"] = scan_changed_files(record["files_changed"], self.working_dir)
        self._apply_security_gate(record)

        # ---- BUILD FALLBACK (deterministik proje üretimi) ------------------
        # Uzman kodlayıcı write_file çağrısını yapamadıysa (küçük yerel
        # modellerde sık) site/uygulama isteklerini boşa düşürme: dosyaları
        # deterministik üretici yazar. Önceki "0 dosya" gürültüsü temizlenir.
        if (mode == "execute" and not record["files_changed"]
                and self._is_build_like(message)):
            try:
                from ai_agent import get_agent_v6

                agent = get_agent_v6()
                bf = await agent._smart_build_or_edit(message, "")
            except Exception as exc:
                bf = None
                logger.warning("Kodlama zinciri build fallback hatası: %s", exc)
            if bf:
                record["files_changed"] = list(dict.fromkeys(
                    record["files_changed"] + list(bf.get("files") or [])
                ))
                record["remaining_issues"] = [
                    x for x in record["remaining_issues"]
                    if ("dosya değişmedi" not in x and "hiçbir dosya" not in x)
                ]
                record.setdefault("notes", []).append(
                    "Uzman kodlayıcı write_file çağrısını yapamadı; "
                    "deterministik proje üreticisi dosyaları yazdı."
                )
                if record.get("status") in (
                    TaskStatus.RUNNING.value, TaskStatus.PARTIAL.value,
                    TaskStatus.FAILED.value,
                ) and not [f for f in (record.get("security") or [])
                           if f.get("severity") == "critical"]:
                    record["status"] = TaskStatus.COMPLETED.value
                record["security"] = scan_changed_files(
                    record["files_changed"], self.working_dir
                )
                self._apply_security_gate(record)

        # ---- KALİTE KAPISI: gerçek doğrulama komutu -----------------------
        if verify_command:
            attempt = 0
            while True:
                # Senkron alt süreç olay döngüsünü KİLİTLEMESİN: aksi halde
                # doğrulama komutu (ör. pytest, timeout=600s) çalıştığı süre
                # boyunca TÜM arayüz (login/sohbet/health) donuyordu.
                verification = await asyncio.to_thread(
                    self.run_verification, verify_command)
                record["verification"] = verification
                if verification.get("passed"):
                    # Daha önce başarısız bir uzman adımı varsa test geçse
                    # bile görev tamamlanmış sayılmaz.
                    if record["status"] in (TaskStatus.RUNNING.value,
                                            TaskStatus.PARTIAL.value,
                                            TaskStatus.TEST_FAILED.value):
                        record["status"] = TaskStatus.COMPLETED.value
                elif verification.get("blocked"):
                    record["status"] = TaskStatus.BLOCKED.value
                else:
                    record["status"] = TaskStatus.TEST_FAILED.value
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
                if mode == "execute" and write_steps and not record["files_changed"]:
                    record["status"] = TaskStatus.PARTIAL.value
                    record["remaining_issues"].append(
                        "Uygulama modunda hiçbir dosya değişmedi; test/doğrulama "
                        "kanıtı da yok. Görev tamamlanmış sayılmadı."
                    )
                else:
                    record["status"] = TaskStatus.COMPLETED.value

        # Yeniden denemeler yeni dosya değiştirmiş olabilir; taramayı tazele.
        if record["files_changed"]:
            record["files_changed"] = list(dict.fromkeys(record["files_changed"]))
            record["security"] = scan_changed_files(
                record["files_changed"], self.working_dir
            )
            self._apply_security_gate(record)

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

        # ---- Deterministik karar kapısı ------------------------------------
        verdict = self.deterministic_verdict(record, step_results)
        record["verdict"] = verdict

        # ---- Ana Yönetici için sonuç raporu -------------------------------
        report = self.build_report(record, step_results, task_type)
        record["report"] = report

        # ---- ANA YÖNETİCİ AJAN: rapor incelemesi + nihai yanıt -----------
        if via_main_manager:
            review_context = json.dumps(
                {"deterministik_karar": verdict, "rapor": report},
                ensure_ascii=False,
            )[:5000]
            review = await self._run_step(
                task_id, f"{base_conv}-mm1", "mm1",
                {"role": "main-manager",
                 "goal": "Kodlama Yöneticisi raporunu ve deterministik kararı incele; "
                         "test edilmemiş işi doğrulanmış sayma. Kullanıcıya net nihai "
                         "yanıtı ve kalan riskleri yaz.",
                 "write": False, "task_type": task_type.value},
                "plan", message, extra_context=review_context,
            )
            record["messages"].append(asdict(review) | {"phase": "main-review"})
            record["final_answer"] = (
                review.response
                or (step_results[-1].response if step_results else "")
            )
            record["review"] = {
                "verdict": verdict["verdict"],
                "passed": verdict["passed"],
                "reasons": verdict["reasons"],
                "evidence": verdict["evidence"],
                "llm_review_ok": bool(review.success),
                "notes": (review.response or "")[:2000],
            }
        else:
            record["final_answer"] = step_results[-1].response if step_results else ""
            record["review"] = {
                "verdict": verdict["verdict"],
                "passed": verdict["passed"],
                "reasons": verdict["reasons"],
                "evidence": verdict["evidence"],
                "llm_review_ok": None,
                "notes": "",
            }

        # LLM metni üretemediyse VEYA deterministik karar onay vermediyse
        # nihai yanıtı KANITTAN üret (uydurma yok). LLM'in "tamam" metni,
        # test/kanıt kapısı geçmedikçe geçerli değildir.
        _v = record.get("verification") or {}
        _low = (record["final_answer"] or "").lower()
        _force_evidence_answer = (
            not record["final_answer"].strip()
            or not verdict["passed"]
            or any(m in _low for m in _LLM_FAIL_MARKERS)
        )
        if _force_evidence_answer:
            files = ", ".join(record.get("files_changed") or []) or "yok"
            if verdict["passed"] and _v.get("passed") is True:
                record["final_answer"] = (
                    "Görev tamamlandı (kanıtlı). "
                    f"Doğrulama: `{_v.get('command')}` → exit={_v.get('exit_code')}. "
                    f"Değişen dosyalar: {files}."
                )
            elif verdict["verdict"] == "PLAN_ONAYLANDI":
                record["final_answer"] = (
                    "Plan tamamlandı; uygulama ve test kanıtı yok. "
                    "Uygulamak için `mode=execute` ve onay gerekir."
                )
            elif _v.get("blocked"):
                record["final_answer"] = (
                    "Görev engellendi: doğrulama komutu güvenlik nedeniyle "
                    f"çalıştırılmadı ({_v.get('error', 'yıkıcı komut')})."
                )
            elif _v.get("ran") and _v.get("passed") is not True:
                record["final_answer"] = (
                    "Görev tamamlanmadı: doğrulama "
                    f"`{_v.get('command')}` → exit={_v.get('exit_code')}."
                )
            else:
                record["final_answer"] = (
                    "Görev tamamlanmadı veya kısmi: gerçek test/doğrulama kanıtı yok. "
                    f"Değişen dosyalar: {files}. Riskler: "
                    + ("; ".join(record.get("remaining_issues") or []) or "yok")
                )
            record["final_answer_note"] = (
                "Nihai özet yalnızca deterministik kanıt ve karar kapısından "
                "üretildi (LLM metni kullanılmadı)."
            )

        if record["status"] == TaskStatus.RUNNING.value:
            record["status"] = TaskStatus.COMPLETED.value

        # Rapor, nihai yanıt ve karar sonrası son haliyle yeniden üretilir.
        report = self.build_report(record, step_results, task_type)
        record["report"] = report
        self._save_task(record)

        # ---- ÖĞRENME (otomatik, denetimli) --------------------------------
        # Görev geçmişinden deterministik içgörü üretir. LLM kullanmaz, kod/model/
        # güvenlik kuralı DEĞİŞTİRMEZ; yalnızca coding_insights.json yazar.
        # Hata olursa görev raporu yine döner (asla görevi düşürmez).
        insight_summary = self._refresh_insights()

        review_passed = bool((record.get("review") or {}).get("passed"))
        verification = record.get("verification") or {}
        verified = bool(
            verification.get("passed") is True
            and record["status"] == TaskStatus.COMPLETED.value
            and mode == "execute"
        )
        return {
            "success": record["status"] == TaskStatus.COMPLETED.value and review_passed,
            "verified": verified,
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
    def deterministic_verdict(record: Dict[str, Any],
                              step_results: List[TaskMessage]) -> Dict[str, Any]:
        """Ana Yönetici kararını LLM iddiasından değil kanıttan üretir."""
        status = record.get("status")
        mode = record.get("mode")
        verification = record.get("verification") or {}
        reasons: List[str] = []
        evidence: List[str] = []

        if status in (TaskStatus.FAILED.value, TaskStatus.BLOCKED.value):
            reasons.append(f"Görev durumu: {status}")
            return {"verdict": "REDDEDILDI", "passed": False,
                    "reasons": reasons, "evidence": evidence}

        if status == TaskStatus.TEST_FAILED.value:
            reasons.append(
                "Doğrulama komutu başarısız: "
                f"exit={verification.get('exit_code')}"
            )
            return {"verdict": "REDDEDILDI", "passed": False,
                    "reasons": reasons, "evidence": evidence}

        if verification.get("passed") is True:
            evidence.append(
                f"doğrulama exit=0 ({verification.get('command', '-')})"
            )
            if record.get("files_changed"):
                evidence.append(
                    "değişen dosya: " + ", ".join(record["files_changed"])
                )
                return {"verdict": "ONAYLANDI", "passed": True,
                        "reasons": reasons, "evidence": evidence}
            if mode == "plan":
                return {"verdict": "PLAN_ONAYLANDI", "passed": True,
                        "reasons": ["Plan modu; dosya değişikliği beklenmez."],
                        "evidence": evidence}
            reasons.append("Doğrulama geçti ancak dosya değişikliği kanıtı yok.")
            return {"verdict": "KISMI", "passed": False,
                    "reasons": reasons, "evidence": evidence}

        if mode == "plan":
            failed = [m.recipient for m in step_results if not m.success]
            if failed:
                reasons.append("Başarısız uzman adımları: " + ", ".join(failed))
                return {"verdict": "REDDEDILDI", "passed": False,
                        "reasons": reasons, "evidence": evidence}
            return {"verdict": "PLAN_ONAYLANDI", "passed": True,
                    "reasons": ["Plan modu; tüm uzman adımları yanıt üretti. Uygulama/test kanıtı yok."],
                    "evidence": evidence}

        if status == TaskStatus.PARTIAL.value:
            reasons.append("Görev kısmi: yazma ve/veya doğrulama kanıtı eksik.")
            return {"verdict": "KISMI", "passed": False,
                    "reasons": reasons, "evidence": evidence}

        reasons.append("Gerçek doğrulama komutu çalıştırılmadı; sonuç kanıtsız.")
        return {"verdict": "KISMI", "passed": False,
                "reasons": reasons, "evidence": evidence}

    @staticmethod
    def build_report(record: Dict[str, Any], step_results: List[TaskMessage],
                     task_type: TaskType) -> Dict[str, Any]:
        changed = sorted(set(record.get("files_changed") or []))
        tools = list(dict.fromkeys(record.get("tools_used", [])))
        verification = record.get("verification") or {}
        issues = list(dict.fromkeys(record.get("remaining_issues") or []))
        security = record.get("security") or []
        conflicts = record.get("conflicts") or []
        verdict = record.get("verdict") or record.get("review") or {}
        failed = [
            {"agent": m.recipient, "status": m.status, "purpose": m.purpose,
             "missing_work": m.missing_work}
            for m in step_results if not m.success or m.status != StepStatus.COMPLETED.value
        ]
        return {
            "1_gorev_kimligi": {
                "task_id": record["task_id"],
                "istek_ozeti": record["request"][:300],
                "gorev_turu": task_type.value,
                "mod": record["mode"],
                "durum": record.get("status"),
                "deneme": record.get("retries", 0),
                "azami_duzeltme": record.get("max_retries", 0),
            },
            "2_uygulanan_cozum": record.get("final_answer", "")[:1500],
            "3_kullanilan_uzmanlar": [m.recipient for m in step_results],
            "4_degistirilen_dosyalar": changed,
            "5_calistirilan_araclar": tools,
            "6_test_sonuclari": {
                "dogrulama": verification,
                "iddia_eden_adimlar": [m.recipient for m in step_results
                                       if m.recipient in ("test-engineer", "regression-tester")],
                "deterministik_karar": verdict,
            },
            "7_inceleme_ve_guvenlik": {
                "inceleme_notlari": [m.response[:600] for m in step_results
                                     if m.recipient in ("reviewer", "security")],
                "sir_taramasi": security,
                "guvenlik_engeli": [f for f in security
                                    if f.get("severity") == "critical"],
            },
            "8_basarisiz_islemler": failed,
            "9_kalan_riskler": issues,
            "10_geri_donus_durumu": {
                "git_tag": "pre-coding-agents",
                "not": "Değişiklikler geri alınabilir; yedek geri dönüş noktası mevcut.",
                "degisen_dosyalar": changed,
            },
            "11_ana_yoneticiden_beklenen": (
                "Raporu ve deterministik kararı incele; onay yoksa doğrulanmış "
                "sayma, gerekirse ek test/düzeltme iste, kullanıcıya sun."
            ),
            "12_model_ve_saglayici": {
                "saglayici": record.get("selected_provider"),
                "model": record.get("selected_model"),
                "adim_modeli": next((m.model for m in step_results if m.model), None),
                "adim_saglayicisi": next((m.provider for m in step_results if m.provider), None),
            },
            "13_kanit_ozeti": {
                "durum": record.get("status"),
                "karar": verdict.get("verdict") if isinstance(verdict, dict) else verdict,
                "degisen_dosya_sayisi": len(changed),
                "calistirilan_arac_sayisi": len(tools),
                "dogrulama_calisti": bool(verification.get("ran")),
                "dogrulama_gecti": verification.get("passed"),
                "dogrulanmis": bool(
                    verification.get("passed") is True
                    and record.get("status") == TaskStatus.COMPLETED.value
                    and record.get("mode") == "execute"
                ),
                "cakismalar": conflicts,
                "kritik_guvenlik_bulgusu": len([
                    f for f in security if f.get("severity") == "critical"
                ]),
            },
            "14_akis": record.get("workflow", []),
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
