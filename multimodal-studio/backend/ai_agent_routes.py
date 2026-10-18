"""
AI Agent API Routes - NEXUS-CORE v6.1
======================================
Chat interface for the AI agent with user chat persistence.
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
import json

from ai_agent import chat, get_agent_v6, get_agent_info, reset_agent_v6
from auth import auth_service, get_optional_user, get_current_user

# Force fresh agent with current .env config
reset_agent_v6()

router = APIRouter(prefix="/api/v1/ai", tags=["ai-agent"])
security = HTTPBearer(auto_error=False)


# ============================================================
# REQUEST/RESPONSE MODELS
# ============================================================

class ChatRequest(BaseModel):
    """Chat request."""
    message: str = Field(..., description="User message")
    conversation_id: Optional[str] = Field(None, description="Continue existing conversation")
    history: Optional[List[Dict]] = Field(None, description="Previous messages")
    agent_id: Optional[str] = Field(None, description="Custom agent ID to use (use 'auto' for automatic selection)")


class ChatResponse(BaseModel):
    """Chat response."""
    success: bool
    response: str
    conversation_id: str
    tools_used: List[str] = []
    thinking_steps: List[Dict] = []
    selected_agent: Optional[Dict] = None
    error: Optional[str] = None


class AgentInfoResponse(BaseModel):
    """Agent info response."""
    name: str
    type: str
    capabilities: List[str]
    tools: List[str]
    llm_model: str


# ============================================================
# CHAT ENDPOINTS
# ============================================================

@router.post("/chat", response_model=ChatResponse, summary="Chat with AI Agent")
async def chat_endpoint(request: ChatRequest, current_user = Depends(get_optional_user)):
    """
    Chat with the AI agent.
    
    The agent understands natural language and can:
    - Answer questions
    - Generate code
    - Create visual prompts
    - Create video prompts
    - Search the web
    - Learn from past interactions
    
    If authenticated, chat is persisted to user's chat history.
    
    Examples:
    - "Python'da hello world yazdır"
    - "FastAPI ile kullanıcı API'si oluştur"
    - "Cyberpunk tema için Midjourney promptu yaz"
    - "ürün lansmanı için video sahnesi tasarla"
    - "Yapay zeka nedir?"
    """
    try:
        # If user is authenticated and no conversation_id provided, create/get user chat
        conversation_id = request.conversation_id
        chat_id_for_persistence = None
        
        if current_user and not conversation_id:
            # Create a new chat or use the most recent one
            user_chats = auth_service.get_user_chats(current_user.id)
            if user_chats:
                conversation_id = user_chats[0].id
                chat_id_for_persistence = conversation_id
            else:
                # Create new chat
                new_chat = auth_service.create_chat(current_user.id)
                conversation_id = new_chat.id
                chat_id_for_persistence = conversation_id
        elif current_user and conversation_id:
            # Verify chat belongs to user, or create new if it doesn't exist
            user_chat = auth_service.get_chat(conversation_id, current_user.id)
            if user_chat:
                chat_id_for_persistence = conversation_id
            else:
                # Create new chat with the provided ID (from frontend)
                auth_service.create_chat(current_user.id, chat_id=conversation_id)
                chat_id_for_persistence = conversation_id
        
        # Handle auto agent selection
        agent_id = request.agent_id
        selected_agent_info = None
        if agent_id == "auto":
            from custom_agents import auto_select_agent, get_agent
            agent_id = auto_select_agent(request.message)
            selected_agent = get_agent(agent_id)
            if selected_agent:
                selected_agent_info = {
                    "id": selected_agent["id"],
                    "name": selected_agent["name"],
                    "icon": selected_agent["icon"]
                }
        
        result = await chat(request.message, conversation_id, history=request.history, agent_id=agent_id)
        
        # Add selected agent info to result
        if selected_agent_info:
            result["selected_agent"] = selected_agent_info
        
        # Persist messages and update title if authenticated
        if current_user and chat_id_for_persistence and result.get("success"):
            # Save user message
            auth_service.add_message(chat_id_for_persistence, current_user.id, "user", request.message)
            # Save assistant response
            auth_service.add_message(chat_id_for_persistence, current_user.id, "assistant", result.get("response", ""))
            
            # Update chat title with first 10 chars of first user message
            user_chat = auth_service.get_chat(chat_id_for_persistence, current_user.id)
            if user_chat and (user_chat.title == "Yeni Sohbet" or not user_chat.title):
                new_title = request.message[:10] + ("..." if len(request.message) > 10 else "")
                auth_service.update_chat_title(chat_id_for_persistence, current_user.id, new_title)
        
        if not isinstance(result, dict):
            result = {"success": False, "response": "", "conversation_id": conversation_id or "", "error": "Boş ajan yanıtı"}
        result.setdefault("success", False)
        result.setdefault("response", result.get("error") or "")
        result.setdefault("conversation_id", conversation_id or "")
        result.setdefault("tools_used", [])
        result.setdefault("thinking_steps", [])
        return ChatResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/stream", summary="Stream Chat Response")
async def chat_stream_endpoint(request: ChatRequest):
    """
    Stream chat response (SSE format).
    For real-time streaming responses.
    """
    import httpx
    
    async def generate():
        # Simplified streaming - in production, use real streaming
        result = await chat(request.message, request.conversation_id)
        
        # Persist messages if authenticated
        if hasattr(request, 'user') and request.user and result.get("success"):
            chat_id = request.conversation_id
            if chat_id:
                auth_service.add_message(chat_id, request.user.id, "user", request.message)
                auth_service.add_message(chat_id, request.user.id, "assistant", result.get("response", ""))
        
        # Send as SSE
        yield f"data: {json.dumps({'type': 'start', 'conversation_id': result.get('conversation_id')})}\n\n"
        yield f"data: {json.dumps({'type': 'content', 'content': result.get('response', '')})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'tools_used': result.get('tools_used', [])})}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }
    )


@router.get("/info", response_model=AgentInfoResponse, summary="Get Agent Info")
async def agent_info():
    """Get information about the AI agent."""
    info = get_agent_info()
    return AgentInfoResponse(**info)


@router.get("/conversations", summary="List Conversations")
async def list_conversations():
    """List all active conversations."""
    agent = get_agent_v6()
    conversations = []
    for conv_id, conv in agent.memory.conversations.items():
        conversations.append({
            "id": conv_id,
            "message_count": len(conv.messages),
            "created_at": conv.created_at,
            "last_message": conv.messages[-1].content[:100] if conv.messages else None
        })
    return {"conversations": conversations}


@router.get("/conversations/{conversation_id}", summary="Get Conversation")
async def get_conversation(conversation_id: str):
    """Get full conversation history."""
    agent = get_agent_v6()
    conv = agent.memory.get_or_create(conversation_id)
    
    return {
        "id": conv.id,
        "messages": [
            {
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp
            }
            for msg in conv.messages
        ],
        "created_at": conv.created_at,
        "updated_at": conv.updated_at
    }


@router.delete("/conversations/{conversation_id}", summary="Delete Conversation")
async def delete_conversation(conversation_id: str):
    """Delete a conversation."""
    agent = get_agent_v6()
    if conversation_id in agent.memory.conversations:
        del agent.memory.conversations[conversation_id]
        return {"success": True, "message": f"Conversation {conversation_id} deleted"}
    return {"success": False, "message": "Conversation not found"}


@router.get("/learning/stats", summary="Get Learning Statistics")
async def learning_stats():
    """Get learning statistics."""
    agent = get_agent_v6()
    return {
        "stats": agent.learning.stats,
        "total_lessons": len(agent.learning.lessons),
        "recent_lessons": list(agent.learning.lessons.values())[-10:]
    }