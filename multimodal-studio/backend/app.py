# backend/app.py - Main FastAPI Application Entry Point

from fastapi import FastAPI, HTTPException, Depends, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
import os
import logging
import time
from datetime import datetime
from typing import Dict, Any, List, Optional

# Learning Registry Import
from learning_registry import log_project_completion, get_registry

# Agent Import
from agent_core import get_agent
from agent_routes import router as agent_router

# AI Agent Import (True AI with LLM)
from ai_agent_routes import router as ai_agent_router

# Brain Import (Continuous Learning)
from brain_routes import router as brain_router

# Auth Import (User Management & Chat Persistence)
from auth_routes import router as auth_router

# Project Management Import (OpenCode-style file operations)
from project_routes import router as project_router

# Model Management Import (AI model selection)
from model_routes import router as model_router

# Filesystem Browser Import (Project selection)
from fs_routes import router as fs_router

# Custom Agent Builder Import
from custom_agent_routes import router as custom_agent_router

# Telegram Integration Import (control + chat)
from telegram_routes import router as telegram_router

# Video Generation Import (Pollinations.ai)
from video_generator import get_video_generator

# Configure logging (production-ready)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("multimodal-studio")

# Initialize FastAPI app
app = FastAPI(
    title="Çoklu Ortam Yaratıcı Stüdyo API",
    description="NEXUS-CORE v6.0 - True AI Agent + Kurumsal Çok Modlu Yapay Zeka Üretim Platformu",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Include Agent Router
app.include_router(agent_router)

# Include AI Agent Router (True AI)
app.include_router(ai_agent_router)

# Include Brain Router (Continuous Learning)
app.include_router(brain_router)

# Include Auth Router (User Management)
app.include_router(auth_router)

# Include Project Router (File Management)
app.include_router(project_router)

# Include Model Router (AI Model Selection)
app.include_router(model_router)

# Include Filesystem Router (Project Selection)
app.include_router(fs_router)

# Include Custom Agent Router
app.include_router(custom_agent_router)

# Include Telegram Router (bot control + chat)
app.include_router(telegram_router)

# CORS configuration (G2 fix)
# Wildcard "*" cannot be combined with allow_credentials=True and is unsafe for
# production. We use an explicit allowlist. Zero-config local development keeps
# working (frontend on :8080, API/docs on :8000, Next.js dev on :3000);
# production can override/extend via comma-separated CORS_ORIGINS.
_DEV_ORIGINS = [
    "http://localhost:8080", "http://127.0.0.1:8080",
    "http://localhost:8000", "http://127.0.0.1:8000",
    "http://localhost:3000", "http://127.0.0.1:3000",
]
_env_origins = [
    o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",")
    if o.strip() and o.strip() != "*"
]
allowed_origins = sorted(set(_env_origins) | set(_DEV_ORIGINS))
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info("CORS allowed origins: %s", allowed_origins)


# ============================================================
# AGENT INITIALIZATION & TOOL CONNECTION
# ============================================================

@app.on_event("startup")
async def startup_agent():
    """Initialize agent and connect backend tools on startup."""
    agent = get_agent()
    
    # Connect actual backend functions to agent tools
    agent.connect_backend_tools({
        "code_generation": _agent_code_generation,
        "visual_generation": _agent_visual_generation,
        "video_generation": _agent_video_generation,
        "learning_query": _agent_learning_query,
    })
    logger.info("Agent initialized and tools connected")

    # Start Telegram bot if configured and enabled (non-blocking background task)
    try:
        from telegram_bot import token_is_set, load_config as _tg_load, start_bot_from_config
        _tg_cfg = _tg_load()
        if token_is_set() and _tg_cfg.get("enabled", True):
            _tg_status = await start_bot_from_config()
            logger.info("Telegram bot started (running=%s)", _tg_status.get("running"))
        else:
            logger.info("Telegram bot not configured/enabled; skipping start")
    except Exception as e:
        logger.warning(f"Telegram bot not started: {e}")


@app.on_event("shutdown")
async def shutdown_telegram():
    """Stop the Telegram bot polling task on shutdown."""
    try:
        from telegram_bot import stop_bot
        await stop_bot()
    except Exception as e:
        logger.debug(f"Telegram shutdown error: {e}")


async def _agent_code_generation(params: Dict[str, Any]) -> Dict[str, Any]:
    """Agent tool: Generate code via backend."""
    from pydantic import ValidationError
    try:
        # Import request model locally to avoid circular imports
        class CodeRequest(BaseModel):
            prompt: str
            language: str = "python"
            framework: str = "fastapi"
            complexity: str = "medium"
            mode: str = "api"
        
        req = CodeRequest(**params)
        
        # Call the actual generation logic
        generated_code = _generate_code_template(req)
        
        return {
            "success": True,
            "code": generated_code,
            "language": req.language,
            "framework": req.framework,
            "complexity": req.complexity
        }
    except ValidationError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"Code generation failed: {str(e)}"}


async def _agent_visual_generation(params: Dict[str, Any]) -> Dict[str, Any]:
    """Agent tool: Generate visual prompt via backend."""
    try:
        class VisualRequest(BaseModel):
            subject: str
            environment: str
            camera: str
            style: str = "cinematic"
        
        req = VisualRequest(**params)
        final_prompt = _construct_visual_prompt(req)
        
        return {
            "success": True,
            "final_prompt": final_prompt,
            "subject": req.subject,
            "style": req.style
        }
    except Exception as e:
        return {"success": False, "error": f"Visual generation failed: {str(e)}"}


async def _agent_video_generation(params: Dict[str, Any]) -> Dict[str, Any]:
    """Agent tool: Generate video prompt via backend."""
    try:
        class VideoRequest(BaseModel):
            timecode: str
            camera_movement: str
            motion_dynamics: str
            video_model: str = "veo"
        
        req = VideoRequest(**params)
        final_prompt = _construct_video_prompt(req)
        
        return {
            "success": True,
            "final_prompt": final_prompt,
            "timecode": req.timecode,
            "model": req.video_model
        }
    except Exception as e:
        return {"success": False, "error": f"Video generation failed: {str(e)}"}


async def _agent_learning_query(params: Dict[str, Any]) -> Dict[str, Any]:
    """Agent tool: Query learning registry."""
    from learning_registry import get_lessons_for_task, get_registry
    
    try:
        query = params.get("query", "")
        category = None
        
        # Determine category from query
        if any(kw in query.lower() for kw in ["kod", "code", "api", "python"]):
            category = "code"
        elif any(kw in query.lower() for kw in ["görsel", "visual", "prompt", "midjourney"]):
            category = "visual"
        elif any(kw in query.lower() for kw in ["video", "film", "scene", "veo"]):
            category = "video"
        
        lessons = get_lessons_for_task(category=category)
        
        return {
            "success": True,
            "query": query,
            "category": category,
            "lessons_found": len(lessons),
            "lessons": [
                {
                    "description": l.description,
                    "pattern": l.pattern,
                    "confidence": l.confidence
                }
                for l in lessons
            ]
        }
    except Exception as e:
        return {"success": False, "error": f"Learning query failed: {str(e)}"}


# ============================================================
# PYDANTIC MODELS (Data Validation - Production Grade)
# ============================================================

class CodeGenerationRequest(BaseModel):
    """Kod üretimi için istek modeli."""
    prompt: str = Field(..., description="İstenen kodun doğal dil açıklaması")
    language: str = Field(default="python", description="Hedef programlama dili")
    framework: str = Field(default="fastapi", description="Hedef framework/kütüphane (script = basit dosya)")
    complexity: str = Field(default="medium", description="Karmaşıklık seviyesi: low|medium|high")
    mode: str = Field(default="api", description="Üretim modu: api|script")
    
    @validator("language")
    def validate_language(cls, v):
        allowed = ["python", "javascript", "typescript", "go", "rust", "bash", "sql"]
        if v.lower() not in allowed:
            raise ValueError(f"Dil şunlardan biri olmalı: {allowed}")
        return v.lower()
    
    @validator("framework")
    def validate_framework(cls, v):
        allowed = ["fastapi", "flask", "express", "nextjs", "django", "script", "cli", "standalone"]
        if v.lower() not in allowed:
            raise ValueError(f"Framework şunlardan biri olmalı: {allowed}")
        return v.lower()
    
    @validator("mode")
    def validate_mode(cls, v):
        allowed = ["api", "script"]
        if v.lower() not in allowed:
            raise ValueError(f"Mod şunlardan biri olmalı: {allowed}")
        return v.lower()


class VisualGenerationRequest(BaseModel):
    """Görsel üretimi için istek modeli."""
    subject: str = Field(..., description="Detaylı anatomik/çevresel tanım (özne)")
    environment: str = Field(..., description="Işık ve çevre terimleri")
    camera: str = Field(..., description="Optik ve lens parametreleri")
    style: str = Field(default="cinematic", description="Görsel stil")
    
    @validator("style")
    def validate_style(cls, v):
        allowed = ["cinematic", "realistic", "conceptual", "minimalist"]
        if v.lower() not in allowed:
            raise ValueError(f"Stil şunlardan biri olmalı: {allowed}")
        return v.lower()


class ImageGenerationRequest(BaseModel):
    """Gerçek görsel (resim) üretimi için istek modeli - Pollinations.ai ile."""
    prompt: str = Field(..., description="Görsel açıklaması (İngilizce önerilir)")
    width: int = Field(default=1024, description="Genişlik", ge=256, le=2048)
    height: int = Field(default=1024, description="Yükseklik", ge=256, le=2048)
    model: str = Field(default="flux", description="Model: flux, gptimage, dall-e, midjourney, turbo")
    seed: Optional[int] = Field(default=None, description="Seed (isteğe bağlı)")
    enhance: bool = Field(default=True, description="Prompt enhance et")


class VideoGenerationRequest(BaseModel):
    """Video üretimi için istek modeli."""
    timecode: str = Field(..., description="Zaman kodu aralığı [başlangıç - bitiş]")
    camera_movement: str = Field(..., description="Teknik kamera hareketi terimleri")
    motion_dynamics: str = Field(..., description="Karakter/nesne hareket parametreleri")
    video_model: str = Field(default="veo", description="Hedef yapay zeka video modeli")


# ============================================================
# HEALTH CHECK ENDPOINT
# ============================================================

@app.get("/health", tags=["sistem"], summary="Sistem Sağlık Kontrolü")
async def health_check():
    """Sistem sağlık kontrolü."""
    return {
        "durum": "çalışıyor",
        "zaman_damgası": datetime.utcnow().isoformat(),
        "servis": "coklu-ortam-studyo-api",
        "versiyon": "1.0.0"
    }


# ============================================================
# CODE GENERATION ENDPOINT
# ============================================================

@app.post("/api/v1/generate/code", tags=["üretim"], summary="Kod Üret")
async def generate_code(request: CodeGenerationRequest):
    """
    Doğal dil açıklamasından üretime hazır kod üret.
    
    Örnek:
    POST /api/v1/generate/code
    {
        "prompt": "Kullanıcı profil bilgilerini döndüren bir FastAPI endpoint oluştur",
        "language": "python",
        "framework": "fastapi",
        "complexity": "medium"
    }
    """
    start_time = time.time()
    try:
        logger.info(f"Code generation request: {request.language}/{request.framework}")
        
        # Generate code based on language/framework
        generated_code = _generate_code_template(request)
        
        duration = time.time() - start_time
        
        # Log to learning registry
        log_project_completion(
            user_prompt=request.prompt,
            project_type="code",
            duration=duration,
            success=True,
            artifacts={"code": generated_code, "language": request.language, "framework": request.framework},
            metrics={"lines_of_code": len(generated_code.split('\n')), "duration": duration}
        )
        
        return {
            "success": True,
            "language": request.language,
            "framework": request.framework,
            "complexity": request.complexity,
            "code": generated_code,
            "generated_at": datetime.utcnow().isoformat(),
            "metadata": {
                "prompt": request.prompt,
                "lines_of_code": len(generated_code.split('\n')),
                "learning_enabled": True
            }
        }
        
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Code generation failed: {str(e)}")
        log_project_completion(
            user_prompt=request.prompt,
            project_type="code",
            duration=duration,
            success=False,
            artifacts={},
            metrics={"duration": duration}
        )
        raise HTTPException(status_code=500, detail=f"Code generation error: {str(e)}")


def _generate_code_template(request: CodeGenerationRequest) -> str:
    """Generate code template based on specifications."""
    
    language = request.language.lower()
    framework = request.framework.lower()
    mode = request.mode.lower()
    
    # Script/Standalone mode - simple executable files
    if mode == "script" or framework in ["script", "cli", "standalone"]:
        return _generate_script_template(language, request.prompt, request.complexity)
    
    # API/Framework mode
    if language == "python" and framework == "fastapi":
        return _python_fastapi_template(request.prompt, request.complexity)
    elif language == "python" and framework == "flask":
        return _python_flask_template(request.prompt, request.complexity)
    elif language == "javascript" and framework == "express":
        return _javascript_express_template(request.prompt, request.complexity)
    elif language == "typescript" and framework == "nextjs":
        return _typescript_nextjs_template(request.prompt, request.complexity)
    elif language == "python" and framework == "django":
        return _python_django_template(request.prompt, request.complexity)
    else:
        return _python_fastapi_template(request.prompt, request.complexity)


def _python_fastapi_template(prompt: str, complexity: str) -> str:
    """Generate Python FastAPI code template."""
    
    complexity_map = {
        "low": "...",  # Simple implementation
        "medium": "### Moderate complexity implementation", 
        "high": "### Advanced implementation with error handling"
    }
    
    template = f'''"""
Generated Code: {prompt}
Complexity: {complexity}
DO NOT SHARE OUTSIDE OF PRODUCTION ENVIRONMENT
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(
    title="Generated API",
    description="Auto-generated from natural language prompt",
    version="1.0.0"
)

# Request/Response Models
{complexity_map.get(complexity, complexity_map["medium"])}
'''
    
    return template


def _generate_script_template(language: str, prompt: str, complexity: str) -> str:
    """Generate simple executable script (not API framework)."""
    
    complexity_map = {
        "low": "# Simple implementation",
        "medium": "# Moderate complexity with functions",
        "high": "# Advanced with error handling, config, logging"
    }
    
    comment_char = "#" if language in ["python", "bash", "sql"] else "//"
    
    if language == "python":
        return f'''{comment_char} Generated Script: {prompt}
{comment_char} Complexity: {complexity}
{comment_char} Run: python script.py

{complexity_map.get(complexity, complexity_map["medium"])}

def main():
    """Ana fonksiyon."""
    print("Merhaba Dünya")
    # TODO: Implement: {prompt}

if __name__ == "__main__":
    main()
'''
    
    elif language == "javascript":
        return f'''{comment_char} Generated Script: {prompt}
{comment_char} Complexity: {complexity}
{comment_char} Run: node script.js

{complexity_map.get(complexity, complexity_map["medium"])}

function main() {{
    console.log("Merhaba Dünya");
    // TODO: Implement: {prompt}
}}

main();
'''
    
    elif language == "typescript":
        return f'''{comment_char} Generated Script: {prompt}
{comment_char} Complexity: {complexity}
{comment_char} Run: npx ts-node script.ts

{complexity_map.get(complexity, complexity_map["medium"])}

function main(): void {{
    console.log("Merhaba Dünya");
    // TODO: Implement: {prompt}
}}

main();
'''
    
    elif language == "bash":
        return f'''{comment_char} Generated Script: {prompt}
{comment_char} Complexity: {complexity}
{comment_char} Run: bash script.sh

{complexity_map.get(complexity, complexity_map["medium"])}

#!/bin/bash
set -euo pipefail

echo "Merhaba Dünya"
# TODO: Implement: {prompt}
'''
    
    elif language == "sql":
        return f'''{comment_char} Generated SQL: {prompt}
{comment_char} Complexity: {complexity}

{complexity_map.get(complexity, complexity_map["medium"])}

-- Merhaba Dünya equivalent
SELECT 'Merhaba Dünya' AS message;
-- TODO: Implement: {prompt}
'''
    
    else:
        return f'''{comment_char} Generated Script: {prompt}
{comment_char} Language: {language}
{comment_char} Complexity: {complexity}

{complexity_map.get(complexity, complexity_map["medium"])}

// TODO: Implement: {prompt}
'''


def _python_flask_template(prompt: str, complexity: str) -> str:
    """Generate Python Flask code template."""
    
    complexity_map = {
        "low": "...",
        "medium": "### Moderate complexity implementation",
        "high": "### Advanced implementation with error handling"
    }
    
    template = f'''"""
Generated Code: {prompt}
Complexity: {complexity}
DO NOT SHARE OUTSIDE OF PRODUCTION ENVIRONMENT
"""

from flask import Flask, jsonify, request

app = Flask(__name__)

# Routes
{complexity_map.get(complexity, complexity_map["medium"])}

@app.route("/")
def hello():
    return jsonify({{"message": "Merhaba Dünya"}})

if __name__ == "__main__":
    app.run(debug=True)
'''
    
    return template


def _javascript_express_template(prompt: str, complexity: str) -> str:
    """Generate JavaScript Express code template."""
    
    complexity_map = {
        "low": "...",
        "medium": "// Moderate complexity implementation",
        "high": "// Advanced implementation with error handling"
    }
    
    template = f'''// Generated Code: {prompt}
// Complexity: {complexity}

const express = require("express");
const app = express();
app.use(express.json());

{complexity_map.get(complexity, complexity_map["medium"])}

app.get("/", (req, res) => {{
    res.json({{ message: "Merhaba Dünya" }});
}});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Server running on port ${{PORT}}`));
'''
    
    return template


def _typescript_nextjs_template(prompt: str, complexity: str) -> str:
    """Generate TypeScript Next.js code template."""
    
    complexity_map = {
        "low": "...",
        "medium": "// Moderate complexity implementation",
        "high": "// Advanced implementation with error handling"
    }
    
    template = f'''// Generated Code: {prompt}
// Complexity: {complexity}

import type {{ NextApiRequest, NextApiResponse }} from "next";

{complexity_map.get(complexity, complexity_map["medium"])}

export default function handler(req: NextApiRequest, res: NextApiResponse) {{
    res.status(200).json({{ message: "Merhaba Dünya" }});
}}
'''
    
    return template


def _python_django_template(prompt: str, complexity: str) -> str:
    """Generate Python Django code template."""
    
    complexity_map = {
        "low": "...",
        "medium": "### Moderate complexity implementation",
        "high": "### Advanced implementation with error handling"
    }
    
    template = f'''"""
Generated Code: {prompt}
Complexity: {complexity}
DO NOT SHARE OUTSIDE OF PRODUCTION ENVIRONMENT
"""

# Django views.py example
from django.http import JsonResponse
from django.views import View

{complexity_map.get(complexity, complexity_map["medium"])}

class HelloView(View):
    def get(self, request):
        return JsonResponse({{"message": "Merhaba Dünya"}})
'''
    
    return template


# ============================================================
# VISUAL GENERATION ENDPOINT  
# ============================================================

@app.post("/api/v1/generate/visual", tags=["üretim"], summary="Görsel Prompt Üret")
async def generate_visual(request: VisualGenerationRequest):
    """
    Parametrik girişlerden profesyonel yapay zeka görsel promptu üret.
    
    Şunlarla uyumlu prompt çıktısı verir:
    - Midjourney v6: --ar 16:9 --style raw --v 6.0
    - Stable Diffusion XL / DALL-E 3
    """
    start_time = time.time()
    try:
        logger.info(f"Visual generation request: {request.style} style")
        
        # Construct parametric prompt
        final_prompt = _construct_visual_prompt(request)
        
        duration = time.time() - start_time
        
        # Log to learning registry
        log_project_completion(
            user_prompt=f"Visual: {request.subject[:100]}",
            project_type="visual",
            duration=duration,
            success=True,
            artifacts={"visual_prompt": final_prompt, "subject": request.subject, "style": request.style},
            metrics={"prompt_length": len(final_prompt), "duration": duration}
        )
        
        return {
            "success": True,
            "prompt_format": "parametric_breakdown",
            "subject": request.subject,
            "environment": request.environment,
            "camera": request.camera,
            "final_prompt_english": final_prompt,
            "generated_at": datetime.utcnow().isoformat(),
            "parameters": {
                "subject_analysis": request.subject[:50] + "..." if len(request.subject) > 50 else request.subject,
                "lighting_analysis": request.environment[:50] + "..." if len(request.environment) > 50 else request.environment,
                "camera_analysis": request.camera[:50] + "..." if len(request.camera) > 50 else request.camera
            },
            "learning_enabled": True
        }
        
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Visual generation failed: {str(e)}")
        log_project_completion(
            user_prompt=f"Visual: {request.subject[:100]}",
            project_type="visual",
            duration=duration,
            success=False,
            artifacts={},
            metrics={"duration": duration}
        )
        raise HTTPException(status_code=500, detail=f"Visual generation error: {str(e)}")


# ============================================================
# IMAGE GENERATION ENDPOINT (Actual Images via Pollinations.ai)
# ============================================================

@app.post("/api/v1/generate/image", tags=["üretim"], summary="Gerçek Görsel Üret (Pollinations.ai)")
async def generate_image(request: ImageGenerationRequest):
    """
    Pollinations.ai ücretsiz API ile gerçek görsel dosyası üret.
    
    Desteklenen modeller:
    - flux (varsayılan, en iyi kalite)
    - gptimage (GPT-Image)
    - dall-e (DALL-E style)
    - midjourney (Midjourney style)
    - turbo (hızlı)
    
    Returns:
    - image_url: Görselin doğrudan URL'si
    - width, height: Boyutlar
    - model: Kullanılan model
    - seed: Kullanılan seed
    """
    start_time = time.time()
    try:
        logger.info(f"Image generation request: {request.prompt[:100]}")
        
        # Build Pollinations URL
        import urllib.parse
        encoded_prompt = urllib.parse.quote(request.prompt)
        
        # Model parameter mapping
        model_param = ""
        if request.model and request.model != "flux":
            model_param = f"&model={request.model}"
        
        # Seed parameter
        seed_param = f"&seed={request.seed}" if request.seed else ""
        
        # Enhance parameter
        enhance_param = "&enhance=true" if request.enhance else ""
        
        # Build URL
        image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={request.width}&height={request.height}{model_param}{seed_param}{enhance_param}&nologo=true"
        
        # Test the URL (bounded retry + backoff for Pollinations 402 FREE_LIMIT)
        import httpx
        import asyncio
        last_status = None
        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(3):
                resp = await client.head(image_url)
                last_status = resp.status_code
                if resp.status_code == 200:
                    break
                if attempt < 2:
                    # 402 = ücretsiz katman hız limiti → bekle ve tekrar dene
                    await asyncio.sleep(2 * (attempt + 1) if resp.status_code == 402 else (attempt + 1))
        if last_status != 200:
            raise HTTPException(
                status_code=500,
                detail=f"Image generation failed - Pollinations returned {last_status}"
            )
        
        duration = time.time() - start_time
        
        # Log to learning registry
        log_project_completion(
            user_prompt=f"Image: {request.prompt[:100]}",
            project_type="image",
            duration=duration,
            success=True,
            artifacts={"prompt": request.prompt, "width": request.width, "height": request.height, "model": request.model},
            metrics={"duration": duration}
        )
        
        return {
            "success": True,
            "image_url": image_url,
            "prompt": request.prompt,
            "width": request.width,
            "height": request.height,
            "model": request.model,
            "seed": request.seed,
            "generated_at": datetime.utcnow().isoformat(),
            "generation_time": round(duration, 2)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Image generation failed: {str(e)}")
        log_project_completion(
            user_prompt=f"Image: {request.prompt[:100]}",
            project_type="image",
            duration=duration,
            success=False,
            artifacts={},
            metrics={"duration": duration}
        )
        raise HTTPException(status_code=500, detail=f"Image generation error: {str(e)}")


# ============================================================
# FILE UPLOAD ENDPOINT
# ============================================================

@app.post("/api/v1/upload/file", tags=["dosya"], summary="Dosya/Belge Yükle")
async def upload_file(file: UploadFile = File(...)):
    """
    Dosya/belge yükle ve içeriğini döndür.
    
    Desteklenen formatlar:
    - Metin: .txt, .md, .py, .js, .ts, .html, .css, .json, .csv, .xml
    - Belgeler: .pdf, .doc, .docx (metin çıkarma sınırlı)
    - Kod: Tüm programlama dilleri
    
    Returns:
    - filename: Dosya adı
    - content: Dosya içeriği (metin)
    - size: Dosya boyutu
    - type: MIME type
    """
    try:
        content = await file.read()
        
        # Try to decode as text
        text_content = ""
        try:
            text_content = content.decode('utf-8')
        except UnicodeDecodeError:
            text_content = f"[Binary dosya - {len(content)} bytes - Metin olarak okunamadı]"
        
        return {
            "success": True,
            "filename": file.filename,
            "content": text_content,
            "size": len(content),
            "type": file.content_type,
            "uploaded_at": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"File upload failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"File upload error: {str(e)}")


# ============================================================
# VIDEO UPLOAD ENDPOINT
# ============================================================

@app.post("/api/v1/upload/video", tags=["dosya"], summary="Video Yükle")
async def upload_video(file: UploadFile = File(...)):
    """
    Video dosyası yükle.
    
    Desteklenen formatlar:
    - Video: .mp4, .webm, .mov, .avi, .mkv
    
    Returns:
    - filename: Video adı
    - size: Dosya boyutu
    - type: MIME type
    - duration: Tahmini süre (varsa)
    """
    try:
        content = await file.read()
        
        return {
            "success": True,
            "filename": file.filename,
            "size": len(content),
            "type": file.content_type,
            "uploaded_at": datetime.utcnow().isoformat(),
            "message": "Video yüklendi. Backend'de video işleme (transkripsiyon, özetleme) eklenebilir."
        }
    except Exception as e:
        logger.error(f"Video upload failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Video upload error: {str(e)}")


# ============================================================
# IMAGE PROXY ENDPOINT (CORS bypass for Pollinations.ai)
# ============================================================

@app.get("/api/v1/image/proxy")
async def proxy_image(url: str):
    """
    Pollinations.ai görselini proxy olarak getir (CORS bypass).
    
    Frontend'in doğrudan pollinations.ai'ye erişememesi durumunda kullanılır.
    """
    import httpx
    from urllib.parse import unquote
    
    # Decode URL first (in case of double encoding from frontend)
    decoded_url = unquote(url)
    
    # Validate URL is from pollinations.ai
    if not decoded_url.startswith("https://image.pollinations.ai/"):
        raise HTTPException(status_code=400, detail="Invalid image URL")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://pollinations.ai/",
            })
            
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail="Failed to fetch image")
            
            # Return image with proper CORS headers
            from fastapi.responses import Response
            return Response(
                content=resp.content,
                media_type=resp.headers.get("content-type", "image/jpeg"),
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET",
                    "Cache-Control": "public, max-age=3600",
                }
            )
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"Proxy error: {str(e)}")


def _construct_visual_prompt(request: VisualGenerationRequest) -> str:
    """
    Construct professional AI art prompt from parametric components.
    
    Format: Subject + Environment + Lighting + Camera + Style parameters
    """
    
    # Build the final prompt following professional standards
    prompt_parts = []
    
    # Subject (Özne) - Detailed anatomik, dokusal ve çevresel tanım
    prompt_parts.append(f"Subject: {request.subject}")
    
    # Environment & Lighting (Çevre & Işık) - Volumetric, GI, professional terms
    prompt_parts.append(f"Environment & Lighting: {request.environment}")
    
    # Camera & Lens (Kamera & Lens) - Optik veriler
    prompt_parts.append(f"Camera & Lens: {request.camera}")
    
    # Final Prompt - Kopyalanacak metin
    final_prompt = ", ".join(prompt_parts) + f", {request.style} style, --ar 16:9 --style raw --v 6.0"
    
    return final_prompt


# ============================================================
# VIDEO GENERATION ENDPOINT
# ============================================================

@app.post("/api/v1/generate/video", tags=["üretim"], summary="Video Promptu Üret")
async def generate_video(request: VideoGenerationRequest):
    """
    Zaman kodu tabanlı sahne tanımından sinematik video promptu üret.
    
    Şunlar için video promptu döndürür:
    - Google Veo
    - OpenAI Sora
    - Runway Gen-3
    - Luma Dream Machine
    """
    start_time = time.time()
    try:
        logger.info(f"Video generation request: {request.timecode}")
        
        # Construct cinematic video prompt
        final_prompt = _construct_video_prompt(request)
        
        duration = time.time() - start_time
        
        # Log to learning registry
        log_project_completion(
            user_prompt=f"Video: {request.timecode} {request.camera_movement[:50]}",
            project_type="video",
            duration=duration,
            success=True,
            artifacts={"video_prompt": final_prompt, "timecode": request.timecode, "model": request.video_model},
            metrics={"prompt_length": len(final_prompt), "duration": duration}
        )
        
        return {
            "success": True,
            "timecode": request.timecode,
            "camera_movement": request.camera_movement,
            "motion_dynamics": request.motion_dynamics,
            "video_model": request.video_model,
            "final_prompt_english": final_prompt,
            "generated_at": datetime.utcnow().isoformat(),
            "prompt_structure": {
                "timecode": request.timecode,
                "camera": request.camera_movement,
                "motion": request.motion_dynamics
            },
            "learning_enabled": True
        }
        
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Video generation failed: {str(e)}")
        log_project_completion(
            user_prompt=f"Video: {request.timecode} {request.camera_movement[:50]}",
            project_type="video",
            duration=duration,
            success=False,
            artifacts={},
            metrics={"duration": duration}
        )
        raise HTTPException(status_code=500, detail=f"Video generation error: {str(e)}")


def _construct_video_prompt(request: VideoGenerationRequest) -> str:
    """
    Construct cinematic video AI prompt following timecode-based scene direction.
    
    Parameters follow professional video direction standards.
    """
    
    # Parse timecode (format: [00:00 - 00:04])
    timecode = request.timecode.strip().replace("[", "").replace("]", "").strip()
    
    # Build cinematic prompt
    prompt = f"""
Cinematic Scene Specification:
Timecode: {timecode}
Camera Movement: {request.camera_movement}
Motion Dynamics: {request.motion_dynamics}

Video AI Prompt: {request.motion_dynamics}, {request.camera_movement}, {timecode}, 
cinematic quality, professional color grading, 16:9 aspect ratio, 
smooth motion, high frame rate, consistent physics
""".strip()
    
    return prompt


# ============================================================
# REAL VIDEO GENERATION ENDPOINT (Pollinations.ai)
# ============================================================

class RealVideoGenerationRequest(BaseModel):
    """Gerçek video üretim isteği."""
    prompt: str = Field(..., description="Video açıklaması")
    duration: int = Field(default=5, ge=1, le=30, description="Video süresi (saniye)")
    width: int = Field(default=1280, description="Genişlik (piksel)")
    height: int = Field(default=720, description="Yükseklik (piksel)")
    fps: int = Field(default=24, description="Frame rate")
    num_frames: int = Field(default=4, ge=2, le=12, description="Sahne frame sayısı")
    style: str = Field(default="cinematic", description="Görsel stil: cinematic|realistic|anime|artistic|minimal")
    model: str = Field(default="standard", description="Video modeli (gelecek için)")


@app.post("/api/v1/generate/real-video", tags=["üretim"], summary="Gerçek Video Üret")
async def generate_real_video(request: RealVideoGenerationRequest):
    """
    Metinden gerçek video dosyası üretir (Pollinations.ai).

    Bu endpoint:
    - Metin açıklamasından gerçek bir video dosyası (.mp4) oluşturur
    - Ücretsiz Pollinations.ai API'sini kullanır
    - Video dosyasını sunucuda kaydeder ve URL döndürür
    """
    start_time = time.time()

    try:
        logger.info(f"Real video generation request: {request.prompt[:50]}...")

        video_gen = get_video_generator()
        result = await video_gen.generate_video(
            prompt=request.prompt,
            duration=request.duration,
            width=request.width,
            height=request.height,
            fps=request.fps,
            num_frames=request.num_frames,
            style=request.style
        )

        if result.get("success"):
            duration_taken = time.time() - start_time

            # Learning registry'ye kaydet
            log_project_completion(
                user_prompt=f"Video: {request.prompt[:50]}",
                project_type="real_video",
                duration=duration_taken,
                success=True,
                artifacts=result,
                metrics={"duration": duration_taken, "video_size": result.get("size_bytes", 0)}
            )

            return {
                "success": True,
                "video_url": result["video_url"],
                "video_id": result["video_id"],
                "prompt": result["prompt"],
                "duration": request.duration,
                "resolution": f"{request.width}x{request.height}",
                "style": request.style,
                "num_frames": request.num_frames,
                "size_kb": round(result.get("size_bytes", 0) / 1024, 2),
                "generation_time": round(duration_taken, 2),
                "generated_at": result["generated_at"]
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Bilinmeyen hata")
            }

    except Exception as e:
        logger.error(f"Real video generation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Video üretim hatası: {str(e)}")


@app.get("/api/v1/videos/{video_id}", tags=["üretim"], summary="Video Dosyasını Getir")
async def get_video_file(video_id: str):
    """Üretilen video dosyasını sunar."""
    import mimetypes

    # Video ID'yi temizle (path traversal koruması)
    video_id = os.path.basename(video_id)

    video_path = os.path.join(os.path.dirname(__file__), "generated_videos", video_id)

    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Video bulunamadı")

    # MIME type belirle
    mime_type, _ = mimetypes.guess_type(video_path)
    if not mime_type:
        mime_type = "video/mp4"

    from fastapi.responses import FileResponse
    return FileResponse(
        video_path,
        media_type=mime_type,
        filename=video_id
    )


# ============================================================
# LEARNING REGISTRY ENDPOINTS
# ============================================================

@app.get("/api/v1/learning/report", tags=["öğrenme"], summary="Öğrenme Raporu Al")
async def get_learning_report():
    """İnsan tarafından okunabilir öğrenme ilerleme raporu al."""
    from learning_registry import generate_learning_report
    return {"rapor": generate_learning_report()}


@app.get("/api/v1/learning/summary", tags=["öğrenme"], summary="Öğrenme Özeti Al")
async def get_learning_summary():
    """Öğrenme özeti istatistiklerini al."""
    registry = get_registry()
    return registry.get_learning_summary()


@app.get("/api/v1/learning/lessons/{category}", tags=["öğrenme"], summary="Kategori Derslerini Al")
async def get_lessons(category: str):
    """Bir kategori için ilgili dersleri al."""
    from learning_registry import get_lessons_for_task
    lessons = get_lessons_for_task(category=category)
    return {
        "kategori": category,
        "dersler": [
            {
                "ders_id": l.lesson_id,
                "aciklama": l.description,
                "desen": l.pattern,
                "guven": l.confidence,
                "kullanim_sayisi": l.usage_count,
                "etkinlik": l.effectiveness_score
            }
            for l in lessons
        ]
    }

# ============================================================
# ROOT ENDPOINT
# ============================================================

@app.get("/", tags=["ana sayfa"], summary="Ana Sayfa")
async def root():
    """API ana sayfası ve bilgileri."""
    return {
        "mesaj": "Çoklu Ortam Yaratıcı Stüdyo API'ye Hoş Geldiniz",
        "versiyon": "1.0.0",
        "aciklama": "NEXUS-CORE v5.0 - Tam yığın çok modlu yapay zeka üretim platformu",
        "endpointler": {
            "belgeler": "/docs",
            "saglik": "/health",
            "kod_uret": "/api/v1/generate/code",
            "gorsel_uret": "/api/v1/generate/visual",
            "video_uret": "/api/v1/generate/video"
        }
    }

# ============================================================
# TÜRKÇE SWAGGER UI DOCS
# ============================================================

from fastapi.responses import HTMLResponse

@app.get("/docs", include_in_schema=False)
async def turkce_docs():
    """Türkçe çevirili özel Swagger UI."""
    return HTMLResponse("""<!DOCTYPE html>
<html>
<head>
  <title>Çoklu Ortam Yaratıcı Stüdyo - API Belgeleri</title>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
</head>
<body style="margin:0">
<div id="swagger-ui"></div>
<script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
window.onload = function() {
  SwaggerUIBundle({
    url: "/openapi.json",
    dom_id: '#swagger-ui',
    presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
    layout: "BaseLayout",
    deepLinking: true,
  });

  const ceviri = {
    "Successful Response": "Başarılı Yanıt",
    "Validation Error": "Doğrulama Hatası",
    "Parameters": "Parametreler",
    "Try it out": "Dene",
    "No parameters": "Parametre yok",
    "Request body": "İstek gövdesi",
    "Example Value": "Örnek Değer",
    "Schema": "Şema",
    "Controls Accept header.": "Kabul başlığını kontrol eder.",
    "No links": "Bağlantı yok",
    "Media type": "Medya türü",
    "Links": "Bağlantılar",
    "Code": "Kod",
    "Description": "Açıklama",
    "Schemas": "Şemalar",
    "Cancel": "İptal",
    "Execute": "Çalıştır",
    "Clear": "Temizle",
    "Response body": "Yanıt gövdesi",
    "Response headers": "Yanıt başlıkları",
    "Responses": "Yanıtlar",
    "Loading...": "Yükleniyor...",
    "Request URL": "İstek URL'si",
    "Server response": "Sunucu yanıtı",
    "Download": "İndir",
    "required": "zorunlu",
    "Expand all": "Tümünü genişlet",
    "Collapse all": "Tümünü daralt",
    "default": "varsayılan",
    "Base URL": "Temel URL",
    "Send empty value": "Boş değer gönder",
  };

  function cevir(node) {
    if (node.nodeType === 3) {
      const temiz = node.textContent.trim();
      if (ceviri[temiz]) {
        node.textContent = node.textContent.replace(temiz, ceviri[temiz]);
      }
    } else if (node.nodeType === 1 && !['SCRIPT','STYLE','INPUT','TEXTAREA'].includes(node.tagName)) {
      node.childNodes.forEach(cevir);
    }
  }

  const gozlemci = new MutationObserver(() => { cevir(document.body); });
  setTimeout(() => {
    cevir(document.body);
    gozlemci.observe(document.body, { childList: true, subtree: true });
  }, 1500);
}
</script>
</body>
</html>""")