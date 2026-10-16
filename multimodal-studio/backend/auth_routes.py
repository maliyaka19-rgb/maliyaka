"""
Auth API Routes - NEXUS-CORE v6.1
==================================
Authentication and chat persistence endpoints with OAuth support.
"""

from fastapi import APIRouter, HTTPException, Depends, status, Request
from fastapi.security import HTTPBearer
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr
from typing import Optional, List
import json
import os
import secrets
import logging
from datetime import datetime, timedelta

from auth import (
    auth_service, get_current_user, get_optional_user,
    UserRegister, UserLogin, TokenResponse, ChatCreate, ChatUpdate,
    create_access_token, hash_password,
    verify_google_token, verify_apple_token,
    GOOGLE_CLIENT_ID, APPLE_CLIENT_ID, OAUTH_REDIRECT_URI,
    generate_apple_client_secret, save_users
)

# Import AI agent to access conversation memory
from ai_agent import get_agent_v6

logger = logging.getLogger("nexus-auth-routes")

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)

# OAuth state storage (in production use Redis)
oauth_states = {}


# ============================================================
# AUTH ENDPOINTS
# ============================================================

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

@router.post("/register", response_model=TokenResponse, summary="Register new user")
async def register(data: UserRegister):
    username = data.username or (data.email.split("@")[0] if "@" in data.email else data.email[:20])
    user = auth_service.register(data.email, username, data.password)
    token = create_access_token({"sub": user.id, "email": user.email})
    return {
        "access_token": token,
        "user": {"id": user.id, "email": user.email, "username": user.username}
    }


@router.post("/forgot-password", summary="Request password reset")
async def forgot_password(data: ForgotPasswordRequest):
    """Request password reset for a registered user."""
    user = auth_service.get_user_by_email(data.email)
    if not user:
        # Don't reveal whether email exists
        return {"success": True, "message": "E-posta adresi sistemde kayıtlıysa şifre sıfırlama linki gönderildi."}
    # Generate reset token
    reset_token = secrets.token_urlsafe(32)
    user.metadata = user.metadata or {}
    user.metadata["reset_token"] = reset_token
    user.metadata["reset_token_expires"] = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    save_users(auth_service.users)
    logger.info(f"Password reset requested for: {data.email}")
    return {"success": True, "message": "Şifre sıfırlama isteiği alındı.", "reset_token": reset_token if os.getenv("DEBUG") else None}


@router.post("/reset-password", summary="Reset password with token")
async def reset_password(data: ResetPasswordRequest):
    """Reset password using a reset token."""
    for user in auth_service.users.values():
        meta = user.metadata or {}
        if meta.get("reset_token") == data.token:
            expires = meta.get("reset_token_expires")
            if expires and datetime.utcnow() < datetime.fromisoformat(expires):
                user.password_hash = hash_password(data.new_password)
                user.metadata.pop("reset_token", None)
                user.metadata.pop("reset_token_expires", None)
                save_users(auth_service.users)
                return {"success": True, "message": "Şifreniz yenilendi."}
            else:
                raise HTTPException(status_code=400, detail="Reset token süresi dolmuş")
    raise HTTPException(status_code=400, detail="Geçersiz reset token")


@router.post("/login", response_model=TokenResponse, summary="Login user")
async def login(data: UserLogin):
    user = auth_service.login(data.email, data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": user.id, "email": user.email})
    return {
        "access_token": token,
        "user": {"id": user.id, "email": user.email, "username": user.username}
    }


@router.post("/guest", response_model=TokenResponse, summary="Guest login")
async def guest_login():
    import secrets
    guest_id = f"guest_{secrets.token_hex(4)}"
    user = auth_service.get_or_create_guest_user(guest_id)
    token = create_access_token({"sub": user.id, "email": user.email})
    return {
        "access_token": token,
        "user": {"id": user.id, "email": user.email, "username": user.username}
    }


@router.get("/me", summary="Get current user info")
async def get_me(current_user = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "username": current_user.username,
        "created_at": current_user.created_at,
        "last_login": current_user.last_login
    }


@router.post("/logout", summary="Logout (client-side token removal)")
async def logout():
    return {"success": True, "message": "Logged out"}


# ============================================================
# OAUTH ENDPOINTS
# ============================================================

class OAuthTokenRequest(BaseModel):
    provider: str  # "google" or "apple"
    id_token: str

@router.post("/oauth/token", response_model=TokenResponse, summary="Exchange OAuth ID token for JWT")
async def oauth_token(data: OAuthTokenRequest):
    """Exchange Google/Apple ID token for our JWT."""
    if data.provider == "google":
        user_info = await verify_google_token(data.id_token)
    elif data.provider == "apple":
        user_info = await verify_apple_token(data.id_token)
    else:
        raise HTTPException(status_code=400, detail="Invalid provider")
    
    if not user_info:
        raise HTTPException(status_code=401, detail="Invalid OAuth token")
    
    # Get or create user
    user = auth_service.get_or_create_oauth_user(
        email=user_info["email"],
        provider=user_info["provider"],
        provider_id=user_info["provider_id"],
        name=user_info.get("name")
    )
    
    token = create_access_token({"sub": user.id, "email": user.email})
    return {
        "access_token": token,
        "user": {"id": user.id, "email": user.email, "username": user.username}
    }

def _is_configured_oauth(client_id: str) -> bool:
    return bool(client_id and not client_id.startswith("your-") and client_id != "placeholder")

@router.get("/oauth/google/url", summary="Get Google OAuth URL")
async def google_oauth_url(request: Request):
    """Get Google OAuth authorization URL."""
    if not _is_configured_oauth(GOOGLE_CLIENT_ID):
        user = auth_service.get_or_create_oauth_user(
            email="google.user@example.com",
            provider="google",
            provider_id="mock_google_123",
            name="Google Kullanıcısı"
        )
        token = create_access_token({"sub": user.id, "email": user.email})
        return {"url": f"http://localhost:8080/chat.html?token={token}&provider=google", "mock": True}
    
    import secrets
    state = secrets.token_urlsafe(32)
    oauth_states[state] = "google"
    
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "consent"
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + "&".join(f"{k}={v}" for k, v in params.items())
    return {"url": url, "state": state}

@router.get("/oauth/apple/url", summary="Get Apple OAuth URL")
async def apple_oauth_url(request: Request):
    """Get Apple OAuth authorization URL."""
    if not _is_configured_oauth(APPLE_CLIENT_ID):
        user = auth_service.get_or_create_oauth_user(
            email="apple.user@example.com",
            provider="apple",
            provider_id="mock_apple_123",
            name="Apple Kullanıcısı"
        )
        token = create_access_token({"sub": user.id, "email": user.email})
        return {"url": f"http://localhost:8080/chat.html?token={token}&provider=apple", "mock": True}
    
    import secrets
    state = secrets.token_urlsafe(32)
    oauth_states[state] = "apple"
    
    params = {
        "client_id": APPLE_CLIENT_ID,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": "name email",
        "state": state,
        "response_mode": "form_post"
    }
    url = "https://appleid.apple.com/auth/authorize?" + "&".join(f"{k}={v}" for k, v in params.items())
    return {"url": url, "state": state}

@router.get("/oauth/callback", summary="OAuth callback handler")
async def oauth_callback(request: Request):
    """Handle OAuth callback from Google/Apple."""
    params = dict(request.query_params)
    code = params.get("code")
    state = params.get("state")
    error = params.get("error")
    
    if error:
        return RedirectResponse(url=f"/chat.html?error={error}")
    
    if not code or not state or state not in oauth_states:
        return RedirectResponse(url="/chat.html?error=invalid_state")
    
    provider = oauth_states.pop(state)
    
    # Exchange code for tokens
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            if provider == "google":
                token_resp = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "code": code,
                        "client_id": GOOGLE_CLIENT_ID,
                        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
                        "redirect_uri": OAUTH_REDIRECT_URI,
                        "grant_type": "authorization_code"
                    }
                )
                tokens = token_resp.json()
                id_token = tokens.get("id_token")
                if id_token:
                    user_info = await verify_google_token(id_token)
            else:  # apple
                client_secret = generate_apple_client_secret()
                token_resp = await client.post(
                    "https://appleid.apple.com/auth/token",
                    data={
                        "code": code,
                        "client_id": APPLE_CLIENT_ID,
                        "client_secret": client_secret,
                        "redirect_uri": OAUTH_REDIRECT_URI,
                        "grant_type": "authorization_code"
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                )
                tokens = token_resp.json()
                id_token = tokens.get("id_token")
                if id_token:
                    user_info = await verify_apple_token(id_token)
            
            if user_info:
                user = auth_service.get_or_create_oauth_user(
                    email=user_info["email"],
                    provider=user_info["provider"],
                    provider_id=user_info["provider_id"],
                    name=user_info.get("name")
                )
                jwt_token = create_access_token({"sub": user.id, "email": user.email})
                # Redirect to frontend with token
                return RedirectResponse(url=f"/chat.html?token={jwt_token}&provider={provider}")
    except Exception as e:
        logger.error(f"OAuth callback error: {e}")
    
    return RedirectResponse(url="/chat.html?error=oauth_failed")

@router.post("/oauth/link", summary="Link OAuth provider to existing account")
async def link_oauth(data: OAuthTokenRequest, current_user = Depends(get_current_user)):
    """Link Google/Apple account to existing user."""
    if data.provider == "google":
        user_info = await verify_google_token(data.id_token)
    elif data.provider == "apple":
        user_info = await verify_apple_token(data.id_token)
    else:
        raise HTTPException(status_code=400, detail="Invalid provider")
    
    if not user_info:
        raise HTTPException(status_code=401, detail="Invalid OAuth token")
    
    # Update user metadata
    current_user.metadata = current_user.metadata or {}
    current_user.metadata[f"{data.provider}_id"] = user_info["provider_id"]
    from auth import save_users
    save_users(auth_service.users)
    
    return {"success": True, "message": f"{data.provider.capitalize()} account linked"}

# ============================================================
# CHAT PERSISTENCE ENDPOINTS
# ============================================================

@router.post("/chats", summary="Create new chat")
async def create_chat(data: ChatCreate, current_user = Depends(get_current_user)):
    chat = auth_service.create_chat(current_user.id, data.title or "Yeni Sohbet")
    return {"id": chat.id, "title": chat.title, "created_at": chat.created_at}


@router.get("/chats", summary="List user's chats")
async def list_chats(current_user = Depends(get_current_user)):
    chats = auth_service.get_user_chats(current_user.id)
    return {
        "chats": [
            {
                "id": c.id,
                "title": c.title,
                "created_at": c.created_at,
                "updated_at": c.updated_at,
                "message_count": c.message_count
            }
            for c in chats
        ]
    }


@router.get("/chats/{chat_id}", summary="Get chat details")
async def get_chat(chat_id: str, current_user = Depends(get_current_user)):
    chat = auth_service.get_chat(chat_id, current_user.id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    # Get messages from AI agent memory
    messages = []
    try:
        agent = get_agent_v6()
        if chat_id in agent.memory.conversations:
            conv = agent.memory.conversations[chat_id]
            messages = [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.timestamp
                }
                for msg in conv.messages
                if msg.content  # Only include messages with content
            ]
    except Exception as e:
        print(f"Error loading messages from agent memory: {e}")
    
    return {
        "id": chat.id,
        "title": chat.title,
        "created_at": chat.created_at,
        "updated_at": chat.updated_at,
        "message_count": chat.message_count,
        "messages": messages
    }


@router.patch("/chats/{chat_id}", summary="Update chat title")
async def update_chat(chat_id: str, data: ChatUpdate, current_user = Depends(get_current_user)):
    chat = auth_service.update_chat(chat_id, current_user.id, data.title)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"id": chat.id, "title": chat.title, "updated_at": chat.updated_at}


@router.delete("/chats/{chat_id}", summary="Delete chat")
async def delete_chat(chat_id: str, current_user = Depends(get_current_user)):
    success = auth_service.delete_chat(chat_id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"success": True, "message": "Chat deleted"}


# ============================================================
# INTEGRATION HELPER
# ============================================================

def register_auth_routes(app):
    app.include_router(router)