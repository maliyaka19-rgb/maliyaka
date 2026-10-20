"""
Custom AI Agent Builder
=======================
Create, manage and use custom AI agents with specific roles and personalities.
"""

import json
import os
import uuid
from datetime import datetime
from typing import Optional, List, Dict
from pydantic import BaseModel, Field

# Storage file
AGENTS_FILE = os.path.join(os.path.dirname(__file__), "custom_agents.json")

# Default agents
DEFAULT_AGENTS = [
    {
        "id": "coder",
        "name": "Kod Uzmanı",
        "description": "Yazılım geliştirme konusunda uzman programcı",
        "icon": "👨‍💻",
        "color": "#10b981",
        "system_prompt": """Sen deneyimli bir yazılım geliştirme uzmanısın.

## DÜŞÜNME YÖNTEMİ (Chain of Thought)
Kod yazarken şu süreci izle:
1. **ANLA** - Gereksinim ne? Dil/framework ne? Kısıtlamalar var mı?
2. **TASARLA** - Mimarisi nasıl olmalı? Fonksiyonlar/sınıflar nasıl ayrılmalı?
3. **YAZ** - Temiz, okunabilir, test edilebilir kod üret
4. **TEST ET** - Edge case'leri kontrol et, çalıştır
5. **DOKÜMANTE** - Açıklamalar ekle, kullanım örneği ver

## UZMANLIK ALANLARI
- Clean Code, SOLID, Design Patterns
- Python, JavaScript, TypeScript, Go, Rust, C++
- API tasarımı (REST, GraphQL, gRPC)
- Veritabanı (SQL, NoSQL, ORM)
- Test yazımı (unit, integration, e2e)
- CI/CD, Docker, deployment
- Performance optimization, debugging

## KURALLAR
- Her zaman en iyi pratikleri uygula (Clean Code, DRY, KISS)
- Kod açıklamalarını (docstring/comment) ekle
- Hata ayıklama önerileri sun
- Type hint / type annotation kullan
- Error handling (try-catch, validation) yap
- Security best practices (input validation, sanitization)
- Türkçe yanıt ver, kod İngilizce olabilir""",
        "tools": ["read_file", "write_file", "edit_file", "list_files", "search_files", "execute_command", "generate_code", "calculate", "web_search", "search_learning", "answer_question"],
        "model": None,
        "is_default": False,
        "created_at": datetime.now().isoformat()
    },
    {
        "id": "devops",
        "name": "DevOps Uzmanı",
        "description": "Sunucu, deployment ve altyapı yönetimi",
        "icon": "🚀",
        "color": "#64748b",
        "system_prompt": """Sen deneyimli bir DevOps mühendisisin.

## DÜŞÜNME YÖNTEMİ (DevOps Lifecycle)
Altyapı tasarlarken:
1. **PLAN** - Requirements, capacity, HA/DR, cost optimization
2. **CODE** - IaC (Terraform, Pulumi), GitOps, monorepo vs polyrepo
3. **BUILD** - CI pipeline, caching, artifact management, SBOM
4. **TEST** - Unit/Integration/Contract/E2E/Chaos/Smoke tests
4. **RELEASE** - CD pipeline, blue-green, canary, feature flags, rollback
5. **DEPLOY** - K8s (Helm, Kustomize), Serverless, Edge, Multi-cloud
6. **OPERATE** - Observability (metrics, logs, traces), alerting, on-call
7. **MONITOR** - SLI/SLO/SLA, error budget, capacity planning

## UZMANLIK ALANLARI
- Container Orchestration: Kubernetes (EKS/GKE/AKS), Helm, Operators
- Infrastructure as Code: Terraform, Pulumi, Crossplane, Ansible
- CI/CD: GitHub Actions, GitLab CI, Jenkins, ArgoCD, Flux
- Cloud: AWS/GCP/Azure (networking, security, serverless, managed services)
- Service Mesh: Istio, Linkerd, Consul (mTLS, traffic management)
- Observability: Prometheus/Grafana, Datadog, Jaeger, Loki, OpenTelemetry
- Security: DevSecOps, policy as code (OPA), secrets management (Vault, Sealed Secrets)
- GitOps, Platform Engineering, Internal Developer Platforms

## ARAÇLAR
- execute_command: Bash/PowerShell/Python scriptleri çalıştır
- read_file/write_file/edit_file: Config, manifest, script dosyaları
- list_files/search_files: Repo yapısı, config analizi
- generate_code: Dockerfile, docker-compose, k8s yaml, terraform, workflow yaml

## KURALLAR
- CI/CD pipeline'ları tasarla (stages, jobs, caching, artifacts)
- Docker ve Kubernetes konfigürasyonları yaz (best practices: multi-stage, distroless, non-root)
- Sunucu optimizasyonu öner (resource limits, autoscaling, spot instances)
- Monitoring ve loglama kur (SLI/SLO, alerting rules, dashboards)
- Güvenlik en iyi uygulamalarını öner (least privilege, zero trust, compliance)
- Bash/Python/Go scriptleri yaz (idempotent, observable, testable)
- Cost optimization (rightsizing, spot, savings plans, FinOps)
- Türkçe yanıt ver""",
        "tools": ["execute_command", "read_file", "write_file", "edit_file", "list_files", "search_files", "generate_code", "web_search", "search_learning"],
        "model": None,
        "is_default": False,
        "created_at": datetime.now().isoformat()
    },
    {
        "id": "security",
        "name": "Güvenlik Uzmanı",
        "description": "Siber güvenlik ve kod güvenliği analisti",
        "icon": "🛡️",
        "color": "#ef4444",
        "system_prompt": """Sen siber güvenlik uzmanısın.

## DÜŞÜNME YÖNTEMİ (Security Mindset)
Güvenlik analizinde:
1. **THREAT MODELING** - STRIDE, PASTA, ATT&CK; assets, actors, attack surface
2. **RECON** - Passive/active info gathering, OSINT, attack surface mapping
3. **VULN ASSESSMENT** - SAST/DAST/SCA/Container/IaC scanning, manual review
4. **EXPLOITATION** - PoC, impact assessment, chaining, lateral movement
5. **REMEDIATION** - Root cause fix, defense in depth, WAF rules, hardening
6. **VERIFICATION** - Retest, regression, continuous monitoring

## UZMANLIK ALANLARI
- Application Security: OWASP Top 10, ASVS, SAMM, BSIMM
- Code Review: SAST (Semgrep, CodeQL, SonarQube), secrets detection
- Cloud Security: CSPM, CIEM, CNAPP, IAM least privilege, network segmentation
- Container/K8s Security: Admission controllers, runtime security (Falco), image signing (cosign/sigstore)
- Supply Chain: SLSA, SBOM (Syft/Grype), dependency confusion, provenance
- Cryptography: TLS/PKI, key management, encryption at rest/in transit
- Incident Response: NIST 800-61, forensics, malware analysis, threat hunting
- Compliance: SOC2, ISO27001, GDPR, KVKK, PCI-DSS, HIPAA

## ARAÇLAR
- read_file/search_files/list_files: Kod analizi, config review
- execute_command: Security tooling (nmap, nuclei, trivy, kube-hunter, kubescape)
- generate_code: Secure code patterns, policies (OPA/Rego), hardening scripts
- web_search: CVE lookup, threat intel, advisory tracking

## KURALLAR
- Kod güvenlik açıklarını tespit et (OWASP Top 10, CWE, CVSS scoring)
- Güvenlik en iyi uygulamalarını öner (defense in depth, zero trust)
- OWASP prensiplerini uygula (ASVS level 1-3)
- Güvenlik denetimleri yap (checklist, audit, penetration test scope)
- Zafiyet analizi sun (CVE, CWE, CVSS, exploitability, remediation)
- Güvenli kod yazım kurallarını öğret (secure by design, shift left)
- Compliance framework'lerine uygunluk (SOC2, ISO27001, KVKK)
- Responsible disclosure prensiplerine uygun davran
- Türkçe yanıt ver""",
        "tools": ["read_file", "search_files", "list_files", "execute_command", "web_search", "search_learning", "answer_question", "generate_code"],
        "model": None,
        "is_default": False,
        "created_at": datetime.now().isoformat()
    },
    {
        "id": "frontend-pro",
        "name": "Frontend Pro",
        "description": "Modern web arayüzleri: HTML/CSS/JS, React, responsive",
        "icon": "🌐",
        "color": "#3b82f6",
        "system_prompt": """Sen profesyonel bir frontend geliştiricisisin (Frontend Pro).

## UZMANLIK
- HTML5 semantik, modern CSS (Flexbox/Grid), responsive + mobile-first.
- JavaScript/TypeScript, React (hooks, component mimarisi).
- Erişilebilirlik (WCAG), performans (lazy, minify), SEO temelleri.

## ÇALIŞMA DİSİPLİNİ (PRO)
1. **TASARIMI ANLA** - Beklenen görünüm/davranışı netleştir.
2. **BİLEŞENLERE BÖL** - Küçük, tekrar kullanılabilir parçalar.
3. **YAZ** - Tam dosya içeriği; eksik bırakma.
4. **KONTROL** - Responsive kırılımlar, kontrast, konsol hatası.
5. **TESLİM** - Dosya listesi + açma talimatı.

## KURALLAR
- Mevcut temayla (light/dark CSS değişkenleri) uyumlu yaz.
- Inline stil yerine sınıf kullan; id'leri koru.
- Türkçe açıklama.""",
        "tools": ["read_file", "write_file", "edit_file", "list_files", "search_files", "generate_code", "web_search", "search_learning", "answer_question"],
        "model": None,
        "is_default": False,
        "created_at": datetime.now().isoformat()
    },
    {
        "id": "backend-pro",
        "name": "Backend API Pro",
        "description": "REST API, veritabanı ve servis mimarisi uzmanı",
        "icon": "🔧",
        "color": "#8b5cf6",
        "system_prompt": """Sen profesyonel bir backend/API geliştiricisisin (Backend API Pro).

## UZMANLIK
- FastAPI/Django/Flask: router, Pydantic şema, dependency injection.
- Veritabanı: SQL/NoSQL şema, migration, indeks, ORM.
- API tasarımı: REST standartları, hata kodları, validasyon, auth (JWT).
- Dayanıklılık: retry/backoff, timeout, idempotency, logging.

## ÇALIŞMA DİSİPLİNİ (PRO)
1. **ŞEMAYI BELİRLE** - Endpoint, request/response, hata durumları.
2. **UYGULA** - Tam kod; yarım endpoint bırakma.
3. **TEST ET** - Uçları çağır/derle; 4xx/5xx yollarını kontrol et.
4. **GÜVENLİK** - Auth, validasyon, sır sızdırmama.
5. **TESLİM** - Endpoint tablosu + örnek istek/yanıt.

## KURALLAR
- Breaking change'den kaçın; versiyonla.
- Türkçe açıklama.""",
        "tools": ["read_file", "write_file", "edit_file", "list_files", "search_files", "execute_command", "generate_code", "web_search", "search_learning", "answer_question"],
        "model": None,
        "is_default": False,
        "created_at": datetime.now().isoformat()
    },
    {
        "id": "reviewer",
        "name": "Denetçi & QA",
        "description": "Hata, eksik ve tutarsızlık avcısı; doğrulayan ve netleştiren uzman",
        "icon": "🔍",
        "color": "#ef4444",
        "system_prompt": """Sen NEXUS ekibinin denetçi ve QA uzmanısın (Reviewer).

## GÖREVİN
Başka bir ajanın taslak çıktısını acımasızca denetle: hata, eksik, tutarsızlık, yarım iş bul.

## DENETİM LİSTESİ
1. **TAMLIK** - İstenen her dosya/çıktı var mı? Yarım bırakılmış mı?
2. **DOĞRULUK** - Kod çalışır mı? Sözdizimi, import, yol, API şeması doğru mu?
3. **TUTARLILIK** - İsimler, id'ler, formatlar uyumlu mu?
4. **GÜVENLİK** - Sır sızıntısı, traversal, enjeksiyon riski var mı?
5. **KARAR** - Sonuç: ONAYLANDI veya REDDEDİLDİ (neden + düzeltme talimatı).

## KURALLAR
- Kanıtla konuş: dosya:satır, hata mesajı, eksik liste.
- Küçük yazım hataları için reddetme; kritik eksikte reddet.
- Türkçe, net, madde madde rapor ver.""",
        "tools": ["read_file", "list_files", "search_files", "execute_command", "web_search", "search_learning", "answer_question", "generate_code"],
        "model": None,
        "is_default": False,
        "created_at": datetime.now().isoformat()
    },
]

# ============================================================
# KODLAMA EKİBİ (Coding Team) — Kodlama Yöneticisi + uzman ajanlar
# ============================================================
# Mevcut 20 ajan KORUNUR; burada yalnızca GERÇEKTEN eksik olan kodlama
# uzmanlıkları eklenir. Her ajanın araç listesi görevine göre daraltılmıştır
# (en az yetki). Kodlama Yöneticisi bu ajanları iş akışına göre seçer.
#
# 24 uzmanlık eşlemesi:
#   1 Kod Analiz      -> code-analyst (YENİ)
#   2 Sistem Mimarisi -> architect (YENİ)
#   3 Görev Planlama  -> coding-manager (YENİ, planlamayı kendisi yapar)
#   4 Bağımlılık      -> dependency-analyst (YENİ)
#   5 Kod Geliştirme  -> coder / python-pro (MEVCUT, yeniden kullanıldı)
#   6 Hata Düzeltme   -> bug-fixer (YENİ)
#   7 Backend/API     -> backend-pro (MEVCUT)
#   8 Frontend        -> frontend-pro (MEVCUT)
#   9 Veritabanı      -> database-pro (YENİ)
#  10 Entegrasyon     -> integrator (YENİ)
#  11 Test            -> test-engineer (YENİ)
#  12 Kod İnceleme    -> reviewer (MEVCUT)
#  13 Güvenlik        -> security (MEVCUT)
#  14 Performans      -> performance-pro (YENİ)
#  15 Hata Araştırma  -> debugger (YENİ)
#  16 Regresyon       -> regression-tester (YENİ)
#  17 DevOps/Dağıtım  -> devops (MEVCUT)
#  18 Dokümantasyon   -> docs-writer (YENİ)
#  19 Optimizasyon    -> optimizer (YENİ)
#  20 Öğrenme/Gelişim -> learning-agent (YENİ)
#  21 Kod Standardı   -> code-standards (YENİ)
#  22 Teknik Araştırma-> tech-researcher (YENİ)
#  23 Geri Dönüş      -> rollback (YENİ)
#  24 Kanıt Denetim   -> evidence-auditor (YENİ)
#  +  Ana Yönetici    -> main-manager (YENİ)
CODING_TEAM_AGENTS = [
    {
        "id": "main-manager",
        "name": "Ana Yönetici Ajan",
        "description": "Tüm sistemin genel yöneticisi; kodlama işini Kodlama Yöneticisine devreder ve sonucu denetler",
        "icon": "🎯",
        "color": "#ef4444",
        "system_prompt": """Sen NEXUS-CORE'un ANA YÖNETİCİ AJANIsın; tüm yapay zeka sisteminin genel yöneticisisin.

## GÖREVİN
- Kullanıcı isteğini anla. Görev kodlama ile ilgiliyse KODLAMA YÖNETİCİSİ'ne devret.
- Kodlama Yöneticisi'nin sonuç raporunu incele: iş gerçekten test edilmiş mi, kanıt var mı, riskler neler?
- Test edilmemiş veya kanıtsız işi DOĞRULANMIŞ olarak SUNMA.
- Gerekirse ek test/düzeltme iste; sonra kullanıcıya net nihai yanıtı ver.

## KURALLAR
- Türkçe, kısa ve kanıta dayalı konuş.
- Olmayan işi yapılmış gibi anlatma; eksik/başarısız kısmı açıkça belirt.""",
        "tools": ["read_file", "list_files", "search_files", "web_search", "search_learning", "answer_question"],
        "model": None,
        "is_default": False,
        "created_at": datetime.now().isoformat()
    },
    {
        "id": "coding-manager",
        "name": "Kodlama Yöneticisi",
        "description": "Kodlama alanının uzman yöneticisi; görevi böler, uzman seçer, kalite kapısını uygular",
        "icon": "🧩",
        "color": "#8b5cf6",
        "system_prompt": """Sen KODLAMA YÖNETİCİ AJANIsın; kodlama alanının merkezî yöneticisisin (Ana Yöneticiye bağlısın).

## GÖREVİN
- İsteği analiz et, görev türünü belirle ve alt görevlere böl.
- Yalnızca GEREKLİ uzman ajanları seç; gereksiz ajan çalıştırma.
- Her uzmana açık görev tanımı, beklenen çıktı ve EN AZ araç izni ver.
- Sonuçları topla, test KANITLARINI kontrol et, hatayı uygun uzmana geri gönder.
- Ana Yönetici Ajana yapılandırılmış sonuç raporu sun.

## KURALLAR
- Kanıtsız başarı iddiası yok; test edilmemiş işi tamamlandı sayma.
- Ana Yöneticinin genel yönetim yetkisini gasbetme. Türkçe yanıt ver.""",
        "tools": ["read_file", "list_files", "search_files", "web_search", "search_learning", "answer_question"],
        "model": None,
        "is_default": False,
        "created_at": datetime.now().isoformat()
    },
    {
        "id": "task-planner",
        "name": "Görev Planlama Uzmanı",
        "description": "İsteği alt görevlere böler; sıra, bağımlılık ve kabul kriterlerini belirler",
        "icon": "🗂️",
        "color": "#6366f1",
        "system_prompt": """Sen GÖREV PLANLAMA uzmanısın.

## GÖREVİN
- Kullanıcı isteğini ölçülebilir alt görevlere böl.
- Her alt görev için: amaç, giriş/çıkış, bağımlılık ve KABUL KRİTERİ yaz.
- Hangi uzmanın hangi sırayla çalışması gerektiğini öner.
- Belirsizliği ve varsayımları açıkça ayır.

## KURALLAR
- Hiçbir dosyayı DEĞİŞTİRME/OLUŞTURMA; yalnızca plan üret.
- Türkçe, kısa, numaralı liste halinde yaz. Kanıtsız süre/başarı iddiası yok.""",
        "tools": ["read_file", "list_files", "search_files", "answer_question"],
        "model": None,
        "is_default": False,
        "created_at": datetime.now().isoformat()
    },
    {
        "id": "code-analyst",
        "name": "Kod Analiz Uzmanı",
        "description": "Mevcut kodu ve dosya yapısını inceler; değişiklik alanlarını belirler",
        "icon": "🔎",
        "color": "#0ea5e9",
        "system_prompt": """Sen KOD ANALİZ uzmanısın.

## GÖREVİN
- İlgili dosyaları, fonksiyonları ve bağımlılıkları bul.
- Mevcut kodun ÇALIŞMA MANTIĞINI açıkla; varsayım yapma, gerçek kodu oku.
- Değişiklik gereken alanları dosya düzeyinde (mümkünse satırla) belirt.

## KURALLAR
- Hiçbir dosyayı DEĞİŞTİRME/OLUŞTURMA.
- Türkçe, maddeler halinde, okuduğun kanıta dayalı yaz.""",
        "tools": ["read_file", "list_files", "search_files", "answer_question"],
        "model": None,
        "is_default": False,
        "created_at": datetime.now().isoformat()
    },
    {
        "id": "architect",
        "name": "Sistem Mimarı",
        "description": "Modülleri ve sistem tasarımını değerlendirir; mimari öneriler hazırlar",
        "icon": "🏛️",
        "color": "#6366f1",
        "system_prompt": """Sen SİSTEM MİMARİSİ uzmanısın.

## GÖREVİN
- Modüller arası ilişkileri; ölçeklenebilirlik, bakım kolaylığı ve tasarım sorunlarını değerlendir.
- Gereksiz karmaşıklığı ÖNLEYEN mimari öneriler hazırla.
- Önerileri mevcut sisteme uyarlanabilir, küçük ve geri alınabilir adımlar olarak sun.

## KURALLAR
- Kod yazma/değiştirme; tasarım ve öneri üret. Türkçe ve net yaz.""",
        "tools": ["read_file", "list_files", "search_files", "web_search", "rag_search", "answer_question"],
        "model": None,
        "is_default": False,
        "created_at": datetime.now().isoformat()
    },
    {
        "id": "dependency-analyst",
        "name": "Bağımlılık ve Ortam Uzmanı",
        "description": "Paketleri, sürümleri ve çalışma ortamını inceler",
        "icon": "📦",
        "color": "#f59e0b",
        "system_prompt": """Sen BAĞIMLILIK VE ORTAM uzmanısın.

## GÖREVİN
- Paketleri, sürümleri ve yapılandırmayı incele (requirements.txt, package.json vb.).
- Sürüm uyuşmazlıklarını ve EKSİK bağımlılıkları tespit et.
- Gereksiz/çakışan paket yüklemekten kaçın; mevcut çalışan ortamı koru.

## KURALLAR
- Paket KURMADAN önce gerekçe sun. Dosya değiştirme. Türkçe yaz.""",
        "tools": ["read_file", "list_files", "search_files", "execute_command", "web_search", "answer_question"],
        "model": None,
        "is_default": False,
        "created_at": datetime.now().isoformat()
    },
    {
        "id": "bug-fixer",
        "name": "Hata Düzeltme Uzmanı",
        "description": "Tespit edilen hatalara hedefe yönelik güvenli düzeltmeler uygular",
        "icon": "🔧",
        "color": "#ef4444",
        "system_prompt": """Sen HATA DÜZELTME uzmanısın.

## GÖREVİN
- Tespit edilen hatalar için HEDEFE YÖNELİK en küçük güvenli düzeltmeyi uygula.
- İlgisiz koda DOKUNMA; gereksiz refactor yapma.
- Düzeltmeden sonra ilgili testi/komutu çalıştır ve GERÇEK çıktıyı raporla.

## KURALLAR
- Kanıtsız 'düzeldi' deme. Türkçe, kısa, dosya + değişiklik odaklı yaz.""",
        "tools": ["read_file", "write_file", "edit_file", "list_files", "search_files", "execute_command", "generate_code", "search_learning", "answer_question"],
        "model": None,
        "is_default": False,
        "created_at": datetime.now().isoformat()
    },
    {
        "id": "database-pro",
        "name": "Veritabanı Uzmanı",
        "description": "Veri modellerini, sorguları ve veri bütünlüğünü inceler",
        "icon": "🗄️",
        "color": "#14b8a6",
        "system_prompt": """Sen VERİTABANI uzmanısın.

## GÖREVİN
- Veri modellerini, sorguları ve veri bütünlüğünü incele.
- Veri kaybı riski olan değişikliklerde ONAY iste; geri alınabilir geçiş (migration) öner.
- Yedekleme ve geri dönüş seçeneklerini değerlendir.

## KURALLAR
- Veri silen işlemi onaysız YAPMA. Türkçe ve net yaz.""",
        "tools": ["read_file", "write_file", "edit_file", "list_files", "search_files", "execute_command", "generate_code", "answer_question"],
        "model": None,
        "is_default": False,
        "created_at": datetime.now().isoformat()
    },
    {
        "id": "integrator",
        "name": "Entegrasyon Uzmanı",
        "description": "Modüller, servisler ve ajanlar arasındaki bağlantıları kurar",
        "icon": "🔗",
        "color": "#8b5cf6",
        "system_prompt": """Sen ENTEGRASYON uzmanısın.

## GÖREVİN
- Modüller, servisler ve ajanlar arasındaki bağlantıları kur.
- Veri formatı ve arayüz (interface) uyumluluğunu kontrol et.
- GERÇEK bağlantı hatalarını (kablo/veri biçimi uyuşmazlığı) tespit et ve düzelt.

## KURALLAR
- Entegrasyonu test etmeden 'çalışıyor' deme. Türkçe yaz.""",
        "tools": ["read_file", "write_file", "edit_file", "list_files", "search_files", "execute_command", "generate_code", "web_search", "answer_question"],
        "model": None,
        "is_default": False,
        "created_at": datetime.now().isoformat()
    },
    {
        "id": "test-engineer",
        "name": "Test Mühendisi",
        "description": "Birim, entegrasyon ve uçtan uca testler yazar ve gerçekten çalıştırır",
        "icon": "🧪",
        "color": "#22c55e",
        "system_prompt": """Sen TEST MÜHENDİSİSİN.

## GÖREVİN
- Birim, entegrasyon ve uçtan uca testler YAZ ve GERÇEKTEN ÇALIŞTIR.
- Test komutunu çalıştır; gerçek çıktıyı ve çıkış kodunu raporla.
- Başarısız testi GİZLEME; hatayı ve olası nedenini yaz.

## KURALLAR
- Test çalıştırmadan 'geçti' deme. Türkçe ve kanıtlı yaz.""",
        "tools": ["read_file", "write_file", "edit_file", "list_files", "search_files", "execute_command", "generate_code", "answer_question"],
        "model": None,
        "is_default": False,
        "created_at": datetime.now().isoformat()
    },
    {
        "id": "performance-pro",
        "name": "Performans Uzmanı",
        "description": "Bellek, işlemci, ağ ve yanıt süresini değerlendirir",
        "icon": "⚡",
        "color": "#eab308",
        "system_prompt": """Sen PERFORMANS uzmanısın.

## GÖREVİN
- Bellek, işlemci, ağ istekleri ve yanıt sürelerini değerlendir.
- Ölçülebilir darboğazları araştır (ölçüm/profiling verisi ile).
- KANIT olmadan performans artışı iddiasında BULUNMA.

## KURALLAR
- 'Daha hızlı' demek için ölçüm göster. Dosya değiştirme. Türkçe yaz.""",
        "tools": ["read_file", "list_files", "search_files", "execute_command", "calculate", "answer_question"],
        "model": None,
        "is_default": False,
        "created_at": datetime.now().isoformat()
    },
    {
        "id": "debugger",
        "name": "Hata Araştırma Uzmanı",
        "description": "Günlükleri ve hata mesajlarını inceleyip kök nedeni araştırır",
        "icon": "🐞",
        "color": "#f97316",
        "system_prompt": """Sen HATA ARAŞTIRMA uzmanısın.

## GÖREVİN
- Hata mesajlarını ve günlükleri (log) incele.
- Muhtemel KÖK NEDENLERİ araştır; her biri için kanıt göster.
- Varsayımları, DOĞRULANMIŞ bulgulardan net biçimde ayır.

## KURALLAR
- Dosya değiştirme; teşhis koy. Türkçe, kanıta dayalı yaz.""",
        "tools": ["read_file", "list_files", "search_files", "execute_command", "web_search", "answer_question"],
        "model": None,
        "is_default": False,
        "created_at": datetime.now().isoformat()
    },
    {
        "id": "regression-tester",
        "name": "Regresyon Kontrol Uzmanı",
        "description": "Yeni değişikliklerin eski özellikleri bozup bozmadığını kontrol eder",
        "icon": "♻️",
        "color": "#06b6d4",
        "system_prompt": """Sen REGRESYON KONTROL uzmanısın.

## GÖREVİN
- Yeni değişikliklerin ESKİ özellikleri bozup bozmadığını kontrol et.
- Önceden çalışan önemli işlevlerin testlerini YENİDEN ÇALIŞTIR.
- Yeni hataları ve geriye dönük uyumluluk sorunlarını raporla.

## KURALLAR
- Testleri gerçekten çalıştır; çıktıyı göster. Dosya değiştirme. Türkçe yaz.""",
        "tools": ["read_file", "list_files", "search_files", "execute_command", "answer_question"],
        "model": None,
        "is_default": False,
        "created_at": datetime.now().isoformat()
    },
    {
        "id": "docs-writer",
        "name": "Dokümantasyon Uzmanı",
        "description": "Kurulum, kullanım ve teknik belgeleri günceller",
        "icon": "📚",
        "color": "#a855f7",
        "system_prompt": """Sen TEKNİK DOKÜMANTASYON uzmanısın.

## GÖREVİN
- Kurulum, kullanım ve teknik belgeleri GÜNCELLE.
- Yeni modülleri ve değişen arayüzleri gerçek kodla uyumlu biçimde açıkla.
- GERÇEKTE BULUNMAYAN özellikleri belgeye EKLEME.

## KURALLAR
- Koddan doğrulanmayan davranışı belgeleme. Türkçe, net yaz.""",
        "tools": ["read_file", "write_file", "edit_file", "list_files", "web_search", "answer_question"],
        "model": None,
        "is_default": False,
        "created_at": datetime.now().isoformat()
    },
    {
        "id": "optimizer",
        "name": "Kod Optimizasyon Uzmanı",
        "description": "Ölçülebilir fayda sağlayan kod iyileştirmeleri uygular",
        "icon": "🚀",
        "color": "#3b82f6",
        "system_prompt": """Sen KOD OPTİMİZASYON uzmanısın.

## GÖREVİN
- Tekrarlanan ve gereksiz işlemleri tespit et.
- Kod verimliliğini artıran, ÖLÇÜLEBİLİR fayda sağlayan değişiklikleri uygula.
- DOĞRULUĞU bozan optimizasyonu kabul etme.

## KURALLAR
- Davranışı koru; değişikliği test ile doğrula. Türkçe yaz.""",
        "tools": ["read_file", "write_file", "edit_file", "list_files", "search_files", "execute_command", "answer_question"],
        "model": None,
        "is_default": False,
        "created_at": datetime.now().isoformat()
    },
    {
        "id": "learning-agent",
        "name": "Öğrenme ve Gelişim Uzmanı",
        "description": "Geçmiş görev sonuçlarından ölçülebilir iyileştirme önerileri çıkarır",
        "icon": "🧠",
        "color": "#10b981",
        "system_prompt": """Sen ÖĞRENME VE GELİŞİM uzmanısın.

## GÖREVİN
- Geçmiş görev sonuçlarını ve hata kayıtlarını analiz et.
- Tekrarlanan hata türlerini, sık başarısız testleri ve yanlış ajan seçimlerini belirle.
- Önerilerini TEST EDİLEBİLİR bir iyileştirme planına dönüştür.

## KURALLAR
- Kodu/kuralları kendiliğinden DEĞİŞTİRME; yalnızca öneri sun. Türkçe yaz.""",
        "tools": ["read_file", "list_files", "search_files", "search_learning", "rag_search", "answer_question"],
        "model": None,
        "is_default": False,
        "created_at": datetime.now().isoformat()
    },
]

DEFAULT_AGENTS.extend(CODING_TEAM_AGENTS)


# ============================================================
# KODLAMA EKİBİ RESMİ KADROSU
# Ana Yönetici Ajan -> Kodlama Yöneticisi -> 20 uzman
# ============================================================
CODING_TEAM_GROUPS = [
    "A. Analiz ve planlama",
    "B. Yazılım geliştirme",
    "C. Kalite ve güvenlik",
    "D. Yayın ve sürekli geliştirme",
]

# Sıra kullanıcı tanımıyla birebir aynıdır (1..20).
CODING_SPECIALISTS = [
    {"group": "A. Analiz ve planlama", "role": "Kod Analiz Ajanı", "id": "code-analyst"},
    {"group": "A. Analiz ve planlama", "role": "Sistem Mimarisi Ajanı", "id": "architect"},
    {"group": "A. Analiz ve planlama", "role": "Görev Planlama Ajanı", "id": "task-planner"},
    {"group": "A. Analiz ve planlama", "role": "Bağımlılık Analiz Ajanı", "id": "dependency-analyst"},
    {"group": "B. Yazılım geliştirme", "role": "Kod Geliştirme Ajanı", "id": "coder"},
    {"group": "B. Yazılım geliştirme", "role": "Hata Düzeltme Ajanı", "id": "bug-fixer"},
    {"group": "B. Yazılım geliştirme", "role": "API ve Backend Ajanı", "id": "backend-pro"},
    {"group": "B. Yazılım geliştirme", "role": "Arayüz ve Frontend Ajanı", "id": "frontend-pro"},
    {"group": "B. Yazılım geliştirme", "role": "Veritabanı Ajanı", "id": "database-pro"},
    {"group": "B. Yazılım geliştirme", "role": "Entegrasyon Ajanı", "id": "integrator"},
    {"group": "C. Kalite ve güvenlik", "role": "Test Ajanı", "id": "test-engineer"},
    {"group": "C. Kalite ve güvenlik", "role": "Kod İnceleme Ajanı", "id": "reviewer"},
    {"group": "C. Kalite ve güvenlik", "role": "Güvenlik Ajanı", "id": "security"},
    {"group": "C. Kalite ve güvenlik", "role": "Performans Ajanı", "id": "performance-pro"},
    {"group": "C. Kalite ve güvenlik", "role": "Hata Bulma Ajanı", "id": "debugger"},
    {"group": "D. Yayın ve sürekli geliştirme", "role": "DevOps ve Dağıtım Ajanı", "id": "devops"},
    {"group": "D. Yayın ve sürekli geliştirme", "role": "Dokümantasyon Ajanı", "id": "docs-writer"},
    {"group": "D. Yayın ve sürekli geliştirme", "role": "Kod Optimizasyonu Ajanı", "id": "optimizer"},
    {"group": "D. Yayın ve sürekli geliştirme", "role": "Regresyon Kontrol Ajanı", "id": "regression-tester"},
    {"group": "D. Yayın ve sürekli geliştirme", "role": "Öğrenme ve Gelişim Ajanı", "id": "learning-agent"},
]


# ============================================================
# RESMÎ KADRO (kullanıcı talimatı)
# Yalnızca Ana Yönetici + Kodlama Yöneticisi + 20 uzman kalır.
# Bu listede olmayan ajanlar aktif kadroya alınmaz.
# ============================================================
OFFICIAL_AGENT_IDS = {"main-manager", "coding-manager"} | {
    s["id"] for s in CODING_SPECIALISTS
}

# Kaldırılan ajanlar: eski JSON dosyasında kalmış olsalar bile yüklenmezler.
REMOVED_AGENT_IDS = {
    "assistant", "teacher", "designer", "analyst", "artist", "researcher",
    "writer", "translator", "marketer", "chat-pro", "python-pro",
    "image-pro", "video-pro", "team-lead", "tech-researcher", "rollback",
    "evidence-auditor", "code-standards",
}

OFFICIAL_AGENT_NAMES = {
    "main-manager": "Ana Yönetici Ajan",
    "coding-manager": "Kodlama Yönetici Ajanı",
    "code-analyst": "Kod Analiz Ajanı",
    "architect": "Sistem Mimarisi Ajanı",
    "task-planner": "Görev Planlama Ajanı",
    "dependency-analyst": "Bağımlılık Analiz Ajanı",
    "coder": "Kod Geliştirme Ajanı",
    "bug-fixer": "Hata Düzeltme Ajanı",
    "backend-pro": "API ve Backend Ajanı",
    "frontend-pro": "Arayüz ve Frontend Ajanı",
    "database-pro": "Veritabanı Ajanı",
    "integrator": "Entegrasyon Ajanı",
    "test-engineer": "Test Ajanı",
    "reviewer": "Kod İnceleme Ajanı",
    "security": "Güvenlik Ajanı",
    "performance-pro": "Performans Ajanı",
    "debugger": "Hata Bulma Ajanı",
    "devops": "DevOps ve Dağıtım Ajanı",
    "docs-writer": "Dokümantasyon Ajanı",
    "optimizer": "Kod Optimizasyonu Ajanı",
    "regression-tester": "Regresyon Kontrol Ajanı",
    "learning-agent": "Öğrenme ve Gelişim Ajanı",
}

OFFICIAL_AGENT_DESCRIPTIONS = {
    "main-manager": "Bütün yapay zekâyı yönetir ve nihai sonucu kontrol eder.",
    "coding-manager": (
        "20 uzmanlığı yönetir, görevleri dağıtır ve raporu Ana Yönetici Ajana gönderir."
    ),
}

DEFAULT_AGENTS = [
    a for a in DEFAULT_AGENTS if a.get("id") in OFFICIAL_AGENT_IDS
]
OFFICIAL_AGENT_ORDER = ["main-manager", "coding-manager"] + [
    s["id"] for s in CODING_SPECIALISTS
]
_OFFICIAL_ORDER = {agent_id: i for i, agent_id in enumerate(OFFICIAL_AGENT_ORDER)}
DEFAULT_AGENTS.sort(key=lambda a: _OFFICIAL_ORDER.get(a.get("id"), 999))
for _agent in DEFAULT_AGENTS:
    _agent["name"] = OFFICIAL_AGENT_NAMES.get(_agent["id"], _agent["name"])
    if _agent["id"] in OFFICIAL_AGENT_DESCRIPTIONS:
        _agent["description"] = OFFICIAL_AGENT_DESCRIPTIONS[_agent["id"]]


def coding_hierarchy() -> Dict:
    """Ana Yönetici -> Kodlama Yöneticisi -> 20 uzman ağacını döndürür.

    Eksik ajan varsa `missing` alanında AÇIKÇA bildirilir (sessizce yutulmaz).
    """
    agents = {a.get("id"): a for a in load_agents() if isinstance(a, dict)}

    def _brief(agent_id: str) -> Dict:
        a = agents.get(agent_id) or {}
        return {
            "id": agent_id,
            "name": a.get("name") or agent_id,
            "description": a.get("description", ""),
            "icon": a.get("icon", "🤖"),
            "color": a.get("color", "#64748b"),
            "tools": a.get("tools") or [],
        }

    groups = []
    for group_name in CODING_TEAM_GROUPS:
        members = [
            {**_brief(s["id"]), "role": s["role"]}
            for s in CODING_SPECIALISTS if s["group"] == group_name
        ]
        groups.append({"name": group_name, "specialists": members})

    return {
        "main_manager": _brief("main-manager"),
        "coding_manager": _brief("coding-manager"),
        "groups": groups,
        "total_specialists": len(CODING_SPECIALISTS),
        "missing": [s["id"] for s in CODING_SPECIALISTS if s["id"] not in agents],
    }


def load_agents() -> List[Dict]:
    """Load agents from file or create defaults, ensuring default agents stay updated."""
    stored_agents = []
    if os.path.exists(AGENTS_FILE):
        try:
            with open(AGENTS_FILE, 'r', encoding='utf-8') as f:
                stored_agents = json.load(f)
        except Exception:
            stored_agents = []
    
    if not stored_agents:
        save_agents(DEFAULT_AGENTS)
        return list(DEFAULT_AGENTS)
    
    # Merge: update default agents with latest definitions while keeping user custom agents
    default_ids = {a["id"] for a in DEFAULT_AGENTS}
    # Silinen ajanlar eski JSON'da kalmış olsa bile geri yüklenmez.
    # (İleride kullanıcının bilinçli olarak eklediği yeni ajanlar korunur.)
    custom_user_agents = [
        a for a in stored_agents
        if a.get("id") not in default_ids and a.get("id") not in REMOVED_AGENT_IDS
    ]

    # Preserve the ORIGINAL created_at of default agents so that restarting the
    # server does not rewrite the file on every boot (keeps git clean and keeps
    # a truthful creation timestamp).
    stored_created = {
        a.get("id"): a.get("created_at")
        for a in stored_agents
        if a.get("id") in default_ids and a.get("created_at")
    }
    merged_defaults = []
    for agent in DEFAULT_AGENTS:
        agent = dict(agent)
        if stored_created.get(agent["id"]):
            agent["created_at"] = stored_created[agent["id"]]
        merged_defaults.append(agent)

    merged = merged_defaults + custom_user_agents
    # Only rewrite the file when something actually changed (avoids timestamp
    # churn on every startup).
    if merged != stored_agents:
        try:
            save_agents(merged)
        except Exception:
            pass
    return merged


# Auto-selection keywords for each agent
AGENT_KEYWORDS = {
    "coder": ["kod", "kodla", "program", "python", "javascript", "java", "c++", "hata", "debug", "fonksiyon", "api", "backend", "frontend", "react", "django", "flask", "fastapi", "yazılım", "geliştir", "kod yaz", "script", "algoritma", "refactor"],
    "teacher": ["öğret", "anlat", "nedir", "nasıl", "öğren", "açıkla", "kurs", "eğitim", "ders", "örnek", "basit", "adım adım", "tutorial", "rehber", "kavram"],
    "designer": ["tasarım", "tasarla", "ui", "ux", "arayüz", "renk", "css", "responsive", "layout", "bootstrap", "tailwind", "font", "estetik", "react ile", "web sitesi tasar", "site tasar", "frontend tasar", "görsel tasarım", "mockup", "wireframe"],
    "analyst": ["veri", "analiz", "istatistik", "grafik", "chart", "excel", "pandas", "numpy", "rapor", "sayı", "yüzde", "oran", "hesapla", "ortalama", "varyans", "matematik", "korelasyon"],
    "artist": ["görsel", "resim", "sanat", "midjourney", "dalle", "stable diffusion", "prompt", "video", "sora", "runway", "veo", "fotoğraf", "çizim", "illüstrasyon"],
    "researcher": ["araştır", "incele", "karşılaştır", "analiz et", "makale", "kaynak", "literatür", "bilimsel", "çalışma", "rag", "doküman", "belge", "kaynakça"],
    "writer": ["yaz", "makale", "blog", "içerik", "metin", "seo", "haber", "hikaye", "şiir", "romantik", "edit", "düzenle metin", "copywriting"],
    "translator": ["çevir", "translate", "ingilizce", "almanca", "fransızca", "japonca", "arapça", "rusça", "çince", "dil", "tercüme"],
    "marketer": ["pazarlama", "marketing", "reklam", "sosyal medya", "instagram", "twitter", "seo", "sem", "dönüşüm", "müşteri", "marka", "growth"],
    "devops": ["sunucu", "server", "docker", "kubernetes", "deploy", "ci/cd", "jenkins", "linux", "nginx", "aws", "cloud", "altyapı", "devops"],
    "security": ["güvenlik", "security", "hack", "vulnerability", "zafiyet", "xss", "sql injection", "payload", "encrypt", "şifreleme", "siber", "penetrasyon", "audit", "cve"],
    "chat-pro": ["sohbet", "konuş", "muhabbet", "fikir", "tavsiye", "ne önerirsin", "dertleş"],
    "python-pro": ["python ile", "python script", "script yaz", "python pro", "python", "pip", "pytest", "pandas", "django", "flask", "fastapi", "script"],
    "frontend-pro": ["frontend", "react", "html", "css", "arayüz", "responsive", "component", "tailwind", "tasarım kodu"],
    "backend-pro": ["backend", "rest api", "endpoint", "veritabanı", "database", "sql", "fastapi", "jwt", "auth"],
    "image-pro": ["görsel üret", "resim üret", "resmini yap", "fotoğraf üret", "illüstrasyon", "midjourney", "dall-e"],
    "video-pro": ["video üret", "video yap", "mp4", "film yap", "sahne üret", "veo", "sora", "runway"],
    "reviewer": ["denetle", "kontrol et", "hata var mı", "qa", "test et", "doğrula", "incele"],
    "team-lead": ["ekip", "birleştir", "hepsini yap", "komple", "uçtan uca", "proje yap", "site yap"],
    # --- Kodlama ekibi (kodlama yöneticisi + uzmanlar) ---
    "main-manager": ["ana yönetici", "genel yönetici", "sistem yöneticisi", "tüm sistemi yönet"],
    "coding-manager": ["kodlama görevi", "kodlama yöneticisi", "kodlama işi", "kodlama projesi"],
    "code-analyst": ["kodu analiz et", "kod analizi", "kod analiz", "kodu incele"],
    "architect": ["mimari", "architecture", "sistem tasarımı", "sistem tasarimi"],
    "dependency-analyst": ["bağımlılık", "bagimlilik", "paket sürüm", "paket surum", "sürüm uyuşmaz"],
    "bug-fixer": ["hatayı düzelt", "hatayi duzelt", "bug fix", "hatayı gider"],
    "database-pro": ["veritabanı tasarımı", "veritabani tasarimi", "şema tasarımı", "şema tasarimi", "migration", "migrasyon", "indexleme"],
    "integrator": ["entegre et", "entegrasyon", "integration"],
    "test-engineer": ["test yaz", "test oluştur", "test olustur", "birim test", "unit test", "integration test"],
    "performance-pro": ["performans", "performance", "yavaş çalışıyor", "yavas calisiyor", "darboğaz", "darbogaz"],
    "debugger": ["hata ayıkla", "hata ayikla", "kök neden", "kok neden", "traceback", "log incele"],
    "regression-tester": ["regresyon", "regression"],
    "docs-writer": ["dokümantasyon yaz", "dokumantasyon yaz", "readme yaz", "belge yaz", "dokümantasyon güncelle"],
    "optimizer": ["optimize et", "kod optimizasyon", "kodu iyileştir", "kodu iyilestir"],
    "tech-researcher": ["teknik araştırma", "teknik arastirma", "hangi kütüphane", "hangi kutuphane", "en iyi pratik", "best practice"],
    "rollback": ["geri al", "rollback", "geri dönüş", "geri donus"],
    "evidence-auditor": ["kanıt denetle", "kanit denetle", "rapor denetle", "kanıt kontrol"],
    "code-standards": ["kod standardı", "kod standarti", "isimlendirme", "biçimlendirme kuralı", "kod stili"],
    "learning-agent": ["öğrenme raporu", "ogrenme raporu", "gelişim raporu", "hata kalıpları"],
}

# Kaldırılan ajanların anahtar kelimeleri, resmî kadrodaki en yakın ajana yönlenir.
# Böylece eski anahtar kelime seçici de yalnızca resmî 22 ajanın ID'sini döndürür.
KEYWORD_FALLBACK_AGENTS = {
    "teacher": "main-manager",
    "designer": "frontend-pro",
    "analyst": "code-analyst",
    "artist": "main-manager",
    "researcher": "architect",
    "writer": "main-manager",
    "translator": "main-manager",
    "marketer": "main-manager",
    "chat-pro": "main-manager",
    "python-pro": "coder",
    "image-pro": "main-manager",
    "video-pro": "main-manager",
    "team-lead": "coding-manager",
    "tech-researcher": "architect",
    "rollback": "main-manager",
    "evidence-auditor": "reviewer",
    "code-standards": "reviewer",
}


def keyword_select_agent(user_message: str) -> str:
    """
    Anahtar kelimeye göre uzman seçer (eski davranış; yedek/istek üzerine kullanılır).
    Returns agent ID.
    """
    message_lower = user_message.lower().strip()
    
    # Check for greetings and general chat first
    greetings = ["merhaba", "selam", "hey", "nasılsın", "naber", "günaydın", "iyi akşamlar", "iyi geceler", "selamlar"]
    if any(greeting in message_lower for greeting in greetings) and len(message_lower.split()) <= 5:
        return "main-manager"
    
    # Score each agent based on keyword matches
    scores = {}
    for agent_id, keywords in AGENT_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            if keyword in message_lower:
                # Longer keywords get higher weight (more specific)
                score += len(keyword.split()) * 2 + 1
        if score > 0:
            scores[agent_id] = score
    
    # Return agent with highest score, or default main manager
    if scores:
        best_agent = max(scores, key=scores.get)
        return KEYWORD_FALLBACK_AGENTS.get(best_agent, best_agent)
    
    # Default to main manager (assistant agent was removed from the official roster)
    return "main-manager"


def save_agents(agents: List[Dict]):
    """Save agents to file."""
    with open(AGENTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(agents, f, indent=2, ensure_ascii=False)


def get_agent(agent_id: str) -> Optional[Dict]:
    """Get agent by ID."""
    agents = load_agents()
    for agent in agents:
        if agent["id"] == agent_id:
            return agent
    return None


def create_agent(data: Dict) -> Dict:
    """Create a new custom agent."""
    agents = load_agents()
    
    agent = {
        "id": str(uuid.uuid4())[:12],
        "name": data.get("name", "Yeni Ajan"),
        "description": data.get("description", ""),
        "icon": data.get("icon", "🤖"),
        "color": data.get("color", "#6366f1"),
        "system_prompt": data.get("system_prompt", "Sen yardımsever bir asistanısın. Türkçe yanıt ver."),
        "tools": data.get("tools", []),
        "model": data.get("model", None),
        "is_default": False,
        "created_at": datetime.now().isoformat()
    }
    
    agents.append(agent)
    save_agents(agents)
    return agent


def update_agent(agent_id: str, data: Dict) -> Optional[Dict]:
    """Update an existing agent."""
    agents = load_agents()
    
    for i, agent in enumerate(agents):
        if agent["id"] == agent_id:
            # Update fields
            if "name" in data:
                agent["name"] = data["name"]
            if "description" in data:
                agent["description"] = data["description"]
            if "icon" in data:
                agent["icon"] = data["icon"]
            if "color" in data:
                agent["color"] = data["color"]
            if "system_prompt" in data:
                agent["system_prompt"] = data["system_prompt"]
            if "tools" in data:
                agent["tools"] = data["tools"]
            if "model" in data:
                agent["model"] = data["model"]
            
            agent["updated_at"] = datetime.now().isoformat()
            agents[i] = agent
            save_agents(agents)
            return agent
    
    return None


def delete_agent(agent_id: str) -> bool:
    """Delete an agent (cannot delete default agents)."""
    agents = load_agents()
    
    for agent in agents:
        if agent["id"] == agent_id:
            if agent.get("is_default"):
                return False  # Cannot delete default agents
    
    agents = [a for a in agents if a["id"] != agent_id]
    save_agents(agents)
    return True


def duplicate_agent(agent_id: str) -> Optional[Dict]:
    """Duplicate an existing agent."""
    agent = get_agent(agent_id)
    if not agent:
        return None
    
    new_agent = agent.copy()
    new_agent["id"] = str(uuid.uuid4())[:12]
    new_agent["name"] = f"{agent['name']} (Kopya)"
    new_agent["is_default"] = False
    new_agent["created_at"] = datetime.now().isoformat()
    
    agents = load_agents()
    agents.append(new_agent)
    save_agents(agents)
    return new_agent
