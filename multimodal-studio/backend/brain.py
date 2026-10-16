"""
NEXUS-CORE v6.1 - BRAIN MODULE
===============================
Self-improving cognitive architecture with:
- Episodic memory (what happened)
- Semantic memory (facts, patterns, lessons)
- Procedural memory (skills, tool usage patterns)
- Meta-cognition (reflection on own performance)
- Continuous learning loop
"""

import json
import time
import uuid
import os
from datetime import datetime
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field, asdict
from collections import defaultdict, deque
import logging
from pathlib import Path

logger = logging.getLogger("nexus-brain")

# ============================================================
# MEMORY STRUCTURES
# ============================================================

@dataclass
class Experience:
    """Single interaction experience."""
    id: str
    timestamp: str
    user_query: str
    intent_detected: str
    tools_used: List[str]
    success: bool
    response_summary: str
    latency_ms: int
    tokens_used: int = 0
    error: Optional[str] = None
    user_feedback: Optional[str] = None  # "good", "bad", "correction"
    context: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Lesson:
    """Extracted pattern/lesson from experiences."""
    id: str
    pattern: str           # e.g., "hello world -> script mode"
    category: str          # "code", "visual", "video", "general", "tool_usage"
    confidence: float      # 0.0 - 1.0
    support_count: int     # How many experiences support this
    contradict_count: int  # How many contradict
    created_at: str
    last_reinforced: str
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Skill:
    """Procedural knowledge - how to do something well."""
    id: str
    name: str              # e.g., "generate_python_script"
    trigger_patterns: List[str]  # When to use this skill
    optimal_params: Dict[str, Any]  # Best parameters discovered
    success_rate: float
    usage_count: int
    last_used: str
    evolved_from: Optional[str] = None  # Parent skill ID

@dataclass
class Reflection:
    """Meta-cognitive reflection on performance."""
    id: str
    timestamp: str
    period: str            # "session", "day", "week"
    total_interactions: int
    success_rate: float
    tool_accuracy: Dict[str, float]  # Per-tool success rates
    discovered_patterns: List[str]
    improvement_goals: List[str]
    insights: List[str]

# ============================================================
# BRAIN CORE
# ============================================================

class NexusBrain:
    """
    Self-improving cognitive system.
    Learns from every interaction, extracts patterns, optimizes behavior.
    """
    
    def __init__(self, storage_path: str = "brain_data"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(exist_ok=True)
        
        # Memory stores
        self.experiences: List[Experience] = []
        self.lessons: Dict[str, Lesson] = {}
        self.skills: Dict[str, Skill] = {}
        self.reflections: List[Reflection] = []
        
        # Indexes for fast retrieval
        self._intent_index: Dict[str, List[str]] = defaultdict(list)  # intent -> experience IDs
        self._tool_index: Dict[str, List[str]] = defaultdict(list)    # tool -> experience IDs
        self._pattern_index: Dict[str, List[str]] = defaultdict(list) # pattern -> lesson IDs
        
        # Working memory (current session)
        self.working_memory: deque = deque(maxlen=50)
        self.session_stats = {"total": 0, "success": 0, "tools_used": defaultdict(int)}
        
        # Load persisted memory
        self._load()
        
        # Auto-save interval
        self._last_save = time.time()
        self._save_interval = 30  # seconds
    
    # --------------------------------------------------------
    # PERSISTENCE
    # --------------------------------------------------------
    
    def _load(self):
        """Load all memory from disk."""
        try:
            # Experiences
            exp_file = self.storage_path / "experiences.json"
            if exp_file.exists():
                with open(exp_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.experiences = [Experience(**e) for e in data[-1000:]]  # Keep last 1000
                    self._rebuild_indexes()
            
            # Lessons
            les_file = self.storage_path / "lessons.json"
            if les_file.exists():
                with open(les_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.lessons = {k: Lesson(**v) for k, v in data.items()}
            
            # Skills
            sk_file = self.storage_path / "skills.json"
            if sk_file.exists():
                with open(sk_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.skills = {k: Skill(**v) for k, v in data.items()}
            
            # Reflections
            ref_file = self.storage_path / "reflections.json"
            if ref_file.exists():
                with open(ref_file, 'r', encoding='utf-8') as f:
                    self.reflections = [Reflection(**r) for r in json.load(f)]
            
            logger.info(f"Brain loaded: {len(self.experiences)} experiences, "
                       f"{len(self.lessons)} lessons, {len(self.skills)} skills")
        except Exception as e:
            logger.warning(f"Brain load failed (starting fresh): {e}")
    
    def _save(self, force: bool = False):
        """Persist memory to disk."""
        if not force and time.time() - self._last_save < self._save_interval:
            return
        
        try:
            # Experiences (keep last 1000)
            with open(self.storage_path / "experiences.json", 'w', encoding='utf-8') as f:
                json.dump([asdict(e) for e in self.experiences[-1000:]], f, ensure_ascii=False, indent=2)
            
            # Lessons
            with open(self.storage_path / "lessons.json", 'w', encoding='utf-8') as f:
                json.dump({k: asdict(v) for k, v in self.lessons.items()}, f, ensure_ascii=False, indent=2)
            
            # Skills
            with open(self.storage_path / "skills.json", 'w', encoding='utf-8') as f:
                json.dump({k: asdict(v) for k, v in self.skills.items()}, f, ensure_ascii=False, indent=2)
            
            # Reflections
            with open(self.storage_path / "reflections.json", 'w', encoding='utf-8') as f:
                json.dump([asdict(r) for r in self.reflections], f, ensure_ascii=False, indent=2)
            
            self._last_save = time.time()
            logger.debug("Brain saved successfully")
        except Exception as e:
            logger.error(f"Brain save failed: {e}")
    
    def _rebuild_indexes(self):
        """Rebuild lookup indexes from experiences."""
        self._intent_index.clear()
        self._tool_index.clear()
        for exp in self.experiences:
            self._intent_index[exp.intent_detected].append(exp.id)
            for tool in exp.tools_used:
                self._tool_index[tool].append(exp.id)
    
    # --------------------------------------------------------
    # EXPERIENCE RECORDING (called after each interaction)
    # --------------------------------------------------------
    
    def record_experience(self, 
                         user_query: str,
                         intent_detected: str,
                         tools_used: List[str],
                         success: bool,
                         response_summary: str,
                         latency_ms: int,
                         tokens_used: int = 0,
                         error: Optional[str] = None,
                         context: Dict = None) -> str:
        """Record a new experience and trigger learning."""
        exp_id = str(uuid.uuid4())[:12]
        exp = Experience(
            id=exp_id,
            timestamp=datetime.now().isoformat(),
            user_query=user_query[:500],
            intent_detected=intent_detected,
            tools_used=tools_used,
            success=success,
            response_summary=response_summary[:300],
            latency_ms=latency_ms,
            tokens_used=tokens_used,
            error=error,
            context=context or {}
        )
        
        self.experiences.append(exp)
        self.working_memory.append(exp)
        
        # Update indexes
        self._intent_index[intent_detected].append(exp_id)
        for tool in tools_used:
            self._tool_index[tool].append(exp_id)
        
        # Update session stats
        self.session_stats["total"] += 1
        if success:
            self.session_stats["success"] += 1
        for tool in tools_used:
            self.session_stats["tools_used"][tool] += 1
        
        # Trigger incremental learning
        self._extract_lessons_from_experience(exp)
        self._update_skills_from_experience(exp)
        
        # Periodic reflection
        if self.session_stats["total"] % 10 == 0:
            self._reflect()
        
        self._save()
        return exp_id
    
    def record_feedback(self, experience_id: str, feedback: str):
        """Record user feedback on an experience."""
        for exp in self.experiences:
            if exp.id == experience_id:
                exp.user_feedback = feedback
                # Adjust lesson confidence based on feedback
                self._adjust_lessons_from_feedback(exp, feedback)
                self._save()
                break
    
    # --------------------------------------------------------
    # LESSON EXTRACTION (Pattern Learning)
    # --------------------------------------------------------
    
    def _extract_lessons_from_experience(self, exp: Experience):
        """Extract/update lessons from a single experience."""
        patterns = self._generate_patterns(exp)
        
        for pattern, category in patterns:
            # Find or create lesson
            lesson_id = self._pattern_to_id(pattern)
            
            if lesson_id in self.lessons:
                lesson = self.lessons[lesson_id]
                if exp.success:
                    lesson.support_count += 1
                else:
                    lesson.contradict_count += 1
                lesson.last_reinforced = datetime.now().isoformat()
                lesson.confidence = self._calculate_confidence(lesson)
            else:
                # New lesson
                confidence = 0.6 if exp.success else 0.3
                lesson = Lesson(
                    id=lesson_id,
                    pattern=pattern,
                    category=category,
                    confidence=confidence,
                    support_count=1 if exp.success else 0,
                    contradict_count=0 if exp.success else 1,
                    created_at=datetime.now().isoformat(),
                    last_reinforced=datetime.now().isoformat(),
                    metadata={"first_experience": exp.id}
                )
                self.lessons[lesson_id] = lesson
                self._pattern_index[pattern].append(lesson_id)
    
    def _generate_patterns(self, exp: Experience) -> List[tuple]:
        """Generate pattern strings from experience."""
        patterns = []
        q = exp.user_query.lower()
        
        # Intent-tool pairing patterns
        if exp.tools_used:
            patterns.append((f"{exp.intent_detected} -> {','.join(exp.tools_used)}", "tool_usage"))
        
        # Query pattern -> tool mapping
        if "hello world" in q or "basit" in q or "simple" in q:
            patterns.append(("simple_query -> script_mode", "code"))
        if "api" in q or "rest" in q or "endpoint" in q:
            patterns.append(("api_request -> api_mode", "code"))
        if "midjourney" in q or "görsel" in q or "visual" in q:
            patterns.append(("visual_request -> generate_visual_prompt", "visual"))
        if "video" in q or "film" in q or "sahne" in q:
            patterns.append(("video_request -> generate_video_prompt", "video"))
        
        # Language detection patterns
        for lang in ["python", "javascript", "typescript", "bash", "sql"]:
            if lang in q:
                patterns.append((f"language:{lang} -> {lang}", "code"))
                break
        
        # Success/failure patterns
        if exp.error:
            patterns.append((f"error:{exp.error[:50]} -> check_params", "error_handling"))
        
        return patterns
    
    def _pattern_to_id(self, pattern: str) -> str:
        """Generate stable ID from pattern."""
        import hashlib
        return hashlib.md5(pattern.encode()).hexdigest()[:12]
    
    def _calculate_confidence(self, lesson: Lesson) -> float:
        """Calculate lesson confidence from support/contradict counts."""
        total = lesson.support_count + lesson.contradict_count
        if total == 0:
            return 0.5
        base = lesson.support_count / total
        # Boost confidence with more evidence
        evidence_boost = min(total * 0.02, 0.3)
        return min(base + evidence_boost, 0.95)
    
    def _adjust_lessons_from_feedback(self, exp: Experience, feedback: str):
        """Adjust lesson confidence based on user feedback."""
        patterns = self._generate_patterns(exp)
        for pattern, _ in patterns:
            lesson_id = self._pattern_to_id(pattern)
            if lesson_id in self.lessons:
                lesson = self.lessons[lesson_id]
                if feedback == "good":
                    lesson.support_count += 2
                elif feedback == "bad":
                    lesson.contradict_count += 2
                lesson.confidence = self._calculate_confidence(lesson)
    
    # --------------------------------------------------------
    # SKILL EVOLUTION (Procedural Learning)
    # --------------------------------------------------------
    
    def _update_skills_from_experience(self, exp: Experience):
        """Update or create skills from successful experiences."""
        if not exp.success or not exp.tools_used:
            return
        
        for tool in exp.tools_used:
            skill_name = f"optimal_{tool}"
            
            if skill_name in self.skills:
                skill = self.skills[skill_name]
                skill.usage_count += 1
                skill.last_used = datetime.now().isoformat()
                # Update success rate with exponential moving average
                alpha = 0.1
                skill.success_rate = (1 - alpha) * skill.success_rate + alpha * 1.0
                
                # Extract optimal params from context
                if exp.context:
                    for k, v in exp.context.items():
                        if k not in skill.optimal_params:
                            skill.optimal_params[k] = v
            else:
                # Create new skill
                skill = Skill(
                    id=str(uuid.uuid4())[:12],
                    name=skill_name,
                    trigger_patterns=[exp.intent_detected],
                    optimal_params=exp.context or {},
                    success_rate=1.0,
                    usage_count=1,
                    last_used=datetime.now().isoformat()
                )
                self.skills[skill_name] = skill
    
    # --------------------------------------------------------
    # REFLECTION (Meta-Cognition)
    # --------------------------------------------------------
    
    def _reflect(self):
        """Perform meta-cognitive reflection on recent performance."""
        if len(self.experiences) < 5:
            return
        
        recent = self.experiences[-20:]
        total = len(recent)
        success = sum(1 for e in recent if e.success)
        success_rate = success / total if total > 0 else 0
        
        # Per-tool accuracy
        tool_stats = defaultdict(lambda: {"total": 0, "success": 0})
        for e in recent:
            for tool in e.tools_used:
                tool_stats[tool]["total"] += 1
                if e.success:
                    tool_stats[tool]["success"] += 1
        
        tool_accuracy = {}
        for tool, stats in tool_stats.items():
            tool_accuracy[tool] = stats["success"] / stats["total"] if stats["total"] > 0 else 0
        
        # Discover patterns from recent lessons
        recent_lessons = [l for l in self.lessons.values() 
                         if l.last_reinforced > recent[0].timestamp]
        discovered = [l.pattern for l in recent_lessons if l.confidence > 0.7]
        
        # Generate improvement goals
        goals = []
        if success_rate < 0.8:
            goals.append("Improve overall success rate")
        for tool, acc in tool_accuracy.items():
            if acc < 0.7:
                goals.append(f"Improve {tool} accuracy ({acc:.0%})")
        
        # Generate insights
        insights = []
        if len(self.lessons) > 10:
            insights.append(f"Learned {len(self.lessons)} patterns from experience")
        if len(self.skills) > 3:
            insights.append(f"Developed {len(self.skills)} procedural skills")
        
        reflection = Reflection(
            id=str(uuid.uuid4())[:12],
            timestamp=datetime.now().isoformat(),
            period="session",
            total_interactions=total,
            success_rate=success_rate,
            tool_accuracy=tool_accuracy,
            discovered_patterns=discovered[:5],
            improvement_goals=goals[:3],
            insights=insights
        )
        
        self.reflections.append(reflection)
        logger.info(f"Reflection: {success_rate:.0%} success, goals: {goals}")
    
    # --------------------------------------------------------
    # QUERY INTERFACE (Used by agent for better decisions)
    # --------------------------------------------------------
    
    def get_relevant_lessons(self, query: str, category: str = None, limit: int = 5) -> List[Lesson]:
        """Get lessons relevant to current query."""
        q_lower = query.lower()
        relevant = []
        
        for lesson in self.lessons.values():
            if category and lesson.category != category:
                continue
            # Check if pattern keywords appear in query
            pattern_words = set(lesson.pattern.lower().split(" -> ")[0].split())
            query_words = set(q_lower.split())
            if pattern_words & query_words:  # Intersection
                relevant.append(lesson)
        
        # Sort by confidence and recency
        relevant.sort(key=lambda l: (l.confidence, l.last_reinforced), reverse=True)
        return relevant[:limit]
    
    def get_optimal_skill(self, intent: str, tool: str) -> Optional[Skill]:
        """Get best skill for intent+tool combination."""
        skill_name = f"optimal_{tool}"
        skill = self.skills.get(skill_name)
        if skill and intent in skill.trigger_patterns:
            return skill
        # Fallback: any skill for this tool
        return self.skills.get(skill_name)
    
    def predict_best_tool(self, query: str) -> List[tuple]:
        """Predict best tools for query based on learned patterns."""
        predictions = []
        q_lower = query.lower()
        
        for lesson in self.lessons.values():
            if lesson.category == "tool_usage" and lesson.confidence > 0.6:
                pattern_part = lesson.pattern.split(" -> ")[0]
                if any(word in q_lower for word in pattern_part.split()):
                    tools = lesson.pattern.split(" -> ")[1].split(",")
                    for tool in tools:
                        predictions.append((tool.strip(), lesson.confidence))
        
        # Deduplicate and sort
        seen = set()
        unique = []
        for tool, conf in predictions:
            if tool not in seen:
                seen.add(tool)
                unique.append((tool, conf))
        
        return sorted(unique, key=lambda x: x[1], reverse=True)
    
    def get_context_for_llm(self, query: str) -> str:
        """Generate context string for LLM to make better decisions."""
        lessons = self.get_relevant_lessons(query, limit=3)
        skills = [self.get_optimal_skill("code", "generate_code"),
                  self.get_optimal_skill("visual", "generate_visual_prompt"),
                  self.get_optimal_skill("video", "generate_video_prompt")]
        skills = [s for s in skills if s]
        
        context_parts = []
        
        if lessons:
            context_parts.append("LEARNED PATTERNS:")
            for l in lessons:
                context_parts.append(f"  - {l.pattern} (confidence: {l.confidence:.0%})")
        
        if skills:
            context_parts.append("OPTIMAL SKILLS:")
            for s in skills:
                context_parts.append(f"  - {s.name}: {s.optimal_params}")
        
        # Recent success pattern
        recent_success = [e for e in self.experiences[-10:] if e.success]
        if recent_success:
            context_parts.append(f"RECENT SUCCESS RATE: {len(recent_success)}/10")
        
        return "\n".join(context_parts) if context_parts else "No prior learning context."
    
    def get_stats(self) -> Dict:
        """Get brain statistics."""
        return {
            "experiences_total": len(self.experiences),
            "lessons_learned": len(self.lessons),
            "skills_developed": len(self.skills),
            "reflections": len(self.reflections),
            "session_stats": self.session_stats,
            "top_lessons": sorted(
                [(l.pattern, l.confidence, l.category) for l in self.lessons.values()],
                key=lambda x: x[1], reverse=True
            )[:10],
            "tool_accuracy": {
                tool: sum(1 for e in self.experiences if tool in e.tools_used and e.success) / 
                      max(1, sum(1 for e in self.experiences if tool in e.tools_used))
                for tool in ["generate_code", "generate_visual_prompt", "generate_video_prompt", "answer_question"]
            }
        }

# ============================================================
# GLOBAL BRAIN INSTANCE
# ============================================================

_brain: Optional[NexusBrain] = None

def get_brain() -> NexusBrain:
    global _brain
    if _brain is None:
        _brain = NexusBrain()
    return _brain

def reset_brain():
    global _brain
    _brain = None
    return get_brain()