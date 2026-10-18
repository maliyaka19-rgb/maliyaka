"""
Custom Agent API Routes
=======================
Endpoints for managing custom AI agents.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
import logging

from custom_agents import (
    load_agents, get_agent, create_agent, 
    update_agent, delete_agent, duplicate_agent
)

logger = logging.getLogger("nexus-custom-agents")

router = APIRouter(prefix="/api/v1/agents", tags=["custom-agents"])


# ============================================================
# REQUEST MODELS
# ============================================================

class AgentCreate(BaseModel):
    """Create agent request."""
    name: str = Field(..., min_length=1, max_length=50)
    description: str = Field(default="", max_length=200)
    icon: str = Field(default="🤖", max_length=10)
    color: str = Field(default="#6366f1", max_length=20)
    system_prompt: str = Field(default="Sen yardımsever bir asistanısın. Türkçe yanıt ver.")
    tools: List[str] = Field(default=[])
    model: Optional[str] = None


class AgentUpdate(BaseModel):
    """Update agent request."""
    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    system_prompt: Optional[str] = None
    tools: Optional[List[str]] = None
    model: Optional[str] = None


class TeamRunRequest(BaseModel):
    """Team task request: uzman üretir, denetçi doğrular, lider birleştirir."""
    message: str = Field(..., min_length=1, max_length=4000)
    conversation_id: Optional[str] = None
    refine: bool = Field(default=True)


# ============================================================
# ENDPOINTS
# ============================================================

@router.get("", summary="List all agents")
async def list_agents():
    """Get all available agents."""
    agents = load_agents()
    return {
        "success": True,
        "agents": agents,
        "total": len(agents)
    }


@router.get("/{agent_id}", summary="Get agent details")
async def get_agent_details(agent_id: str):
    """Get a specific agent by ID."""
    agent = get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    return {
        "success": True,
        "agent": agent
    }


@router.post("", summary="Create new agent")
async def create_new_agent(data: AgentCreate):
    """Create a new custom AI agent."""
    try:
        agent = create_agent(data.dict())
        logger.info(f"Created agent: {agent['name']} ({agent['id']})")
        
        return {
            "success": True,
            "agent": agent,
            "message": f"'{agent['name']}' ajanı oluşturuldu"
        }
    except Exception as e:
        logger.error(f"Agent creation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{agent_id}", summary="Update agent")
async def update_agent_endpoint(agent_id: str, data: AgentUpdate):
    """Update an existing agent."""
    agent = update_agent(agent_id, data.dict(exclude_unset=True))
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    return {
        "success": True,
        "agent": agent,
        "message": "Ajan güncellendi"
    }


@router.delete("/{agent_id}", summary="Delete agent")
async def delete_agent_endpoint(agent_id: str):
    """Delete a custom agent (default agents cannot be deleted)."""
    success = delete_agent(agent_id)
    if not success:
        raise HTTPException(
            status_code=400, 
            detail="Varsayılan ajanlar silinemez"
        )
    
    return {
        "success": True,
        "message": "Ajan silindi"
    }


@router.post("/{agent_id}/duplicate", summary="Duplicate agent")
async def duplicate_agent_endpoint(agent_id: str):
    """Duplicate an existing agent."""
    agent = duplicate_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    return {
        "success": True,
        "agent": agent,
        "message": f"'{agent['name']}' oluşturuldu"
    }


@router.post("/team/run", summary="Run agent team (uzman + denetçi + lider)")
async def run_team_task(data: TeamRunRequest):
    """Ekip çalıştır: uzman üretir → denetçi doğrular → lider birleştirip teslim eder."""
    from custom_agents import auto_select_agent, get_agent
    import ai_agent as _ai

    message = data.message.strip()
    conv = data.conversation_id
    specialist_id = auto_select_agent(message)
    if specialist_id in ("reviewer", "team-lead"):
        specialist_id = "assistant"
    specialist = get_agent(specialist_id) or {}

    draft = await _ai.chat(message, conv, agent_id=specialist_id)
    conv = draft.get("conversation_id", conv)
    draft_text = (draft.get("response") or "")[:4000]
    draft_tools = draft.get("tools_used", [])

    review_prompt = (
        f"Orijinal görev: {message}\n\n"
        f"Uzman ({specialist_id}) taslağı:\n{draft_text}\n\n"
        f"Kullanılan araçlar: {', '.join(draft_tools) if draft_tools else 'yok'}\n\n"
        "Denetim yap: eksik/hata/yarım iş var mı? Varsa düzeltmeyi de yaz, yoksa ONAYLANDI de."
    )
    review = await _ai.chat(review_prompt, conv, agent_id="reviewer")
    review_text = (review.get("response") or "")[:4000]

    if data.refine:
        merge_prompt = (
            f"Orijinal görev: {message}\n\n"
            f"Uzman çıktısı:\n{draft_text}\n\n"
            f"Denetçi raporu:\n{review_text}\n\n"
            "Bunları TEK final sonuca birleştir: dosya/görsel/video + net açıklama. Eksik varsa belirt."
        )
        final = await _ai.chat(merge_prompt, conv, agent_id="team-lead")
    else:
        final = review if review.get("success") else draft

    return {
        "success": bool(final.get("success")),
        "response": final.get("response", ""),
        "conversation_id": final.get("conversation_id", conv),
        "specialist": {"id": specialist_id, "name": specialist.get("name", specialist_id)},
        "stages": {
            "draft": {"agent_id": specialist_id, "success": draft.get("success"), "tools_used": draft_tools},
            "review": {"agent_id": "reviewer", "success": review.get("success")},
            "final": {"agent_id": "team-lead" if data.refine else review.get("agent_id", "reviewer")},
        },
        "tools_used": list(dict.fromkeys((draft_tools or []) + (final.get("tools_used", []) or []))),
    }


@router.get("/tools/available", summary="List available tools")
async def list_available_tools():
    """Get list of all available tools that can be assigned to agents."""
    tools = [
        # File System Tools
        {
            "id": "read_file",
            "name": "Dosya Oku",
            "icon": "📖",
            "description": "Dosya içeriğini okur",
            "group": "Dosya"
        },
        {
            "id": "write_file",
            "name": "Dosya Yaz",
            "icon": "📝",
            "description": "Dosya oluşturur veya üzerine yazar",
            "group": "Dosya"
        },
        {
            "id": "edit_file",
            "name": "Dosya Düzenle",
            "icon": "✏️",
            "description": "Dosyada değişiklik yapar",
            "group": "Dosya"
        },
        {
            "id": "list_files",
            "name": "Klasör Listele",
            "icon": "📁",
            "description": "Klasör içeriğini listeler",
            "group": "Dosya"
        },
        {
            "id": "search_files",
            "name": "Dosya Ara",
            "icon": "🔍",
            "description": "Dosyalarda arama yapar",
            "group": "Dosya"
        },
        {
            "id": "execute_command",
            "name": "Komut Çalıştır",
            "icon": "⚙️",
            "description": "Sistem komutu çalıştırır",
            "group": "Dosya"
        },
        # AI Generation Tools
        {
            "id": "generate_code",
            "name": "Kod Üret",
            "icon": "💻",
            "description": "Üretim hazır kod oluşturur",
            "group": "Yapay Zeka"
        },
        {
            "id": "generate_visual_prompt",
            "name": "Görsel Prompt",
            "icon": "🎨",
            "description": "Midjourney/DALL-E/SD için prompt oluşturur",
            "group": "Yapay Zeka"
        },
        {
            "id": "generate_video_prompt",
            "name": "Video Prompt",
            "icon": "🎬",
            "description": "Veo/Sora/Runway için prompt oluşturur",
            "group": "Yapay Zeka"
        },
        {
            "id": "generate_real_video",
            "name": "Gerçek Video Üret",
            "icon": "🎥",
            "description": "Metinden gerçek MP4 video dosyası oluşturur (ücretsiz)",
            "group": "Yapay Zeka"
        },
        # Intelligence Tools
        {
            "id": "web_search",
            "name": "Web Arama",
            "icon": "🌐",
            "description": "Web'de güncel bilgi arar",
            "group": "Zeka"
        },
        {
            "id": "search_learning",
            "name": "Öğrenme Ara",
            "icon": "🧠",
            "description": "Geçmiş deneyimlerde arama yapar",
            "group": "Zeka"
        },
        {
            "id": "answer_question",
            "name": "Soru Cevapla",
            "icon": "💬",
            "description": "Genel bilgi sorularını yanıtlar",
            "group": "Zeka"
        }
    ]
    
    return {
        "success": True,
        "tools": tools,
        "total": len(tools)
    }
