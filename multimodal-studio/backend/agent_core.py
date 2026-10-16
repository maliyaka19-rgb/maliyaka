"""
NEXUS-CORE v5.1 - AGENT CORE
=============================
Real AI Agent with Plan → Act → Observe → Reflect loop.
Features: Memory, Tool Use, Self-Correction, Continuous Learning.
"""

import asyncio
import json
import time
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field, asdict
from collections import deque
import logging

logger = logging.getLogger("nexus-agent")


# ============================================================
# ENUMS & DATA CLASSES
# ============================================================

class AgentState(Enum):
    IDLE = "idle"
    PLANNING = "planning"
    ACTING = "acting"
    OBSERVING = "observing"
    REFLECTING = "reflecting"
    COMPLETED = "completed"
    ERROR = "error"


class ToolType(Enum):
    CODE_GEN = "code_generation"
    VISUAL_GEN = "visual_generation"
    VIDEO_GEN = "video_generation"
    LEARNING = "learning_query"
    WEB_SEARCH = "web_search"
    FILE_OPS = "file_operations"
    REASONING = "reasoning"


@dataclass
class MemoryEntry:
    """Single memory entry."""
    id: str
    type: str  # "short_term" | "long_term" | "episodic" | "semantic"
    content: Dict[str, Any]
    timestamp: str
    importance: float = 0.5
    tags: List[str] = field(default_factory=list)
    access_count: int = 0


@dataclass
class ToolResult:
    """Result from tool execution."""
    tool: str
    success: bool
    output: Any
    error: Optional[str] = None
    duration: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanStep:
    """Single step in execution plan."""
    id: str
    tool: ToolType
    params: Dict[str, Any]
    description: str
    depends_on: List[str] = field(default_factory=list)
    status: str = "pending"  # pending, running, completed, failed
    result: Optional[ToolResult] = None


@dataclass
class ExecutionPlan:
    """Complete execution plan."""
    id: str
    goal: str
    steps: List[PlanStep]
    created_at: str
    status: str = "pending"


@dataclass
class AgentContext:
    """Full agent context/state."""
    session_id: str
    user_goal: str
    state: AgentState = AgentState.IDLE
    plan: Optional[ExecutionPlan] = None
    current_step: int = 0
    memory: List[MemoryEntry] = field(default_factory=list)
    tool_history: List[ToolResult] = field(default_factory=list)
    reflections: List[str] = field(default_factory=list)
    error_count: int = 0
    max_retries: int = 3
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ============================================================
# MEMORY SYSTEM
# ============================================================

class MemorySystem:
    """Multi-tier memory system: short-term, long-term, episodic, semantic."""
    
    def __init__(self, max_short_term: int = 50, max_long_term: int = 1000):
        self.short_term: deque = deque(maxlen=max_short_term)
        self.long_term: Dict[str, MemoryEntry] = {}
        self.episodic: List[MemoryEntry] = []  # Event memories
        self.semantic: Dict[str, MemoryEntry] = {}  # Fact memories
        self.max_long_term = max_long_term
    
    def add(self, entry: MemoryEntry):
        """Add memory to appropriate tier."""
        if entry.type == "short_term":
            self.short_term.append(entry)
        elif entry.type == "long_term":
            if len(self.long_term) >= self.max_long_term:
                self._evict_oldest_long_term()
            self.long_term[entry.id] = entry
        elif entry.type == "episodic":
            self.episodic.append(entry)
        elif entry.type == "semantic":
            self.semantic[entry.id] = entry
    
    def _evict_oldest_long_term(self):
        """Remove least important, least accessed long-term memory."""
        if not self.long_term:
            return
        oldest = min(
            self.long_term.values(),
            key=lambda m: (m.importance, m.access_count, m.timestamp)
        )
        del self.long_term[oldest.id]
    
    def retrieve(self, query: str, limit: int = 10) -> List[MemoryEntry]:
        """Retrieve relevant memories across all tiers."""
        results = []
        query_lower = query.lower()
        
        # Search all tiers
        all_memories = (
            list(self.short_term) +
            list(self.long_term.values()) +
            self.episodic +
            list(self.semantic.values())
        )
        
        for mem in all_memories:
            mem.access_count += 1
            # Simple relevance scoring
            content_str = json.dumps(mem.content, ensure_ascii=False).lower()
            if query_lower in content_str or any(tag in query_lower for tag in mem.tags):
                relevance = content_str.count(query_lower) * 0.1 + mem.importance
                results.append((relevance, mem))
        
        results.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in results[:limit]]
    
    def get_recent(self, limit: int = 10) -> List[MemoryEntry]:
        """Get recent short-term memories."""
        return list(self.short_term)[-limit:]
    
    def consolidate(self):
        """Move important short-term to long-term."""
        for mem in list(self.short_term):
            if mem.importance > 0.7 or mem.access_count > 3:
                mem.type = "long_term"
                self.long_term[mem.id] = mem
                self.short_term.remove(mem)


# ============================================================
# TOOL REGISTRY
# ============================================================

class Tool:
    """Base tool class."""
    
    def __init__(self, name: str, tool_type: ToolType, description: str, func: Callable):
        self.name = name
        self.type = tool_type
        self.description = description
        self.func = func
    
    async def execute(self, params: Dict[str, Any]) -> ToolResult:
        start = time.time()
        try:
            result = await self.func(params)
            return ToolResult(
                tool=self.name,
                success=True,
                output=result,
                duration=time.time() - start
            )
        except Exception as e:
            return ToolResult(
                tool=self.name,
                success=False,
                output=None,
                error=str(e),
                duration=time.time() - start
            )


class ToolRegistry:
    """Registry of all available tools."""
    
    def __init__(self):
        self.tools: Dict[str, Tool] = {}
    
    def register(self, name: str, tool_type: ToolType, description: str, func: Callable):
        self.tools[name] = Tool(name, tool_type, description, func)
    
    def get(self, name: str) -> Optional[Tool]:
        return self.tools.get(name)
    
    def get_by_type(self, tool_type: ToolType) -> List[Tool]:
        return [t for t in self.tools.values() if t.type == tool_type]
    
    def list_all(self) -> List[Dict[str, str]]:
        return [
            {"name": t.name, "type": t.type.value, "description": t.description}
            for t in self.tools.values()
        ]


# ============================================================
# PLANNING MODULE
# ============================================================

class Planner:
    """Creates execution plans from user goals."""
    
    def __init__(self, tool_registry: ToolRegistry):
        self.tools = tool_registry
    
    async def create_plan(self, goal: str, context: AgentContext) -> ExecutionPlan:
        """Create execution plan from goal using available tools."""
        # Analyze goal to determine required tools
        required_tools = self._analyze_goal(goal)
        
        steps = []
        for i, tool_type in enumerate(required_tools):
            step = self._create_step(tool_type, goal, i, context)
            if step:
                steps.append(step)
        
        plan = ExecutionPlan(
            id=str(uuid.uuid4())[:8],
            goal=goal,
            steps=steps,
            created_at=datetime.now().isoformat()
        )
        return plan
    
    def _analyze_goal(self, goal: str) -> List[ToolType]:
        """Determine which tools are needed based on goal."""
        goal_lower = goal.lower()
        tools = []
        
        # Code generation keywords
        if any(kw in goal_lower for kw in ["kod", "code", "api", "function", "script", "uygulama", "backend", "frontend"]):
            tools.append(ToolType.CODE_GEN)
        
        # Visual generation keywords
        if any(kw in goal_lower for kw in ["görsel", "visual", "image", "resim", "prompt", "midjourney", "stable diffusion", "dall-e"]):
            tools.append(ToolType.VISUAL_GEN)
        
        # Video generation keywords
        if any(kw in goal_lower for kw in ["video", "film", "sahne", "scene", "timecode", "veo", "sora", "runway"]):
            tools.append(ToolType.VIDEO_GEN)
        
        # Learning query keywords
        if any(kw in goal_lower for kw in ["öğren", "learn", "memory", "rapor", "report", "geçmiş", "history"]):
            tools.append(ToolType.LEARNING)
        
        # Web search keywords
        if any(kw in goal_lower for kw in ["ara", "search", "bul", "find", "nedir", "what is", "nasıl", "how to"]):
            tools.append(ToolType.WEB_SEARCH)
        
        # Default to reasoning if nothing specific
        if not tools:
            tools.append(ToolType.REASONING)
        
        return tools
    
    def _create_step(self, tool_type: ToolType, goal: str, index: int, context: AgentContext) -> Optional[PlanStep]:
        """Create a plan step for a tool type."""
        tool_map = {
            ToolType.CODE_GEN: {
                "tool": "code_generation",
                "params": {"prompt": goal, "language": "python", "framework": "fastapi", "mode": "api"}
            },
            ToolType.VISUAL_GEN: {
                "tool": "visual_generation",
                "params": {"subject": goal, "environment": "cinematic lighting", "camera": "35mm f/1.8"}
            },
            ToolType.VIDEO_GEN: {
                "tool": "video_generation",
                "params": {"timecode": "[00:00 - 00:05]", "camera_movement": "cinematic", "motion_dynamics": goal}
            },
            ToolType.LEARNING: {
                "tool": "learning_query",
                "params": {"query": goal}
            },
            ToolType.WEB_SEARCH: {
                "tool": "web_search",
                "params": {"query": goal}
            },
            ToolType.REASONING: {
                "tool": "reasoning",
                "params": {"task": goal}
            }
        }
        
        config = tool_map.get(tool_type)
        if not config:
            return None
        
        return PlanStep(
            id=f"step_{index}",
            tool=tool_type,
            params=config["params"],
            description=f"Execute {tool_type.value} for: {goal[:50]}"
        )


# ============================================================
# REASONING ENGINE
# ============================================================

class ReasoningEngine:
    """Internal reasoning for complex tasks."""
    
    def __init__(self, memory: MemorySystem):
        self.memory = memory
    
    async def reason(self, task: str, context: AgentContext) -> Dict[str, Any]:
        """Perform reasoning on a task."""
        # Retrieve relevant memories
        memories = self.memory.retrieve(task, limit=5)
        
        # Simple reasoning: analyze task, break down, use memory
        reasoning = {
            "task": task,
            "analysis": self._analyze_task(task),
            "relevant_memories": len(memories),
            "suggested_approach": self._suggest_approach(task, memories),
            "confidence": 0.8
        }
        
        # Store reasoning as memory
        self.memory.add(MemoryEntry(
            id=str(uuid.uuid4())[:8],
            type="semantic",
            content={"reasoning": reasoning, "task": task},
            timestamp=datetime.now().isoformat(),
            importance=0.6,
            tags=["reasoning", "analysis"]
        ))
        
        return reasoning
    
    def _analyze_task(self, task: str) -> str:
        """Analyze task complexity and type."""
        if len(task) < 50:
            return "Simple direct task"
        elif any(kw in task.lower() for kw in ["ve", "and", "ardından", "then", "sonra"]):
            return "Multi-step sequential task"
        elif any(kw in task.lower() for kw in ["eğer", "if", "duruma göre", "depending"]):
            return "Conditional branching task"
        return "Complex task requiring decomposition"
    
    def _suggest_approach(self, task: str, memories: List[MemoryEntry]) -> str:
        """Suggest approach based on task and memories."""
        if memories:
            return f"Use {len(memories)} relevant past experiences"
        return "Direct execution with available tools"


# ============================================================
# REFLECTION ENGINE
# ============================================================

class ReflectionEngine:
    """Self-reflection and learning from execution."""
    
    def __init__(self, memory: MemorySystem):
        self.memory = memory
    
    async def reflect(self, context: AgentContext) -> Dict[str, Any]:
        """Reflect on execution results."""
        if not context.plan or not context.tool_history:
            return {"reflection": "No execution history to reflect on"}
        
        # Analyze results
        successful = sum(1 for r in context.tool_history if r.success)
        failed = len(context.tool_history) - successful
        
        reflection = {
            "session_id": context.session_id,
            "goal": context.user_goal,
            "total_steps": len(context.tool_history),
            "successful": successful,
            "failed": failed,
            "success_rate": successful / len(context.tool_history) if context.tool_history else 0,
            "lessons": [],
            "improvements": []
        }
        
        # Extract lessons from failures
        for result in context.tool_history:
            if not result.success:
                reflection["lessons"].append({
                    "tool": result.tool,
                    "error": result.error,
                    "lesson": f"Avoid {result.tool} with similar params: {result.error}"
                })
                reflection["improvements"].append(
                    f"Add validation for {result.tool} parameters"
                )
        
        # Store reflection
        self.memory.add(MemoryEntry(
            id=str(uuid.uuid4())[:8],
            type="episodic",
            content={"reflection": reflection},
            timestamp=datetime.now().isoformat(),
            importance=0.8,
            tags=["reflection", "learning"]
        ))
        
        context.reflections.append(json.dumps(reflection, ensure_ascii=False))
        return reflection


# ============================================================
# MAIN AGENT CLASS
# ============================================================

class NexusAgent:
    """Main NEXUS-CORE Agent with full Plan-Act-Observe-Reflect loop."""
    
    def __init__(self):
        self.memory = MemorySystem()
        self.tools = ToolRegistry()
        self.planner = Planner(self.tools)
        self.reasoning = ReasoningEngine(self.memory)
        self.reflection = ReflectionEngine(self.memory)
        self.context: Optional[AgentContext] = None
        
        # Register default tools
        self._register_default_tools()
    
    def _register_default_tools(self):
        """Register all available tools."""
        
        # Code Generation Tool
        async def code_gen(params):
            # This will be connected to actual backend endpoint
            return {"status": "code_generation_queued", "params": params}
        
        self.tools.register(
            "code_generation", ToolType.CODE_GEN,
            "Generate production-ready code (Python, JS, TS, etc.)",
            code_gen
        )
        
        # Visual Generation Tool
        async def visual_gen(params):
            return {"status": "visual_generation_queued", "params": params}
        
        self.tools.register(
            "visual_generation", ToolType.VISUAL_GEN,
            "Generate professional AI art prompts (Midjourney, SD, DALL-E)",
            visual_gen
        )
        
        # Video Generation Tool
        async def video_gen(params):
            return {"status": "video_generation_queued", "params": params}
        
        self.tools.register(
            "video_generation", ToolType.VIDEO_GEN,
            "Generate cinematic video prompts (Veo, Sora, Runway)",
            video_gen
        )
        
        # Learning Query Tool
        async def learning_query(params):
            query = params.get("query", "")
            memories = self.memory.retrieve(query, limit=5)
            return {
                "memories_found": len(memories),
                "memories": [asdict(m) for m in memories]
            }
        
        self.tools.register(
            "learning_query", ToolType.LEARNING,
            "Query learning memory and past experiences",
            learning_query
        )
        
        # Web Search Tool (placeholder)
        async def web_search(params):
            return {"status": "web_search_not_implemented", "query": params.get("query")}
        
        self.tools.register(
            "web_search", ToolType.WEB_SEARCH,
            "Search web for current information",
            web_search
        )
        
        # Reasoning Tool
        async def reasoning(params):
            return await self.reasoning.reason(params.get("task", ""), self.context)
        
        self.tools.register(
            "reasoning", ToolType.REASONING,
            "Internal reasoning and task analysis",
            reasoning
        )
    
    def connect_backend_tools(self, backend_functions: Dict[str, Callable]):
        """Connect actual backend API functions to tools."""
        if "code_generation" in backend_functions:
            self.tools.tools["code_generation"].func = backend_functions["code_generation"]
        if "visual_generation" in backend_functions:
            self.tools.tools["visual_generation"].func = backend_functions["visual_generation"]
        if "video_generation" in backend_functions:
            self.tools.tools["video_generation"].func = backend_functions["video_generation"]
        if "learning_query" in backend_functions:
            self.tools.tools["learning_query"].func = backend_functions["learning_query"]
    
    async def run(self, user_goal: str, session_id: str = None) -> Dict[str, Any]:
        """Main agent execution loop: Plan → Act → Observe → Reflect."""
        session_id = session_id or str(uuid.uuid4())[:8]
        
        # Initialize context
        self.context = AgentContext(
            session_id=session_id,
            user_goal=user_goal
        )
        
        # Store initial goal in memory
        self.memory.add(MemoryEntry(
            id=str(uuid.uuid4())[:8],
            type="episodic",
            content={"goal": user_goal, "session_id": session_id},
            timestamp=datetime.now().isoformat(),
            importance=0.9,
            tags=["goal", "session_start"]
        ))
        
        try:
            # PHASE 1: PLANNING
            self.context.state = AgentState.PLANNING
            self.context.plan = await self.planner.create_plan(user_goal, self.context)
            logger.info(f"Plan created: {len(self.context.plan.steps)} steps")
            
            # PHASE 2: ACTING (Execute Plan)
            self.context.state = AgentState.ACTING
            await self._execute_plan()
            
            # PHASE 3: OBSERVING (Evaluate Results)
            self.context.state = AgentState.OBSERVING
            await self._observe_results()
            
            # PHASE 4: REFLECTING (Learn from Execution)
            self.context.state = AgentState.REFLECTING
            reflection = await self.reflection.reflect(self.context)
            
            # Consolidate memory
            self.memory.consolidate()
            
            self.context.state = AgentState.COMPLETED
            self.context.updated_at = datetime.now().isoformat()
            
            return self._get_final_result(reflection)
            
        except Exception as e:
            self.context.state = AgentState.ERROR
            logger.error(f"Agent error: {e}")
            return {"success": False, "error": str(e), "session_id": session_id}
    
    async def _execute_plan(self):
        """Execute all steps in plan."""
        if not self.context.plan:
            return
        
        for i, step in enumerate(self.context.plan.steps):
            self.context.current_step = i
            step.status = "running"
            
            # Check dependencies
            if not self._check_dependencies(step):
                step.status = "failed"
                step.result = ToolResult(
                    tool=step.tool.value,
                    success=False,
                    output=None,
                    error="Dependencies not met"
                )
                continue
            
            # Execute tool
            tool = self.tools.get(step.tool.value)
            if tool:
                result = await tool.execute(step.params)
                step.result = result
                step.status = "completed" if result.success else "failed"
                self.context.tool_history.append(result)
                
                # Store in memory
                self.memory.add(MemoryEntry(
                    id=str(uuid.uuid4())[:8],
                    type="short_term",
                    content={
                        "step": step.id,
                        "tool": step.tool.value,
                        "params": step.params,
                        "result": asdict(result) if result else None
                    },
                    timestamp=datetime.now().isoformat(),
                    importance=0.7,
                    tags=["execution", step.tool.value]
                ))
            else:
                step.status = "failed"
                step.result = ToolResult(
                    tool=step.tool.value,
                    success=False,
                    output=None,
                    error=f"Tool not found: {step.tool.value}"
                )
    
    def _check_dependencies(self, step: PlanStep) -> bool:
        """Check if step dependencies are satisfied."""
        if not step.depends_on:
            return True
        for dep_id in step.depends_on:
            dep_step = next((s for s in self.context.plan.steps if s.id == dep_id), None)
            if not dep_step or dep_step.status != "completed":
                return False
        return True
    
    async def _observe_results(self):
        """Observe and evaluate execution results."""
        # Could add more sophisticated observation here
        pass
    
    def _get_final_result(self, reflection: Dict) -> Dict[str, Any]:
        """Compile final result."""
        return {
            "success": True,
            "session_id": self.context.session_id,
            "goal": self.context.user_goal,
            "state": self.context.state.value,
            "plan": {
                "id": self.context.plan.id,
                "steps": len(self.context.plan.steps),
                "completed": sum(1 for s in self.context.plan.steps if s.status == "completed")
            },
            "tool_results": [asdict(r) for r in self.context.tool_history],
            "reflection": reflection,
            "memory_stats": {
                "short_term": len(self.memory.short_term),
                "long_term": len(self.memory.long_term),
                "episodic": len(self.memory.episodic),
                "semantic": len(self.memory.semantic)
            }
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get current agent status."""
        if not self.context:
            return {
                "session_id": None,
                "state": "idle",
                "goal": None,
                "current_step": 0,
                "total_steps": 0,
                "memory_counts": {
                    "short_term": len(self.memory.short_term),
                    "long_term": len(self.memory.long_term)
                }
            }
        return {
            "session_id": self.context.session_id,
            "state": self.context.state.value,
            "goal": self.context.user_goal,
            "current_step": self.context.current_step,
            "total_steps": len(self.context.plan.steps) if self.context.plan else 0,
            "memory_counts": {
                "short_term": len(self.memory.short_term),
                "long_term": len(self.memory.long_term)
            }
        }


# ============================================================
# GLOBAL AGENT INSTANCE
# ============================================================

_agent_instance: Optional[NexusAgent] = None

def get_agent() -> NexusAgent:
    """Get or create global agent instance."""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = NexusAgent()
    return _agent_instance

async def run_agent(goal: str, session_id: str = None) -> Dict[str, Any]:
    """Run agent with a goal."""
    agent = get_agent()
    return await agent.run(goal, session_id)

def get_agent_status() -> Dict[str, Any]:
    """Get agent status."""
    agent = get_agent()
    return agent.get_status()