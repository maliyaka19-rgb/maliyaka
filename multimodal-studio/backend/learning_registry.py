"""
NEXUS-CORE v5.0 - Learning Registry System
===========================================
Continuous self-improvement mechanism that stores, retrieves, and applies
lessons learned from every project to optimize future outputs.

This module implements:
- Project outcome logging
- Pattern extraction from successful completions
- Adaptive parameter optimization
- Cross-project knowledge transfer
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
import hashlib


@dataclass
class ProjectLesson:
    """Single lesson extracted from a project."""
    lesson_id: str
    category: str  # "code", "visual", "video", "architecture", "prompt_engineering"
    description: str
    pattern: str  # The reusable pattern/technique
    confidence: float  # 0.0 - 1.0
    project_context: str
    timestamp: str
    usage_count: int = 0
    effectiveness_score: float = 0.0


@dataclass
class ProjectRecord:
    """Complete record of a project execution."""
    project_id: str
    user_prompt: str
    project_type: str  # "code", "visual", "video", "full_stack"
    timestamp: str
    duration_seconds: float
    success: bool
    generated_artifacts: Dict[str, Any]
    lessons_extracted: List[str]  # lesson_ids
    performance_metrics: Dict[str, float]
    user_feedback: Optional[str] = None


class LearningRegistry:
    """
    Central learning registry for NEXUS-CORE v5.0.
    
    Manages persistent storage of:
    - Extracted lessons from projects
    - Project execution history
    - Optimized parameters for each module
    - Success/failure patterns
    """
    
    def __init__(self, registry_path: str = "learning_registry"):
        self.registry_path = Path(registry_path)
        self.registry_path.mkdir(exist_ok=True)
        
        self.lessons_file = self.registry_path / "lessons.json"
        self.projects_file = self.registry_path / "projects.json"
        self.parameters_file = self.registry_path / "optimized_parameters.json"
        
        # Load existing data
        self.lessons: Dict[str, ProjectLesson] = {}
        self.projects: List[ProjectRecord] = []
        self.optimized_parameters: Dict[str, Any] = {}
        
        self._load_registry()
    
    def _load_registry(self):
        """Load learning data from persistent storage."""
        try:
            if self.lessons_file.exists():
                with open(self.lessons_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.lessons = {k: ProjectLesson(**v) for k, v in data.items()}
            
            if self.projects_file.exists():
                with open(self.projects_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.projects = [ProjectRecord(**p) for p in data]
            
            if self.parameters_file.exists():
                with open(self.parameters_file, 'r', encoding='utf-8') as f:
                    self.optimized_parameters = json.load(f)
                    
        except Exception as e:
            print(f"Warning: Could not load learning registry: {e}")
    
    def _save_registry(self):
        """Persist learning data to storage."""
        try:
            with open(self.lessons_file, 'w', encoding='utf-8') as f:
                json.dump({k: asdict(v) for k, v in self.lessons.items()}, f, indent=2, ensure_ascii=False)
            
            with open(self.projects_file, 'w', encoding='utf-8') as f:
                json.dump([asdict(p) for p in self.projects], f, indent=2, ensure_ascii=False)
            
            with open(self.parameters_file, 'w', encoding='utf-8') as f:
                json.dump(self.optimized_parameters, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            print(f"Warning: Could not save learning registry: {e}")
    
    def _generate_id(self, prefix: str, content: str) -> str:
        """Generate unique ID from content hash."""
        hash_obj = hashlib.md5(content.encode())
        return f"{prefix}_{hash_obj.hexdigest()[:12]}"
    
    def record_project(self, 
                       user_prompt: str,
                       project_type: str,
                       duration_seconds: float,
                       success: bool,
                       generated_artifacts: Dict[str, Any],
                       performance_metrics: Dict[str, float] = None,
                       user_feedback: str = None) -> str:
        """
        Record a completed project and extract lessons.
        
        Returns:
            project_id for reference
        """
        project_id = self._generate_id("proj", user_prompt + str(datetime.now()))
        
        # Extract lessons from this project
        lessons = self._extract_lessons(project_id, user_prompt, project_type, 
                                       generated_artifacts, success)
        
        project = ProjectRecord(
            project_id=project_id,
            user_prompt=user_prompt,
            project_type=project_type,
            timestamp=datetime.now().isoformat(),
            duration_seconds=duration_seconds,
            success=success,
            generated_artifacts=generated_artifacts,
            lessons_extracted=[l.lesson_id for l in lessons],
            performance_metrics=performance_metrics or {},
            user_feedback=user_feedback
        )
        
        self.projects.append(project)
        
        # Add extracted lessons
        for lesson in lessons:
            if lesson.lesson_id not in self.lessons:
                self.lessons[lesson.lesson_id] = lesson
            else:
                # Update existing lesson
                existing = self.lessons[lesson.lesson_id]
                existing.usage_count += 1
                existing.effectiveness_score = (
                    (existing.effectiveness_score * (existing.usage_count - 1) + 
                     (1.0 if success else 0.0)) / existing.usage_count
                )
        
        # Update optimized parameters based on project outcomes
        self._update_optimized_parameters(project_type, generated_artifacts, success)
        
        self._save_registry()
        
        return project_id
    
    def _extract_lessons(self, 
                         project_id: str,
                         user_prompt: str,
                         project_type: str,
                         artifacts: Dict[str, Any],
                         success: bool) -> List[ProjectLesson]:
        """Extract reusable lessons from project artifacts."""
        lessons = []
        
        if not success:
            # Even failures teach us what to avoid
            lesson_id = self._generate_id("lesson_avoid", user_prompt)
            lessons.append(ProjectLesson(
                lesson_id=lesson_id,
                category="anti_pattern",
                description=f"Failed approach for: {user_prompt[:100]}",
                pattern=f"Avoid: {project_type} pattern that led to failure",
                confidence=0.7,
                project_context=project_id,
                timestamp=datetime.now().isoformat()
            ))
            return lessons
        
        # Extract code generation lessons
        if "code" in artifacts:
            code = artifacts["code"]
            if isinstance(code, str) and len(code) > 100:
                # Look for successful patterns
                if "async def" in code and "FastAPI" in code:
                    lesson_id = self._generate_id("lesson", "fastapi_async_pattern")
                    lessons.append(ProjectLesson(
                        lesson_id=lesson_id,
                        category="code",
                        description="Async FastAPI pattern with proper error handling",
                        pattern="Use async/await with FastAPI, include try/except, return structured responses",
                        confidence=0.9,
                        project_context=project_id,
                        timestamp=datetime.now().isoformat()
                    ))
                
                if "pydantic" in code.lower() and "BaseModel" in code:
                    lesson_id = self._generate_id("lesson", "pydantic_validation")
                    lessons.append(ProjectLesson(
                        lesson_id=lesson_id,
                        category="code",
                        description="Pydantic model validation for request/response",
                        pattern="Always use Pydantic BaseModel for input validation and response serialization",
                        confidence=0.95,
                        project_context=project_id,
                        timestamp=datetime.now().isoformat()
                    ))
        
        # Extract visual prompt lessons
        if "visual_prompt" in artifacts:
            prompt = artifacts["visual_prompt"]
            if isinstance(prompt, str) and "--ar" in prompt and "--style" in prompt:
                lesson_id = self._generate_id("lesson", "midjourney_parametric_format")
                lessons.append(ProjectLesson(
                    lesson_id=lesson_id,
                    category="visual",
                    description="Midjourney v6 parametric prompt format",
                    pattern="Subject, Environment & Lighting, Camera & Lens, Style, --ar 16:9 --style raw --v 6.0",
                    confidence=0.95,
                    project_context=project_id,
                    timestamp=datetime.now().isoformat()
                ))
        
        # Extract video prompt lessons
        if "video_prompt" in artifacts:
            prompt = artifacts["video_prompt"]
            if isinstance(prompt, str) and "Timecode" in prompt:
                lesson_id = self._generate_id("lesson", "cinematic_timecode_format")
                lessons.append(ProjectLesson(
                    lesson_id=lesson_id,
                    category="video",
                    description="Cinematic timecode-based video prompt structure",
                    pattern="Timecode + Camera Movement + Motion Dynamics + Video AI Prompt format",
                    confidence=0.9,
                    project_context=project_id,
                    timestamp=datetime.now().isoformat()
                ))
        
        # Architecture lessons
        if project_type == "full_stack":
            lesson_id = self._generate_id("lesson", "fullstack_architecture")
            lessons.append(ProjectLesson(
                lesson_id=lesson_id,
                category="architecture",
                description="Full-stack architecture with FastAPI + Next.js + Docker",
                pattern="Separate backend/frontend, shared types, docker-compose orchestration, env-based config",
                confidence=0.85,
                project_context=project_id,
                timestamp=datetime.now().isoformat()
            ))
        
        return lessons
    
    def _update_optimized_parameters(self, 
                                     project_type: str,
                                     artifacts: Dict[str, Any],
                                     success: bool):
        """Update optimized parameters based on project success."""
        if project_type not in self.optimized_parameters:
            self.optimized_parameters[project_type] = {
                "successful_patterns": [],
                "failed_patterns": [],
                "parameter_preferences": {},
                "success_rate": 0.0,
                "total_projects": 0
            }
        
        params = self.optimized_parameters[project_type]
        params["total_projects"] += 1
        
        if success:
            params["successful_patterns"].append({
                "timestamp": datetime.now().isoformat(),
                "artifacts_keys": list(artifacts.keys())
            })
        else:
            params["failed_patterns"].append({
                "timestamp": datetime.now().isoformat(),
                "artifacts_keys": list(artifacts.keys())
            })
        
        # Recalculate success rate
        successful = len(params["successful_patterns"])
        total = params["total_projects"]
        params["success_rate"] = successful / total if total > 0 else 0.0
    
    def get_relevant_lessons(self, 
                            category: str = None,
                            min_confidence: float = 0.7,
                            limit: int = 10) -> List[ProjectLesson]:
        """Get lessons relevant for current task, ordered by effectiveness."""
        filtered = [
            l for l in self.lessons.values()
            if (category is None or l.category == category)
            and l.confidence >= min_confidence
        ]
        
        # Sort by effectiveness score (usage-weighted confidence)
        filtered.sort(
            key=lambda x: x.effectiveness_score * x.confidence * (1 + x.usage_count * 0.1),
            reverse=True
        )
        
        return filtered[:limit]
    
    def get_optimized_parameters(self, project_type: str) -> Dict[str, Any]:
        """Get optimized parameters for a project type."""
        return self.optimized_parameters.get(project_type, {})
    
    def apply_learned_optimizations(self, 
                                    project_type: str,
                                    base_config: Dict[str, Any]) -> Dict[str, Any]:
        """Apply learned optimizations to a base configuration."""
        optimized = self.get_optimized_parameters(project_type)
        lessons = self.get_relevant_lessons(category=project_type if project_type != "full_stack" else None)
        
        enhanced_config = base_config.copy()
        enhanced_config["learned_lessons"] = [
            {
                "pattern": l.pattern,
                "confidence": l.confidence,
                "usage_count": l.usage_count
            }
            for l in lessons[:5]
        ]
        enhanced_config["optimized_parameters"] = optimized.get("parameter_preferences", {})
        enhanced_config["success_rate"] = optimized.get("success_rate", 0.0)
        
        return enhanced_config
    
    def get_learning_summary(self) -> Dict[str, Any]:
        """Get summary of learning progress."""
        categories = {}
        for lesson in self.lessons.values():
            if lesson.category not in categories:
                categories[lesson.category] = {"count": 0, "avg_confidence": 0.0, "total_usage": 0}
            cat = categories[lesson.category]
            cat["count"] += 1
            cat["avg_confidence"] = (cat["avg_confidence"] * (cat["count"] - 1) + lesson.confidence) / cat["count"]
            cat["total_usage"] += lesson.usage_count
        
        return {
            "total_lessons": len(self.lessons),
            "total_projects": len(self.projects),
            "categories": categories,
            "overall_success_rate": sum(
                p.get("success_rate", 0) for p in self.optimized_parameters.values()
            ) / len(self.optimized_parameters) if self.optimized_parameters else 0.0,
            "recent_projects": len([p for p in self.projects 
                                   if (datetime.now() - datetime.fromisoformat(p.timestamp)).days < 7])
        }
    
    def increment_lesson_usage(self, lesson_id: str, success: bool = True):
        """Track lesson usage and update effectiveness."""
        if lesson_id in self.lessons:
            lesson = self.lessons[lesson_id]
            lesson.usage_count += 1
            lesson.effectiveness_score = (
                (lesson.effectiveness_score * (lesson.usage_count - 1) + 
                 (1.0 if success else 0.0)) / lesson.usage_count
            )
            self._save_registry()
    
    def export_learning_report(self) -> str:
        """Export human-readable learning report."""
        summary = self.get_learning_summary()
        
        report = f"""
# NEXUS-CORE v5.0 Learning Report
Generated: {datetime.now().isoformat()}

## Summary
- Total Lessons Learned: {summary['total_lessons']}
- Total Projects Completed: {summary['total_projects']}
- Overall Success Rate: {summary['overall_success_rate']:.1%}
- Recent Activity (7 days): {summary['recent_projects']} projects

## Lessons by Category
"""
        for cat, data in summary['categories'].items():
            report += f"""
### {cat.upper()}
- Lessons: {data['count']}
- Avg Confidence: {data['avg_confidence']:.2f}
- Total Usage: {data['total_usage']}
"""
        
        report += "\n## Top Lessons\n"
        top_lessons = sorted(
            self.lessons.values(),
            key=lambda x: x.effectiveness_score * x.confidence,
            reverse=True
        )[:10]
        
        for i, lesson in enumerate(top_lessons, 1):
            report += f"""
{i}. [{lesson.category}] {lesson.description}
   Pattern: {lesson.pattern}
   Confidence: {lesson.confidence:.2f} | Usage: {lesson.usage_count} | Effectiveness: {lesson.effectiveness_score:.2f}
"""
        
        return report


# Global registry instance
_registry: Optional[LearningRegistry] = None

def get_registry() -> LearningRegistry:
    """Get global learning registry instance."""
    global _registry
    if _registry is None:
        _registry = LearningRegistry()
    return _registry


# Convenience functions for easy integration
def log_project_completion(user_prompt: str, project_type: str, duration: float,
                          success: bool, artifacts: Dict[str, Any], 
                          metrics: Dict[str, float] = None, feedback: str = None) -> str:
    """Log a completed project to the learning registry."""
    registry = get_registry()
    return registry.record_project(user_prompt, project_type, duration, success, artifacts, metrics, feedback)

def get_lessons_for_task(category: str = None) -> List[ProjectLesson]:
    """Get relevant lessons for a task category."""
    registry = get_registry()
    return registry.get_relevant_lessons(category=category)

def apply_optimizations(project_type: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Apply learned optimizations to configuration."""
    registry = get_registry()
    return registry.apply_learned_optimizations(project_type, config)

def generate_learning_report() -> str:
    """Generate human-readable learning report."""
    registry = get_registry()
    return registry.export_learning_report()