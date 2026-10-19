"""
AI Model Management API Routes
===============================
OpenCode-style model selection: list providers, switch models, configure API keys.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
import os
import json
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from provider_health import health

router = APIRouter(prefix="/api/v1/models", tags=["models"])

# Config file path
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "model_config.json")

# Encryption key file
ENCRYPTION_KEY_FILE = os.path.join(os.path.dirname(__file__), ".encryption_key")

def _get_encryption_key() -> bytes:
    """Get or create encryption key for API key storage."""
    if os.path.exists(ENCRYPTION_KEY_FILE):
        with open(ENCRYPTION_KEY_FILE, 'rb') as f:
            return f.read()
    
    # Generate new key from a passphrase (in production, use a proper secret)
    # For development, we use a fixed salt; in production, use a secure secret
    passphrase = os.getenv("NEXUS_ENCRYPTION_PASSPHRASE", "nexus-core-dev-key-change-in-production")
    salt = b"nexus-core-salt-v1"  # Fixed salt for consistent key generation
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))
    
    # Save for future use
    with open(ENCRYPTION_KEY_FILE, 'wb') as f:
        f.write(key)
    
    return key

# Global Fernet instance
_FERNET = Fernet(_get_encryption_key())

def _encrypt_key(api_key: str) -> str:
    """Encrypt an API key for storage."""
    if not api_key:
        return ""
    return _FERNET.encrypt(api_key.encode()).decode()

def _decrypt_key(encrypted_key: str) -> str:
    """Decrypt an API key from storage. Falls back to plaintext keys."""
    if not encrypted_key:
        return ""
    try:
        return _FERNET.decrypt(encrypted_key.encode()).decode()
    except Exception:
        # Plaintext key stored (legacy) — return as-is if it looks valid
        if encrypted_key.startswith(("sk-", "AQ.", "AIza", "gsk_")):
            return encrypted_key
        return ""

# Default model catalog
MODEL_CATALOG = {
    "groq": {
        "name": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "env_key": "GROQ_API_KEY",
        "free": True,
        "models": [
            {"id": "openai/gpt-oss-120b", "name": "GPT-OSS 120B", "description": "Groq-fast large model", "context": "128K", "recommended": True},
            {"id": "openai/gpt-oss-20b", "name": "GPT-OSS 20B", "description": "Groq-fast small model", "context": "128K"},
            {"id": "llama-3.3-70b-versatile", "name": "Llama 3.3 70B", "description": "Meta Llama 3.3", "context": "128K"},
            {"id": "llama-3.1-8b-instant", "name": "Llama 3.1 8B", "description": "Fast & lightweight", "context": "128K"},
            {"id": "mixtral-8x7b-32768", "name": "Mixtral 8x7B", "description": "Mixture of Experts", "context": "32K"},
        ]
    },
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY",
        "free": False,
        "models": [
            {"id": "gpt-4o", "name": "GPT-4o", "description": "Most capable multimodal", "context": "128K", "recommended": True},
            {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "description": "Fast & affordable", "context": "128K"},
            {"id": "gpt-4-turbo", "name": "GPT-4 Turbo", "description": "Fast GPT-4", "context": "128K"},
            {"id": "gpt-4", "name": "GPT-4", "description": "Original GPT-4", "context": "8K"},
            {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo", "description": "Fast & cheap", "context": "16K"},
        ]
    },
    "anthropic": {
        "name": "Anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "env_key": "ANTHROPIC_API_KEY",
        "free": False,
        "models": [
            {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4", "description": "Balanced performance", "context": "200K", "recommended": True},
            {"id": "claude-opus-4-20250514", "name": "Claude Opus 4", "description": "Most capable", "context": "200K"},
            {"id": "claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku", "description": "Fast & smart", "context": "200K"},
        ]
    },
    "gemini": {
        "name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "env_key": "GEMINI_API_KEY",
        "free": True,
        "models": [
            {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "description": "Fast multimodal", "context": "1M", "recommended": True},
            {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "description": "Most capable", "context": "1M"},
            {"id": "gemini-1.5-flash", "name": "Gemini 1.5 Flash", "description": "Fast & free", "context": "1M"},
            {"id": "gemini-1.5-pro", "name": "Gemini 1.5 Pro", "description": "Balanced", "context": "2M"},
        ]
    },
    "together": {
        "name": "Together AI",
        "base_url": "https://api.together.xyz/v1",
        "env_key": "TOGETHER_API_KEY",
        "free": True,
        "models": [
            {"id": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo", "name": "Llama 3.1 70B Turbo", "description": "Fast Llama", "context": "128K", "recommended": True},
            {"id": "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo", "name": "Llama 3.1 405B", "description": "Largest Llama", "context": "128K"},
            {"id": "mistralai/Mixtral-8x22B-Instruct-v0.1", "name": "Mixtral 8x22B", "description": "MoE model", "context": "64K"},
        ]
    },
    "openrouter": {
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "env_key": "OPENROUTER_API_KEY",
        "free": True,
        "models": [
            {"id": "inclusionai/ling-3.0-flash-fin", "name": "Ling 3.0 Flash Fin", "description": "Finance-focused MoE model", "context": "262K", "recommended": True},
            {"id": "xiaomi/mimo-v2.6-flash", "name": "MiMo V2.6 Flash", "description": "Xiaomi 309B MoE model", "context": "262K"},
            {"id": "meta/muse-spark-1.3-contributor", "name": "Muse Spark 1.3", "description": "Meta multimodal reasoning", "context": "256K"},
            {"id": "nvidia/nemotron-3-ultra-550b-a55b:free", "name": "Nemotron 3 Ultra (Free)", "description": "NVIDIA 550B frontier model", "context": "256K"},
            {"id": "nvidia/nemotron-3.5-lightning:free", "name": "Nemotron 3.5 Lightning (Free)", "description": "NVIDIA fast model", "context": "256K"},
            {"id": "inclusionai/ling-3.0-flash", "name": "Ling 3.0 Flash", "description": "Hybrid reasoning MoE", "context": "262K"},
            {"id": "openai/gpt-oss-120b", "name": "GPT-OSS 120B", "description": "OpenAI open source", "context": "128K"},
            {"id": "deepseek/deepseek-chat", "name": "DeepSeek Chat (V3)", "description": "DeepSeek V3 - Latest chat model", "context": "128K", "recommended": True},
            {"id": "deepseek/deepseek-r1", "name": "DeepSeek R1", "description": "DeepSeek R1 - Reasoning model", "context": "128K", "recommended": True},
            {"id": "deepseek/deepseek-coder", "name": "DeepSeek Coder", "description": "Code-specialized model", "context": "128K"},
            {"id": "qwen/qwen-2.5-72b-instruct", "name": "Qwen 2.5 72B", "description": "Alibaba Qwen 2.5 - Large multilingual", "context": "128K", "recommended": True},
            {"id": "qwen/qwen-2.5-32b-instruct", "name": "Qwen 2.5 32B", "description": "Qwen 2.5 medium model", "context": "128K"},
            {"id": "qwen/qwen-2.5-7b-instruct", "name": "Qwen 2.5 7B", "description": "Qwen 2.5 small & fast", "context": "128K"},
            {"id": "qwen/qwen-2.5-coder-32b-instruct", "name": "Qwen 2.5 Coder 32B", "description": "Code-specialized Qwen", "context": "128K", "recommended": True},
            {"id": "moonshotai/kimi-k2", "name": "Kimi K2", "description": "Moonshot AI Kimi K2 - Long context", "context": "200K", "recommended": True},
            {"id": "moonshotai/kimi-k2-0711", "name": "Kimi K2 0711", "description": "Kimi K2 latest version", "context": "200K"},
            {"id": "moonshotai/kimi-vl-7b", "name": "Kimi VL 7B", "description": "Multimodal Kimi vision-language", "context": "128K"},
        ]
    }
}


def _load_config() -> dict:
    """Load model configuration from file."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
            
            # Decrypt stored API keys
            if "api_keys" in config:
                decrypted = {}
                for provider, encrypted_key in config["api_keys"].items():
                    decrypted[provider] = _decrypt_key(encrypted_key)
                config["api_keys"] = decrypted
            
            return config
        except:
            pass
    return {"active_provider": None, "active_model": None, "api_keys": {}}


def _save_config(config: dict):
    """Save model configuration to file."""
    # Encrypt API keys before saving
    config_to_save = config.copy()
    if "api_keys" in config_to_save:
        encrypted = {}
        for provider, api_key in config_to_save["api_keys"].items():
            encrypted[provider] = _encrypt_key(api_key)
        config_to_save["api_keys"] = encrypted
    
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config_to_save, f, indent=2)


def _is_valid_key(key: str) -> bool:
    """Check if API key is valid (not placeholder)."""
    if not key or len(key) < 10:
        return False
    placeholders = ['your-', 'sk-placeholder', 'xxx', 'placeholder']
    return not any(key.lower().startswith(p) for p in placeholders)


# ============================================================
# ENDPOINTS
# ============================================================

@router.get("/catalog")
async def get_model_catalog():
    """Get all available providers and models."""
    config = _load_config()
    api_keys = config.get("api_keys", {})

    catalog = []
    for provider_id, provider_info in MODEL_CATALOG.items():
        # Check if API key is configured
        env_key = provider_info["env_key"]
        configured_key = api_keys.get(provider_id) or os.getenv(env_key, "")
        has_key = _is_valid_key(configured_key)

        models = []
        for model in provider_info["models"]:
            models.append({
                **model,
                "available": has_key
            })

        catalog.append({
            "id": provider_id,
            "name": provider_info["name"],
            "free": provider_info["free"],
            "has_api_key": has_key,
            "models": models
        })

    active_provider = config.get("active_provider")
    active_model = config.get("active_model")

    # Auto-detect if no explicit config
    if not active_provider:
        for p in catalog:
            if p["has_api_key"]:
                active_provider = p["id"]
                recommended = next((m for m in p["models"] if m.get("recommended")), None)
                active_model = recommended["id"] if recommended else p["models"][0]["id"]
                break

    return {
        "success": True,
        "catalog": catalog,
        "active_provider": active_provider,
        "active_model": active_model
    }


@router.post("/activate")
async def activate_model(data: dict):
    """Activate a specific model."""
    provider = data.get("provider")
    model = data.get("model")

    if provider not in MODEL_CATALOG:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    # Find the model
    model_info = None
    for m in MODEL_CATALOG[provider]["models"]:
        if m["id"] == model:
            model_info = m
            break

    if not model_info:
        raise HTTPException(status_code=400, detail=f"Unknown model: {model}")

    # Check API key
    config = _load_config()
    api_keys = config.get("api_keys", {})
    env_key = MODEL_CATALOG[provider]["env_key"]
    key = api_keys.get(provider) or os.getenv(env_key, "")

    if not _is_valid_key(key):
        raise HTTPException(
            status_code=400,
            detail=f"{MODEL_CATALOG[provider]['name']} API key is not configured. Set it first."
        )

    # Save selection
    config["active_provider"] = provider
    config["active_model"] = model
    _save_config(config)

    # Update the running agent
    try:
        from ai_agent import get_agent_v6
        agent = get_agent_v6()
        agent.llm_config.api_key = key
        agent.llm_config.base_url = MODEL_CATALOG[provider]["base_url"]
        agent.llm_config.model = model
        agent.provider = provider
    except Exception as e:
        print(f"Agent update error: {e}")

    return {
        "success": True,
        "provider": provider,
        "model": model,
        "model_name": model_info["name"]
    }


@router.post("/api-key")
async def set_api_key(data: dict):
    """Set API key for a provider."""
    provider = data.get("provider")
    api_key = data.get("api_key", "").strip()

    if provider not in MODEL_CATALOG:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    if api_key and not _is_valid_key(api_key):
        raise HTTPException(status_code=400, detail="Invalid API key format")

    config = _load_config()
    if "api_keys" not in config:
        config["api_keys"] = {}

    if api_key:
        config["api_keys"][provider] = api_key
    else:
        config["api_keys"].pop(provider, None)

    _save_config(config)

    # Anahtar degisti: onceki "gecersiz anahtar" karari artik gecersiz ->
    # devre disini kaldir ki yeni anahtar hemen kullanilabilsin.
    health.reset_provider(provider)

    return {"success": True, "provider": provider, "has_key": bool(api_key),
            "health_reset": True}


@router.get("/active")
async def get_active_model():
    """Get currently active model info."""
    config = _load_config()
    provider = config.get("active_provider")
    model = config.get("active_model")

    if not provider:
        # Auto-detect
        api_keys = config.get("api_keys", {})
        for pid, pinfo in MODEL_CATALOG.items():
            key = api_keys.get(pid) or os.getenv(pinfo["env_key"], "")
            if _is_valid_key(key):
                provider = pid
                recommended = next((m for m in pinfo["models"] if m.get("recommended")), None)
                model = recommended["id"] if recommended else pinfo["models"][0]["id"]
                break

    if not provider:
        return {"success": True, "provider": None, "model": None, "status": "no_api_key"}

    # Get model info
    model_info = None
    for m in MODEL_CATALOG.get(provider, {}).get("models", []):
        if m["id"] == model:
            model_info = m
            break

    return {
        "success": True,
        "provider": provider,
        "provider_name": MODEL_CATALOG.get(provider, {}).get("name", provider),
        "model": model,
        "model_name": model_info["name"] if model_info else model,
        "status": "active"
    }


@router.get("/providers")
async def list_providers():
    """List all providers with their status."""
    config = _load_config()
    api_keys = config.get("api_keys", {})

    providers = []
    for pid, pinfo in MODEL_CATALOG.items():
        env_key = pinfo["env_key"]
        key = api_keys.get(pid) or os.getenv(env_key, "")
        status = health.provider_status(pid)
        providers.append({
            "id": pid,
            "name": pinfo["name"],
            "free": pinfo["free"],
            "has_api_key": _is_valid_key(key),
            "model_count": len(pinfo["models"]),
            # Devre kesici durumu: "ok" | "invalid_key" | "rate_limited" ...
            # (Yalnizca bu surecte yapilan gercek cagrilara dayanir; uydurma yok.)
            "status": status["status"],
            "cooldown_seconds": status.get("cooldown_seconds", 0.0),
            "last_error": status.get("error"),
        })

    return {"success": True, "providers": providers, "health": health.snapshot()}


@router.get("/local/status", summary="Yerel model (Ollama/LM Studio) durumu")
async def local_llm_status():
    """
    OpenAI-uyumlu yerel sunuculari tespit eder (yalnizca loopback adresleri).

    Yerel model varsayilan olarak KAPALIDIR; etkinlestirmek icin
    ``NEXUS_LOCAL_LLM_URL`` ortam degiskenini ayarlayin.
    """
    import local_llm

    info = await local_llm.detect()
    return {
        "success": True,
        **info,
        "enabled": local_llm.is_enabled(),
        "configured_url": local_llm.configured_url() or None,
        "configured_model": local_llm.model_name() or None,
        "note": local_llm.status_note(),
        "recommended_models": local_llm.RECOMMENDED_MODELS,
        "how_to_enable": {
            "env_url": "NEXUS_LOCAL_LLM_URL=http://127.0.0.1:11434/v1",
            "env_model": "NEXUS_LOCAL_LLM_MODEL=qwen2.5:1.5b",
            "runtimes": ["ollama", "lmstudio", "llamacpp"],
        },
        "safety": "Yalnizca localhost; API anahtari gerekmez; varsayilan KAPALI.",
    }
