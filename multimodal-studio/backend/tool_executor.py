"""
Tool Execution Engine for NEXUS-CORE
====================================
Executes tools called by the LLM (files, shell, web search, calculator, RAG).
Extracted from ai_agent.py (Phase 3.2 modularization).
"""
import os
import json
import re
import time
import subprocess
import logging
from typing import Dict, List, Optional, Any

import httpx

from web_tools import SafeCalculator, web_search_duckduckgo, web_search_serpapi, web_search_unified

try:
    from rag_system import rag_add_document, rag_search, rag_list_documents, rag_delete_document, rag_get_stats
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False

logger = logging.getLogger("nexus-agent-v6")

# ============================================================
# TOOL EXECUTION ENGINE
# ============================================================

class ToolExecutor:
    """Executes tools called by the LLM."""
    
    def __init__(self, backend_url: str = "http://localhost:8000", working_dir: str = None):
        self.backend_url = backend_url
        # Project working directory
        self.working_dir = working_dir or os.getcwd()
    
    def _resolve_path(self, relative_path: str) -> str:
        """Resolve a relative path against the working directory, preventing path traversal."""
        # Remove leading slashes and normalize
        clean_path = relative_path.replace('\\', '/').lstrip('/')
        # Prevent path traversal
        clean_path = clean_path.replace('../', '').replace('..\\', '')
        full_path = os.path.abspath(os.path.join(self.working_dir, clean_path))
        # Verify the resolved path is still within working_dir
        if not full_path.startswith(os.path.abspath(self.working_dir)):
            raise ValueError("Path traversal detected")
        return full_path
    
    async def execute(self, tool_name: str, arguments: Dict) -> Dict:
        """Execute a tool and return result."""
        import httpx
        
        try:
            # ===== FILE SYSTEM TOOLS =====
            if tool_name == "read_file":
                try:
                    full_path = self._resolve_path(arguments["path"])
                    if not os.path.exists(full_path):
                        return {"success": False, "error": f"File not found: {arguments['path']}"}
                    
                    with open(full_path, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                    
                    start = arguments.get("start_line", 1)
                    end = arguments.get("end_line", len(lines))
                    
                    # Apply line range
                    start_idx = max(0, start - 1)
                    end_idx = min(len(lines), end)
                    selected_lines = lines[start_idx:end_idx]
                    
                    # Add line numbers
                    numbered_lines = []
                    for i, line in enumerate(selected_lines, start=start_idx + 1):
                        numbered_lines.append(f"{i:4d} | {line.rstrip()}")
                    
                    content = '\n'.join(numbered_lines)
                    
                    return {
                        "success": True,
                        "path": arguments["path"],
                        "content": content,
                        "total_lines": len(lines),
                        "showing": f"{start}-{end}",
                        "file_size": os.path.getsize(full_path)
                    }
                except Exception as e:
                    return {"success": False, "error": str(e)}
            
            elif tool_name == "write_file":
                try:
                    full_path = self._resolve_path(arguments["path"])
                    os.makedirs(os.path.dirname(full_path), exist_ok=True)
                    
                    content = arguments["content"]
                    mode = 'a' if arguments.get("append", False) else 'w'
                    
                    with open(full_path, mode, encoding='utf-8') as f:
                        f.write(content)
                    
                    return {
                        "success": True,
                        "path": arguments["path"],
                        "bytes_written": len(content.encode('utf-8')),
                        "mode": "append" if mode == 'a' else "overwrite"
                    }
                except Exception as e:
                    return {"success": False, "error": str(e)}
            
            elif tool_name == "edit_file":
                try:
                    full_path = self._resolve_path(arguments["path"])
                    if not os.path.exists(full_path):
                        return {"success": False, "error": f"File not found: {arguments['path']}"}
                    
                    with open(full_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    old_text = arguments["old_text"]
                    new_text = arguments["new_text"]
                    
                    if old_text not in content:
                        return {"success": False, "error": "old_text not found in file"}
                    
                    count = content.count(old_text)
                    content = content.replace(old_text, new_text)
                    
                    with open(full_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    
                    return {
                        "success": True,
                        "path": arguments["path"],
                        "replacements": count
                    }
                except Exception as e:
                    return {"success": False, "error": str(e)}
            
            elif tool_name == "list_files":
                try:
                    rel_path = arguments.get("path", ".")
                    full_path = self._resolve_path(rel_path)
                    
                    if not os.path.exists(full_path):
                        return {"success": False, "error": f"Directory not found: {rel_path}"}
                    
                    recursive = arguments.get("recursive", False)
                    files = []
                    dirs = []
                    
                    if recursive:
                        for root, dirnames, filenames in os.walk(full_path):
                            # Skip hidden dirs and common build dirs
                            dirnames[:] = [d for d in dirnames if not d.startswith('.') and d not in ['node_modules', '__pycache__', 'venv', '.git']]
                            for d in dirnames:
                                dirs.append(os.path.relpath(os.path.join(root, d), full_path))
                            for f in filenames:
                                if not f.startswith('.'):
                                    fpath = os.path.join(root, f)
                                    files.append({
                                        "name": os.path.relpath(fpath, full_path),
                                        "size": os.path.getsize(fpath),
                                        "type": os.path.splitext(f)[1] or "file"
                                    })
                    else:
                        for item in os.listdir(full_path):
                            if item.startswith('.'):
                                continue
                            item_path = os.path.join(full_path, item)
                            if os.path.isdir(item_path):
                                dirs.append(item)
                            else:
                                files.append({
                                    "name": item,
                                    "size": os.path.getsize(item_path),
                                    "type": os.path.splitext(item)[1] or "file"
                                })
                    
                    return {
                        "success": True,
                        "path": rel_path,
                        "directories": dirs[:50],
                        "files": files[:100],
                        "total_files": len(files),
                        "total_dirs": len(dirs)
                    }
                except Exception as e:
                    return {"success": False, "error": str(e)}
            
            elif tool_name == "search_files":
                try:
                    query = arguments["query"]
                    file_type = arguments.get("file_type", "")
                    search_path = arguments.get("path", ".")
                    full_path = self._resolve_path(search_path)
                    
                    results = []
                    files_scanned = 0
                    
                    for root, dirnames, filenames in os.walk(full_path):
                        # Skip hidden dirs and common build dirs
                        dirnames[:] = [d for d in dirnames if not d.startswith('.') and d not in ['node_modules', '__pycache__', 'venv', '.git']]
                        
                        for filename in filenames:
                            if filename.startswith('.'):
                                continue
                            if file_type and not filename.endswith(file_type):
                                continue
                            
                            filepath = os.path.join(root, filename)
                            rel_path = os.path.relpath(filepath, full_path)
                            
                            # Skip large files
                            if os.path.getsize(filepath) > 1024 * 1024:  # 1MB
                                continue
                            
                            try:
                                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                                    for line_num, line in enumerate(f, 1):
                                        if query.lower() in line.lower():
                                            results.append({
                                                "file": rel_path,
                                                "line": line_num,
                                                "content": line.strip()[:200]
                                            })
                                            if len(results) >= 50:  # Limit results
                                                return {
                                                    "success": True,
                                                    "query": query,
                                                    "results": results,
                                                    "files_scanned": files_scanned,
                                                    "truncated": True
                                                }
                                        files_scanned = 1  # At least scanned one file
                            except:
                                continue
                    
                    return {
                        "success": True,
                        "query": query,
                        "results": results,
                        "matches": len(results),
                        "truncated": False
                    }
                except Exception as e:
                    return {"success": False, "error": str(e)}
            
            elif tool_name == "execute_command":
                try:
                    import subprocess
                    
                    command = arguments["command"]
                    timeout = arguments.get("timeout", 30)
                    
                    # Execute with subprocess
                    process = subprocess.Popen(
                        command,
                        shell=True,
                        cwd=self.working_dir,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        encoding='utf-8',
                        errors='replace'
                    )
                    
                    try:
                        stdout, stderr = process.communicate(timeout=timeout)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        stdout, stderr = process.communicate()
                        return {
                            "success": False,
                            "error": f"Command timed out after {timeout}s",
                            "stdout": stdout[:2000],
                            "stderr": stderr[:1000]
                        }
                    
                    return {
                        "success": process.returncode == 0,
                        "exit_code": process.returncode,
                        "stdout": stdout[:5000],
                        "stderr": stderr[:2000],
                        "command": command
                    }
                except Exception as e:
                    return {"success": False, "error": str(e)}
            
            # ===== EXISTING TOOLS =====
            elif tool_name == "generate_code":
                # Auto-detect script vs API mode
                prompt = arguments.get("prompt", "").lower()
                language = arguments.get("language", "python")
                mode = arguments.get("mode", "auto")
                
                # Auto-detect mode from prompt
                if mode == "auto":
                    if any(kw in prompt for kw in ["script", "simple", "basit", "print", "hello world", "çalıştırılabilir", "standalone"]):
                        mode = "script"
                    else:
                        mode = "api"
                
                # Auto-detect language from prompt
                if any(kw in prompt for kw in ["javascript", "node", "npm", "js"]):
                    language = "javascript"
                elif any(kw in prompt for kw in ["typescript", "ts"]):
                    language = "typescript"
                elif any(kw in prompt for kw in ["bash", "shell", "terminal"]):
                    language = "bash"
                
                framework = "script" if mode == "script" else "fastapi"
                
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"{self.backend_url}/api/v1/generate/code",
                        json={
                            "prompt": arguments["prompt"],
                            "language": language,
                            "framework": framework,
                            "mode": mode
                        }
                    )
                    data = resp.json()
                    return {
                        "success": data.get("success", False),
                        "code": data.get("code", ""),
                        "language": language,
                        "mode": mode
                    }
            
            elif tool_name == "generate_visual_prompt":
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"{self.backend_url}/api/v1/generate/visual",
                        json=arguments
                    )
                    data = resp.json()
                    return {
                        "success": data.get("success", False),
                        "final_prompt": data.get("final_prompt_english", ""),
                        "subject": data.get("subject", "")
                    }
            
            elif tool_name == "generate_image":
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(
                        f"{self.backend_url}/api/v1/generate/image",
                        json=arguments
                    )
                    data = resp.json()
                    return {
                        "success": data.get("success", False),
                        "image_url": data.get("image_url", ""),
                        "prompt": data.get("prompt", ""),
                        "width": data.get("width", 1024),
                        "height": data.get("height", 1024),
                        "model": data.get("model", "flux")
                    }
            
            elif tool_name == "generate_video_prompt":
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"{self.backend_url}/api/v1/generate/video",
                        json=arguments
                    )
                    data = resp.json()
                    return {
                        "success": data.get("success", False),
                        "final_prompt": data.get("final_prompt_english", ""),
                        "timecode": data.get("timecode", "")
                    }
            
            elif tool_name == "generate_real_video":
                # Generate actual video file (takes 30-300 seconds due to rate limits)
                async with httpx.AsyncClient(timeout=300.0) as client:
                    resp = await client.post(
                        f"{self.backend_url}/api/v1/generate/real-video",
                        json=arguments
                    )
                    data = resp.json()
                    if data.get("success"):
                        video_url = f"{self.backend_url}{data['video_url']}"
                        return {
                            "success": True,
                            "video_url": video_url,
                            "video_id": data.get("video_id"),
                            "duration": data.get("duration"),
                            "resolution": data.get("resolution"),
                            "size_kb": data.get("size_kb"),
                            "generation_time": data.get("generation_time")
                        }
                    return {"success": False, "error": data.get("error", "Video generation failed")}
            
            elif tool_name == "search_learning":
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"{self.backend_url}/api/v1/learning/report",
                        json=arguments
                    )
                    data = resp.json()
                    return {
                        "success": True,
                        "report": data.get("rapor", data.get("report", "")),
                        "query": arguments.get("query", "")
                    }
            
            elif tool_name == "web_search":
                query = arguments.get("query", "")
                max_results = arguments.get("max_results", 8)
                results = await web_search_unified(query, max_results)
                return {
                    "success": True,
                    "query": query,
                    "results": results,
                    "count": len(results)
                }
            
            elif tool_name == "calculate":
                expression = arguments.get("expression", "")
                result = CALCULATOR.evaluate(expression)
                return result
            
            # ===== RAG TOOLS =====
            elif tool_name == "rag_add_document":
                from rag_system import rag_add_document
                return await rag_add_document(
                    content=arguments.get("content", ""),
                    title=arguments.get("title", ""),
                    category=arguments.get("category", "general"),
                    source=arguments.get("source", "user"),
                    tags=arguments.get("tags", [])
                )
            
            elif tool_name == "rag_search":
                from rag_system import rag_search
                return await rag_search(
                    query=arguments.get("query", ""),
                    n_results=arguments.get("n_results", 5),
                    category=arguments.get("category")
                )
            
            elif tool_name == "rag_list_documents":
                from rag_system import rag_list_documents
                return await rag_list_documents()
            
            elif tool_name == "rag_delete_document":
                from rag_system import rag_delete_document
                return await rag_delete_document(
                    doc_id=arguments.get("doc_id", "")
                )
            
            elif tool_name == "rag_get_stats":
                from rag_system import rag_get_stats
                return await rag_get_stats()
            
            else:
                return {"success": False, "error": f"Unknown tool: {tool_name}"}
        
        except Exception as e:
            return {"success": False, "error": str(e)}


