# T-008 API Entegrasyon Test Raporu

Tarih: 2026-10-16 23:52

Ozet: **34/36 PASS**

| Sinif | Method | Endpoint | Status |
|---|---|---|---|
| PASS | POST | `/api/v1/auth/login` | 200 |
| PASS | GET | `/` | 200 |
| PASS | GET | `/health` | 200 |
| PASS | GET | `/api/v1/models/catalog` | 200 |
| PASS | GET | `/api/v1/models/providers` | 200 |
| PASS | GET | `/api/v1/models/active` | 200 |
| PASS | GET | `/api/v1/agents` | 200 |
| PASS | GET | `/api/v1/agents/tools/available` | 200 |
| PASS | GET | `/api/v1/ai/info` | 200 |
| PASS | GET | `/api/v1/ai/conversations` | 200 |
| PASS | GET | `/api/v1/ai/learning/stats` | 200 |
| PASS | GET | `/api/v1/agent/status` | 200 |
| PASS | GET | `/api/v1/agent/tools` | 200 |
| PASS | GET | `/api/v1/agent/sessions` | 200 |
| PASS | GET | `/api/v1/agent/memory/stats` | 200 |
| PASS | GET | `/api/v1/brain/stats` | 200 |
| PASS | GET | `/api/v1/brain/skills` | 200 |
| PASS | GET | `/api/v1/brain/lessons` | 200 |
| PARTIAL | GET | `/api/v1/brain/context` | 422 |
| PASS | GET | `/api/v1/brain/experiences` | 200 |
| PASS | GET | `/api/v1/brain/reflections` | 200 |
| PARTIAL | GET | `/api/v1/brain/predict` | 422 |
| PASS | GET | `/api/v1/fs/drives` | 200 |
| PASS | GET | `/api/v1/fs/home` | 200 |
| PASS | GET | `/api/v1/fs/desktop` | 200 |
| PASS | GET | `/api/v1/fs/browse` | 200 |
| PASS | GET | `/api/v1/fs/current-project` | 200 |
| PASS | GET | `/api/v1/fs/recent-projects` | 200 |
| PASS | GET | `/api/v1/project/stats` | 200 |
| PASS | GET | `/api/v1/project/tree` | 200 |
| PASS | GET | `/api/v1/learning/report` | 200 |
| PASS | GET | `/api/v1/learning/summary` | 200 |
| PASS | GET | `/api/v1/auth/me` | 200 |
| PASS | GET | `/api/v1/auth/chats` | 200 |
| PASS | POST | `/api/v1/generate/visual` | 200 |
| PASS | POST | `/api/v1/ai/chat` | 200 |
