"""
Filesystem Browser API Routes
==============================
Browse computer directories, open/save projects like OpenCode.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import os
import json
import string
import shutil
from pathlib import Path

router = APIRouter(prefix="/api/v1/fs", tags=["filesystem"])

# Recent projects file
RECENT_FILE = os.path.join(os.path.dirname(__file__), "recent_projects.json")

# Current working directory (can be changed)
_current_workdir = os.environ.get(
    "NEXUS_WORKING_DIR",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

# Whether a project is currently open (False = default dir, no project)
_project_open = False


def _load_recent() -> list:
    if os.path.exists(RECENT_FILE):
        try:
            with open(RECENT_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return []


def _save_recent(projects: list):
    with open(RECENT_FILE, 'w', encoding='utf-8') as f:
        json.dump(projects, f, indent=2, ensure_ascii=False)


@router.get("/drives")
async def list_drives():
    """List all available drives (Windows) or root directories (Linux/Mac)."""
    drives = []
    
    if os.name == 'nt':
        # Windows: list drive letters
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                try:
                    # Check if accessible
                    os.listdir(drive)
                    drives.append({
                        "name": f"{letter}:",
                        "path": drive,
                        "type": "drive"
                    })
                except PermissionError:
                    pass
    else:
        # Unix: root directory
        drives.append({
            "name": "/",
            "path": "/",
            "type": "drive"
        })
    
    return {"success": True, "drives": drives}


@router.get("/browse")
async def browse_directory(path: str = ""):
    """
    Browse a directory and list its contents.
    Returns folders and files separately.
    """
    if not path:
        # Return drives on Windows, root on Unix
        return await list_drives()
    
    # Validate path exists
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Directory not found: {path}")
    
    if not os.path.isdir(path):
        raise HTTPException(status_code=400, detail=f"Not a directory: {path}")
    
    try:
        folders = []
        files = []
        
        for item in sorted(os.listdir(path)):
            # Skip hidden files and system dirs on Windows
            if item.startswith('.') or item in ['System Volume Information', '$Recycle.Bin', 'Recovery']:
                continue
            
            item_path = os.path.join(path, item)
            try:
                if os.path.isdir(item_path):
                    folders.append({
                        "name": item,
                        "path": item_path,
                        "type": "folder"
                    })
                else:
                    size = os.path.getsize(item_path)
                    ext = os.path.splitext(item)[1].lower()
                    files.append({
                        "name": item,
                        "path": item_path,
                        "type": "file",
                        "size": size,
                        "ext": ext
                    })
            except PermissionError:
                continue
        
        # Get parent directory
        parent = os.path.dirname(path.rstrip('\\/')) or None
        
        return {
            "success": True,
            "current_path": path,
            "parent": parent,
            "folders": folders[:100],  # Limit
            "files": files[:200],  # Limit
            "total_folders": len(folders),
            "total_files": len(files)
        }
    
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/open-project")
async def open_project(data: dict):
    """
    Set a directory as the current project working directory.
    Saves it to recent projects.
    """
    global _current_workdir, _project_open
    
    path = data.get("path", "").strip()
    
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Directory not found: {path}")
    
    if not os.path.isdir(path):
        raise HTTPException(status_code=400, detail=f"Not a directory: {path}")
    
    # Update current working directory
    _current_workdir = os.path.abspath(path)
    _project_open = True
    os.environ["NEXUS_WORKING_DIR"] = _current_workdir
    
    # Update agent's working directory
    try:
        from ai_agent import get_agent_v6
        agent = get_agent_v6()
        agent.tools.working_dir = _current_workdir
    except Exception as e:
        print(f"Agent update error: {e}")
    
    # Update project_routes working directory
    try:
        import project_routes
        project_routes.WORKING_DIR = _current_workdir
    except:
        pass
    
    # Add to recent projects
    recent = _load_recent()
    project_name = os.path.basename(path) or path
    
    # Remove if already exists
    recent = [p for p in recent if p["path"] != _current_workdir]
    
    # Add to beginning
    recent.insert(0, {
        "name": project_name,
        "path": _current_workdir,
        "opened_at": __import__('datetime').datetime.now().isoformat()
    })
    
    # Keep only last 20
    recent = recent[:20]
    _save_recent(recent)
    
    return {
        "success": True,
        "path": _current_workdir,
        "name": project_name
    }


@router.post("/close-project", summary="Close current project")
async def close_project():
    """
    Close the current project and reset to default working directory.
    """
    global _current_workdir, _project_open
    
    # Reset to default (parent of backend dir)
    default_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _project_open = False
    _current_workdir = default_dir
    os.environ["NEXUS_WORKING_DIR"] = default_dir
    
    # Update agent's working directory
    try:
        from ai_agent import get_agent_v6
        agent = get_agent_v6()
        agent.tools.working_dir = default_dir
    except Exception as e:
        print(f"Agent update error: {e}")
    
    # Update project_routes working directory
    try:
        import project_routes
        project_routes.WORKING_DIR = default_dir
    except:
        pass
    
    return {
        "success": True,
        "message": "Proje kapatıldı",
        "working_dir": default_dir
    }


@router.get("/current-project")
async def get_current_project():
    """Get current working directory info."""
    global _current_workdir
    
    # Check if still exists
    if not os.path.exists(_current_workdir):
        _current_workdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    name = os.path.basename(_current_workdir) or _current_workdir
    
    # Count files
    file_count = 0
    folder_count = 0
    try:
        for item in os.listdir(_current_workdir):
            if item.startswith('.'):
                continue
            if os.path.isdir(os.path.join(_current_workdir, item)):
                folder_count += 1
            else:
                file_count += 1
    except:
        pass
    
    return {
        "success": True,
        "path": _current_workdir,
        "name": name,
        "is_open": _project_open,
        "file_count": file_count,
        "folder_count": folder_count
    }


@router.get("/recent-projects")
async def get_recent_projects():
    """Get list of recently opened projects."""
    recent = _load_recent()
    
    # Filter out non-existent paths
    valid_projects = []
    for p in recent:
        if os.path.exists(p["path"]):
            valid_projects.append(p)
    
    # Save cleaned list
    if len(valid_projects) != len(recent):
        _save_recent(valid_projects)
    
    return {"success": True, "projects": valid_projects}


class CreateProjectRequest(BaseModel):
    path: str
    name: str


@router.delete("/recent-projects")
async def clear_recent_projects(path: Optional[str] = None):
    """Clear the recent projects list, or remove a single entry when `path` is given."""
    if path:
        recent = _load_recent()
        target = os.path.normcase(os.path.abspath(path))
        remaining = [p for p in recent if os.path.normcase(os.path.abspath(p.get("path", ""))) != target]
        _save_recent(remaining)
        return {"success": True, "removed": len(recent) - len(remaining)}
    _save_recent([])
    return {"success": True}


@router.post("/create-project", summary="Create a new project folder")
async def create_project(req: CreateProjectRequest):
    """Create a new project folder inside `path` (parent directory) and return its full path."""
    parent = os.path.abspath(req.path)
    name = (req.name or "").strip()

    if not name:
        raise HTTPException(status_code=400, detail="Proje adı boş olamaz")
    if any(sep in name for sep in ("/", "\\", "..")):
        raise HTTPException(status_code=400, detail="Proje adı geçersiz karakter içeriyor")
    if not os.path.isdir(parent):
        raise HTTPException(status_code=404, detail="Üst klasör bulunamadı")

    target = os.path.join(parent, name)
    if os.path.exists(target):
        raise HTTPException(status_code=409, detail="Bu isimde bir dosya/klasör zaten var")

    try:
        os.makedirs(target, exist_ok=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Klasör oluşturulamadı: {e}")

    return {"success": True, "path": target, "name": name}


def _is_protected_dir(path: str) -> bool:
    """Refuse to delete dangerous roots (drive roots, home, the app itself)."""
    p = os.path.abspath(path)
    if os.path.dirname(p) == p:  # drive root, e.g. C:\
        return True
    home = os.path.abspath(os.path.expanduser("~"))
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    studio_root = os.path.dirname(backend_dir)
    protected = {os.path.normcase(home), os.path.normcase(backend_dir), os.path.normcase(studio_root)}
    return os.path.normcase(p) in protected


@router.delete("/project", summary="Delete a project folder")
async def delete_project(path: str):
    """
    Recursively delete a project folder. Refuses drive roots, the user home and
    the application directories. Closes the project first if it is the currently
    open one, and removes it from the recent list.
    """
    global _current_workdir, _project_open

    if not path:
        raise HTTPException(status_code=400, detail="path gerekli")

    target = os.path.abspath(path)
    if not os.path.exists(target):
        raise HTTPException(status_code=404, detail="Proje bulunamadı")
    if not os.path.isdir(target):
        raise HTTPException(status_code=400, detail="Bu bir klasör değil")
    if _is_protected_dir(target):
        raise HTTPException(status_code=403, detail="Bu klasör güvenlik nedeniyle silinemez")

    # If deleting the open project, reset the working dir first
    if os.path.normcase(target) == os.path.normcase(os.path.abspath(_current_workdir)):
        try:
            await close_project()
        except Exception:
            pass

    try:
        shutil.rmtree(target)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Proje silinemedi: {e}")

    # Remove from recent list too
    recent = _load_recent()
    remaining = [p for p in recent if os.path.normcase(os.path.abspath(p.get("path", ""))) != os.path.normcase(target)]
    if len(remaining) != len(recent):
        _save_recent(remaining)

    return {"success": True, "path": target, "message": "Proje silindi"}


@router.get("/home")
async def get_home_directory():
    """Get user's home directory."""
    home = os.path.expanduser("~")
    return {"success": True, "path": home}


@router.get("/desktop")
async def get_desktop_directory():
    """Get user's desktop directory."""
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.exists(desktop):
        desktop = os.path.expanduser("~")
    return {"success": True, "path": desktop}
