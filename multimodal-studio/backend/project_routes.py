"""
Project Management API Routes
==============================
OpenCode-style project file management: browse, read, write, create, delete files.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional, List
import os
import shutil
import json

from auth import get_optional_user

router = APIRouter(prefix="/api/v1/project", tags=["project"])

# Working directory (same as agent's)
WORKING_DIR = os.environ.get(
    "NEXUS_WORKING_DIR",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


# ============================================================
# MODELS
# ============================================================

class FileContent(BaseModel):
    path: str
    content: str


class FileCreate(BaseModel):
    path: str
    content: str = ""
    is_dir: bool = False


class FileRename(BaseModel):
    old_path: str
    new_path: str


class ProjectInfo(BaseModel):
    name: str
    path: str
    type: str  # "file" or "dir"
    size: Optional[int] = None
    children: Optional[List['ProjectInfo']] = None


# ============================================================
# HELPERS
# ============================================================

def _resolve(rel_path: str) -> str:
    """Resolve relative path safely within working directory."""
    clean = rel_path.replace("\\", "/").lstrip("/")
    clean = clean.replace("../", "").replace("..\\", "")
    full = os.path.abspath(os.path.join(WORKING_DIR, clean))
    if not full.startswith(os.path.abspath(WORKING_DIR)):
        raise HTTPException(status_code=403, detail="Path traversal detected")
    return full


def _file_info(rel_path: str, full_path: str) -> dict:
    """Get file/directory info."""
    name = os.path.basename(rel_path) or rel_path
    if os.path.isdir(full_path):
        return {"name": name, "path": rel_path, "type": "dir"}
    else:
        size = os.path.getsize(full_path)
        return {"name": name, "path": rel_path, "type": "file", "size": size}


# ============================================================
# ENDPOINTS
# ============================================================

@router.get("/tree")
async def get_project_tree(path: str = "."):
    """
    Get project file tree.
    Returns nested directory structure.
    """
    full_path = _resolve(path)
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="Directory not found")

    def build_tree(rel, full):
        entries = []
        try:
            for item in sorted(os.listdir(full)):
                if item.startswith('.') or item in ['node_modules', '__pycache__', 'venv', '.git', 'auth_data', 'brain_data', 'learning_registry']:
                    continue
                item_rel = os.path.join(rel, item).replace("\\", "/") if rel != "." else item
                item_full = os.path.join(full, item)
                if os.path.isdir(item_full):
                    entry = _file_info(item_rel, item_full)
                    entry["children"] = build_tree(item_rel, item_full)
                    entries.append(entry)
                else:
                    entries.append(_file_info(item_rel, item_full))
        except PermissionError:
            pass
        return entries

    tree = build_tree(path, full_path)
    return {"success": True, "tree": tree, "root": path}


@router.get("/file")
async def read_file(path: str):
    """Read file content."""
    full_path = _resolve(path)
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not found")
    if os.path.isdir(full_path):
        raise HTTPException(status_code=400, detail="Path is a directory")

    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
        size = os.path.getsize(full_path)
        lines = content.count('\n') + 1
        return {
            "success": True,
            "path": path,
            "content": content,
            "size": size,
            "lines": lines,
            "modified": os.path.getmtime(full_path)
        }
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Binary file")


@router.post("/file")
async def write_file(data: FileContent):
    """Write/create file content."""
    full_path = _resolve(data.path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    with open(full_path, 'w', encoding='utf-8') as f:
        f.write(data.content)

    return {
        "success": True,
        "path": data.path,
        "size": len(data.content.encode('utf-8'))
    }


@router.post("/create")
async def create_file(data: FileCreate):
    """Create new file or directory."""
    full_path = _resolve(data.path)

    if os.path.exists(full_path):
        raise HTTPException(status_code=409, detail="Already exists")

    if data.is_dir:
        os.makedirs(full_path, exist_ok=True)
        return {"success": True, "path": data.path, "type": "dir"}
    else:
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(data.content)
        return {"success": True, "path": data.path, "type": "file"}


@router.delete("/file")
async def delete_file(path: str):
    """Delete file or directory."""
    full_path = _resolve(path)
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="Not found")

    if os.path.isdir(full_path):
        shutil.rmtree(full_path)
        return {"success": True, "path": path, "type": "dir"}
    else:
        os.remove(full_path)
        return {"success": True, "path": path, "type": "file"}


@router.post("/rename")
async def rename_file(data: FileRename):
    """Rename/move file or directory."""
    old_full = _resolve(data.old_path)
    new_full = _resolve(data.new_path)

    if not os.path.exists(old_full):
        raise HTTPException(status_code=404, detail="Source not found")
    if os.path.exists(new_full):
        raise HTTPException(status_code=409, detail="Destination already exists")

    os.makedirs(os.path.dirname(new_full), exist_ok=True)
    shutil.move(old_full, new_full)
    return {"success": True, "old_path": data.old_path, "new_path": data.new_path}


@router.get("/stats")
async def get_project_stats():
    """Get project statistics."""
    total_files = 0
    total_dirs = 0
    total_size = 0
    extensions = {}

    for root, dirs, files in os.walk(WORKING_DIR):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', '__pycache__', 'venv', '.git', 'auth_data', 'brain_data', 'learning_registry']]
        for f in files:
            if f.startswith('.'):
                continue
            filepath = os.path.join(root, f)
            size = os.path.getsize(filepath)
            total_files += 1
            total_size += size

            ext = os.path.splitext(f)[1] or 'no_ext'
            extensions[ext] = extensions.get(ext, 0) + 1

        total_dirs += len(dirs)

    return {
        "success": True,
        "working_dir": WORKING_DIR,
        "total_files": total_files,
        "total_dirs": total_dirs,
        "total_size": total_size,
        "extensions": dict(sorted(extensions.items(), key=lambda x: x[1], reverse=True)[:10])
    }
