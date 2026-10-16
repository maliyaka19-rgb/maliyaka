"""
Agent API Routes - NEXUS-CORE v5.1
===================================
REST endpoints for the autonomous agent system.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import asyncio
from collections import deque

from agent_core import get_agent, run_agent, get_agent_status, NexusAgent

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


# ============================================================
# REQUEST/RESPONSE MODELS
# ============================================================

class AgentRunRequest(BaseModel):
    """Request to run agent with a goal."""
    goal: str = Field(..., description="User's goal/task for the agent")
    session_id: Optional[str] = Field(None, description="Optional session ID for continuity")
    async_mode: bool = Field(default=False, description="Run asynchronously")


class AgentRunResponse(BaseModel):
    """Response from agent execution."""
    success: bool
    session_id: str
    goal: str
    state: str
    plan: Optional[Dict[str, Any]] = None
    tool_results: List[Dict[str, Any]] = []
    reflection: Optional[Dict[str, Any]] = None
    memory_stats: Optional[Dict[str, int]] = None
    error: Optional[str] = None


class AgentStatusResponse(BaseModel):
    """Agent status response."""
    session_id: Optional[str]
    state: str
    goal: Optional[str] = None
    current_step: int
    total_steps: int
    memory_counts: Dict[str, int]


class AgentMemoryQuery(BaseModel):
    """Query agent memory."""
    query: str = Field(..., description="Search query")
    limit: int = Field(default=10, description="Max results")


class AgentToolInfo(BaseModel):
    """Tool information."""
    name: str
    type: str
    description: str


# ============================================================
# AGENT ENDPOINTS
# ============================================================

@router.post("/run", response_model=AgentRunResponse, summary="Run Agent with Goal")
async def run_agent_endpoint(request: AgentRunRequest):
    """
    Execute autonomous agent with a goal.
    
    The agent will:
    1. PLAN - Analyze goal and create execution plan
    2. ACT - Execute plan steps using available tools
    3. OBSERVE - Evaluate results
    4. REFLECT - Learn from execution and update memory
    
    Example goals:
    - "Create a FastAPI REST API for user management with JWT"
    - "Generate Midjourney prompt for cyberpunk cityscape"
    - "Create video prompt for product launch scene"
    - "Search for latest AI news and summarize"
    """
    try:
        result = await run_agent(request.goal, request.session_id)
        return AgentRunResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent execution failed: {str(e)}")


@router.post("/run-async", summary="Run Agent Asynchronously")
async def run_agent_async(request: AgentRunRequest):
    """
    Start agent execution asynchronously.
    Returns immediately with session_id for polling.
    """
    agent = get_agent()
    session_id = request.session_id or f"async_{asyncio.get_event_loop().time()}"
    
    # Start background task
    asyncio.create_task(run_agent(request.goal, session_id))
    
    return {
        "success": True,
        "session_id": session_id,
        "message": "Agent started in background. Poll /status for updates."
    }


@router.get("/status", response_model=AgentStatusResponse, summary="Get Agent Status")
async def get_agent_status_endpoint(session_id: Optional[str] = None):
    """Get current agent status and progress."""
    status = get_agent_status()
    return AgentStatusResponse(**status)


@router.get("/tools", response_model=List[AgentToolInfo], summary="List Available Tools")
async def list_agent_tools():
    """List all tools available to the agent."""
    agent = get_agent()
    return [AgentToolInfo(**t) for t in agent.tools.list_all()]


@router.post("/memory/query", summary="Query Agent Memory")
async def query_memory(request: AgentMemoryQuery):
    """Search agent's memory for relevant past experiences."""
    agent = get_agent()
    memories = agent.memory.retrieve(request.query, limit=request.limit)
    return {
        "query": request.query,
        "results": len(memories),
        "memories": [
            {
                "id": m.id,
                "type": m.type,
                "content": m.content,
                "timestamp": m.timestamp,
                "importance": m.importance,
                "tags": m.tags
            }
            for m in memories
        ]
    }


@router.get("/memory/stats", summary="Get Memory Statistics")
async def memory_stats():
    """Get memory system statistics."""
    agent = get_agent()
    return {
        "short_term": len(agent.memory.short_term),
        "long_term": len(agent.memory.long_term),
        "episodic": len(agent.memory.episodic),
        "semantic": len(agent.memory.semantic),
        "total": (
            len(agent.memory.short_term) +
            len(agent.memory.long_term) +
            len(agent.memory.episodic) +
            len(agent.memory.semantic)
        )
    }


@router.post("/memory/consolidate", summary="Consolidate Memory")
async def consolidate_memory():
    """Move important short-term memories to long-term storage."""
    agent = get_agent()
    agent.memory.consolidate()
    return {"success": True, "message": "Memory consolidation complete"}


@router.delete("/memory/clear", summary="Clear Session Memory")
async def clear_memory(session_id: Optional[str] = None):
    """Clear memory (optionally for specific session)."""
    agent = get_agent()
    if session_id:
        # Clear only session-related memories
        agent.memory.short_term = deque(
            [m for m in agent.memory.short_term 
             if m.content.get("session_id") != session_id],
            maxlen=agent.memory.short_term.maxlen
        )
        return {"success": True, "message": f"Cleared memory for session {session_id}"}
    else:
        # Clear all
        agent.memory.short_term.clear()
        agent.memory.long_term.clear()
        agent.memory.episodic.clear()
        agent.memory.semantic.clear()
        return {"success": True, "message": "All memory cleared"}


# ============================================================
# BACKGROUND AGENT MANAGEMENT
# ============================================================

@router.get("/sessions", summary="List Active Sessions")
async def list_sessions():
    """List all active agent sessions."""
    agent = get_agent()
    # In a full implementation, this would track multiple sessions
    return {
        "active_session": agent.context.session_id if agent.context else None,
        "agent_state": agent.context.state.value if agent.context else "idle"
    }


@router.post("/stop", summary="Stop Current Agent")
async def stop_agent():
    """Stop currently running agent."""
    agent = get_agent()
    if agent.context and agent.context.state not in ["completed", "error", "idle"]:
        agent.context.state = "error"
        return {"success": True, "message": "Agent stopped"}
    return {"success": False, "message": "No active agent to stop"}