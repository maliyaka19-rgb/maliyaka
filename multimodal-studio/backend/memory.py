"""
Conversation & Learning Memory for NEXUS-CORE
=============================================
Extracted from ai_agent.py (Phase 3.2 modularization).
"""
from dataclasses import dataclass, field
from datetime import datetime
from collections import deque
from typing import Dict, List, Optional, Any
import time
import uuid

# ============================================================
# CONVERSATION MEMORY
# ============================================================

@dataclass
class Message:
    """Single chat message."""
    role: str  # "system", "user", "assistant", "tool"
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    tool_calls: Optional[List[Dict]] = None
    tool_call_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Conversation:
    """Chat conversation with memory."""
    id: str
    messages: List[Message] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


class ConversationMemory:
    """Manages chat conversations and history."""
    
    def __init__(self, max_history: int = 50):
        self.conversations: Dict[str, Conversation] = {}
        self.max_history = max_history
    
    def get_or_create(self, conversation_id: str = None) -> Conversation:
        """Get existing or create new conversation."""
        if conversation_id is None:
            conversation_id = str(uuid.uuid4())[:12]
        
        if conversation_id not in self.conversations:
            self.conversations[conversation_id] = Conversation(id=conversation_id)
        
        return self.conversations[conversation_id]
    
    def add_message(self, conversation_id: str, message: Message):
        """Add message to conversation."""
        conv = self.get_or_create(conversation_id)
        conv.messages.append(message)
        conv.updated_at = datetime.now().isoformat()
        
        # Trim if too long
        if len(conv.messages) > self.max_history:
            conv.messages = conv.messages[-self.max_history:]
    
    def get_history(self, conversation_id: str, include_system: bool = True) -> List[Dict]:
        """Get conversation history in OpenAI format."""
        conv = self.get_or_create(conversation_id)
        
        history = []
        for msg in conv.messages:
            if msg.role == "system" and not include_system:
                continue
            
            entry = {"role": msg.role, "content": msg.content}
            
            if msg.tool_calls:
                entry["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            
            history.append(entry)
        
        return history


# ============================================================
# LEARNING MEMORY
# ============================================================

class LearningMemory:
    """Long-term learning from interactions."""
    
    def __init__(self):
        self.lessons: Dict[str, Dict] = {}
        self.stats: Dict[str, int] = {"total_queries": 0, "successful": 0, "failed": 0}
    
    def record(self, query: str, tools_used: List[str], success: bool, response_summary: str = ""):
        """Record an interaction."""
        self.stats["total_queries"] += 1
        if success:
            self.stats["successful"] += 1
        else:
            self.stats["failed"] += 1
        
        # Store lesson
        lesson_id = str(uuid.uuid4())[:8]
        self.lessons[lesson_id] = {
            "query": query[:200],
            "tools_used": tools_used,
            "success": success,
            "response_summary": response_summary[:200],
            "timestamp": datetime.now().isoformat()
        }
    
    def get_similar(self, query: str, limit: int = 5) -> List[Dict]:
        """Find similar past queries."""
        query_lower = query.lower()
        results = []
        
        for lesson in self.lessons.values():
            if query_lower in lesson["query"].lower():
                results.append(lesson)
        
        return results[:limit]


