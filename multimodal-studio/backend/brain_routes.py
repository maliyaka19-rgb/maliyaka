"""
Brain API Routes - NEXUS-CORE v6.1
===================================
Endpoints for inspecting and interacting with the learning brain.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
import json

from brain import get_brain, reset_brain, NexusBrain

router = APIRouter(prefix="/api/v1/brain", tags=["brain"])


# ============================================================
# REQUEST/RESPONSE MODELS
# ============================================================

class FeedbackRequest(BaseModel):
    experience_id: str
    feedback: str  # "good", "bad", "correction"


class BrainStatsResponse(BaseModel):
    experiences_total: int
    lessons_learned: int
    skills_developed: int
    reflections: int
    session_stats: Dict
    top_lessons: List
    tool_accuracy: Dict


class LessonsResponse(BaseModel):
    lessons: List[Dict]


class SkillsResponse(BaseModel):
    skills: List[Dict]


class ReflectionsResponse(BaseModel):
    reflections: List[Dict]


# ============================================================
# ENDPOINTS
# ============================================================

@router.get("/stats", response_model=BrainStatsResponse, summary="Get Brain Statistics")
async def brain_stats():
    """Get comprehensive brain statistics."""
    brain = get_brain()
    return brain.get_stats()


@router.get("/lessons", response_model=LessonsResponse, summary="Get Learned Lessons")
async def get_lessons(category: Optional[str] = None, limit: int = 20):
    """Get learned lessons, optionally filtered by category."""
    brain = get_brain()
    lessons = []
    for lesson in brain.lessons.values():
        if category and lesson.category != category:
            continue
        lessons.append({
            "id": lesson.id,
            "pattern": lesson.pattern,
            "category": lesson.category,
            "confidence": lesson.confidence,
            "support_count": lesson.support_count,
            "contradict_count": lesson.contradict_count,
            "created_at": lesson.created_at,
            "last_reinforced": lesson.last_reinforced
        })
    # Sort by confidence
    lessons.sort(key=lambda x: x["confidence"], reverse=True)
    return {"lessons": lessons[:limit]}


@router.get("/skills", response_model=SkillsResponse, summary="Get Developed Skills")
async def get_skills():
    """Get procedural skills developed by the brain."""
    brain = get_brain()
    skills = []
    for skill in brain.skills.values():
        skills.append({
            "id": skill.id,
            "name": skill.name,
            "trigger_patterns": skill.trigger_patterns,
            "optimal_params": skill.optimal_params,
            "success_rate": skill.success_rate,
            "usage_count": skill.usage_count,
            "last_used": skill.last_used
        })
    skills.sort(key=lambda x: x["usage_count"], reverse=True)
    return {"skills": skills}


@router.get("/reflections", response_model=ReflectionsResponse, summary="Get Meta-Cognitive Reflections")
async def get_reflections(limit: int = 10):
    """Get meta-cognitive reflections on performance."""
    brain = get_brain()
    reflections = []
    for ref in brain.reflections[-limit:]:
        reflections.append({
            "id": ref.id,
            "timestamp": ref.timestamp,
            "period": ref.period,
            "total_interactions": ref.total_interactions,
            "success_rate": ref.success_rate,
            "tool_accuracy": ref.tool_accuracy,
            "discovered_patterns": ref.discovered_patterns,
            "improvement_goals": ref.improvement_goals,
            "insights": ref.insights
        })
    return {"reflections": reflections}


@router.post("/feedback", summary="Record User Feedback")
async def record_feedback(request: FeedbackRequest):
    """Record user feedback on an experience to improve learning."""
    brain = get_brain()
    brain.record_feedback(request.experience_id, request.feedback)
    return {"success": True, "message": f"Feedback '{request.feedback}' recorded"}


@router.get("/predict", summary="Predict Best Tools for Query")
async def predict_tools(query: str):
    """Get brain's prediction of best tools for a query."""
    brain = get_brain()
    predictions = brain.predict_best_tool(query)
    return {
        "query": query,
        "predictions": [{"tool": tool, "confidence": conf} for tool, conf in predictions]
    }


@router.get("/context", summary="Get Brain Context for Query")
async def get_context(query: str):
    """Get brain context that would be injected into LLM prompt."""
    brain = get_brain()
    context = brain.get_context_for_llm(query)
    return {"query": query, "context": context}


@router.post("/reset", summary="Reset Brain (Clear All Learning)")
async def reset_brain_endpoint():
    """Reset brain - clears all learned patterns, skills, and reflections."""
    reset_brain()
    return {"success": True, "message": "Brain reset - all learning cleared"}


@router.get("/experiences", summary="Get Recent Experiences")
async def get_experiences(limit: int = 20):
    """Get recent interaction experiences."""
    brain = get_brain()
    experiences = []
    for exp in brain.experiences[-limit:]:
        experiences.append({
            "id": exp.id,
            "timestamp": exp.timestamp,
            "user_query": exp.user_query,
            "intent_detected": exp.intent_detected,
            "tools_used": exp.tools_used,
            "success": exp.success,
            "response_summary": exp.response_summary,
            "latency_ms": exp.latency_ms,
            "user_feedback": exp.user_feedback
        })
    return {"experiences": experiences[::-1]}  # Most recent first


# ============================================================
# INTEGRATION HELPER
# ============================================================

def register_brain_routes(app):
    """Register brain routes with FastAPI app."""
    app.include_router(router)