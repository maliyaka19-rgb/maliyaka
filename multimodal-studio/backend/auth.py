"""
Authentication Module - NEXUS-CORE v6.1
=======================================
JWT-based auth with user management and chat persistence.
"""

import os
import uuid
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field, asdict
from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
import json
from pathlib import Path
import logging

logger = logging.getLogger("nexus-auth")

# ============================================================
# CONFIG
# ============================================================

SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "nexus-core-v6-dev-secret-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

# OAuth Config
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
APPLE_CLIENT_ID = os.getenv("APPLE_CLIENT_ID", "")  # Services ID
APPLE_TEAM_ID = os.getenv("APPLE_TEAM_ID", "")
APPLE_KEY_ID = os.getenv("APPLE_KEY_ID", "")
APPLE_PRIVATE_KEY = os.getenv("APPLE_PRIVATE_KEY", "")
OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "http://localhost:8000/api/v1/auth/oauth/callback")

DATA_DIR = Path("auth_data")
DATA_DIR.mkdir(exist_ok=True)
USERS_FILE = DATA_DIR / "users.json"
CHATS_FILE = DATA_DIR / "chats.json"

# ============================================================
# MODELS
# ============================================================

@dataclass
class User:
    id: str
    email: str
    username: str
    password_hash: str
    created_at: str
    last_login: Optional[str] = None
    is_active: bool = True
    metadata: Dict = field(default_factory=dict)

@dataclass
class ChatSession:
    id: str
    user_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int = 0
    messages: List[Dict] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)

class UserRegister(BaseModel):
    email: EmailStr
    username: Optional[str] = None
    password: str

class UserLogin(BaseModel):
    email: str  # Accepts both email AND username
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Dict

class ChatCreate(BaseModel):
    title: Optional[str] = "Yeni Sohbet"

class ChatUpdate(BaseModel):
    title: Optional[str] = None

# ============================================================
# PASSWORD UTILS
# ============================================================

def hash_password(password: str) -> str:
    """Hash password with salt."""
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return f"{salt}:{pwd_hash.hex()}"

def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against hash."""
    try:
        salt, hash_val = password_hash.split(":")
        pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
        return pwd_hash.hex() == hash_val
    except Exception:
        return False

# ============================================================
# JWT UTILS
# ============================================================

def create_access_token(data: Dict, expires_delta: Optional[timedelta] = None) -> str:
    import jwt
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> Optional[Dict]:
    if not token:
        return None
    if token.startswith("guest_"):
        return {"sub": token, "email": f"{token}@nexus.local", "username": "Misafir", "is_guest": True}
    import jwt
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

# ============================================================
# STORAGE
# ============================================================

def load_users() -> Dict[str, User]:
    if not USERS_FILE.exists():
        return {}
    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return {k: User(**v) for k, v in data.items()}
    except Exception:
        return {}

def save_users(users: Dict[str, User]):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump({k: asdict(v) for k, v in users.items()}, f, ensure_ascii=False, indent=2)

def load_chats() -> Dict[str, ChatSession]:
    if not CHATS_FILE.exists():
        return {}
    try:
        with open(CHATS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return {k: ChatSession(**v) for k, v in data.items()}
    except Exception:
        return {}

def save_chats(chats: Dict[str, ChatSession]):
    with open(CHATS_FILE, 'w', encoding='utf-8') as f:
        json.dump({k: asdict(v) for k, v in chats.items()}, f, ensure_ascii=False, indent=2)

# ============================================================
# AUTH SERVICE
# ============================================================

class AuthService:
    def __init__(self):
        self.users = load_users()
        self.chats = load_chats()
    
    # ----- User Management -----
    
    def register(self, email: str, username: Optional[str], password: str) -> User:
        if len(password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
        if not username:
            username = email.split("@")[0] if "@" in email else email[:20]
        # Check existing
        for user in self.users.values():
            if user.email == email:
                raise HTTPException(status_code=400, detail="Email already registered")
            if user.username == username:
                raise HTTPException(status_code=400, detail="Username taken")
        
        user_id = str(uuid.uuid4())[:12]
        user = User(
            id=user_id,
            email=email,
            username=username,
            password_hash=hash_password(password),
            created_at=datetime.utcnow().isoformat()
        )
        self.users[user_id] = user
        save_users(self.users)
        logger.info(f"User registered: {username} ({email})")
        return user

    def get_or_create_guest_user(self, guest_id: Optional[str] = None) -> User:
        if not guest_id:
            guest_id = f"guest_{secrets.token_hex(4)}"
        existing = self.users.get(guest_id)
        if existing:
            return existing
        user = User(
            id=guest_id,
            email=f"{guest_id}@nexus.local",
            username="Misafir",
            password_hash="",
            created_at=datetime.utcnow().isoformat(),
            metadata={"is_guest": True}
        )
        self.users[guest_id] = user
        save_users(self.users)
        logger.info(f"Created guest user: {guest_id}")
        return user
    
    def login(self, email: str, password: str) -> Optional[User]:
        # Find user by email OR username
        existing_user = self.get_user_by_email(email)
        if not existing_user:
            existing_user = self.get_user_by_username(email)
        if existing_user:
            if verify_password(password, existing_user.password_hash):
                existing_user.last_login = datetime.utcnow().isoformat()
                save_users(self.users)
                return existing_user
            else:
                return None  # Wrong password

        # User doesn't exist - return None (no auto-creation)
        # User must register explicitly
        return None
    
    def get_user(self, user_id: str) -> Optional[User]:
        return self.users.get(user_id)
    
    def get_user_by_email(self, email: str) -> Optional[User]:
        for user in self.users.values():
            if user.email == email:
                return user
        return None
    
    def get_user_by_username(self, username: str) -> Optional[User]:
        for user in self.users.values():
            if user.username and user.username.lower() == username.lower():
                return user
        return None
    
    # ----- Chat Management -----
    
    def create_chat(self, user_id: str, title: str = "Yeni Sohbet", chat_id: str = None) -> ChatSession:
        if chat_id is None:
            chat_id = str(uuid.uuid4())[:12]
        now = datetime.utcnow().isoformat()
        chat = ChatSession(
            id=chat_id,
            user_id=user_id,
            title=title,
            created_at=now,
            updated_at=now
        )
        self.chats[chat_id] = chat
        save_chats(self.chats)
        return chat
    
    def get_chat(self, chat_id: str, user_id: str) -> Optional[ChatSession]:
        chat = self.chats.get(chat_id)
        if chat and chat.user_id == user_id:
            return chat
        return None
    
    def get_user_chats(self, user_id: str) -> List[ChatSession]:
        user_chats = [c for c in self.chats.values() if c.user_id == user_id]
        user_chats.sort(key=lambda x: x.updated_at, reverse=True)
        return user_chats
    
    def update_chat(self, chat_id: str, user_id: str, title: str) -> Optional[ChatSession]:
        chat = self.get_chat(chat_id, user_id)
        if chat:
            chat.title = title
            chat.updated_at = datetime.utcnow().isoformat()
            save_chats(self.chats)
            return chat
        return None
    
    def delete_chat(self, chat_id: str, user_id: str) -> bool:
        chat = self.get_chat(chat_id, user_id)
        if chat:
            del self.chats[chat_id]
            save_chats(self.chats)
            return True
        return False
    
    def increment_message_count(self, chat_id: str, user_id: str):
        chat = self.get_chat(chat_id, user_id)
        if chat:
            chat.message_count += 1
            chat.updated_at = datetime.utcnow().isoformat()
            save_chats(self.chats)
    
    def update_chat_title(self, chat_id: str, user_id: str, title: str):
        """Update chat title."""
        chat = self.get_chat(chat_id, user_id)
        if chat:
            chat.title = title
            chat.updated_at = datetime.utcnow().isoformat()
            save_chats(self.chats)

    def add_message(self, chat_id: str, user_id: str, role: str, content: str):
        """Add a message to chat session."""
        chat = self.get_chat(chat_id, user_id)
        if chat:
            if not hasattr(chat, 'messages') or chat.messages is None:
                chat.messages = []
            chat.messages.append({
                "role": role,
                "content": content,
                "timestamp": datetime.utcnow().isoformat()
            })
            chat.message_count = len(chat.messages)
            chat.updated_at = datetime.utcnow().isoformat()
            save_chats(self.chats)
            return True
        return False
    
    # ----- OAuth Methods -----
    
    def get_or_create_oauth_user(self, email: str, provider: str, provider_id: str, name: str = None) -> User:
        """Get existing user or create new one from OAuth."""
        # Check if user exists with this email
        existing = self.get_user_by_email(email)
        if existing:
            # Update provider info in metadata
            if not existing.metadata:
                existing.metadata = {}
            existing.metadata[f"{provider}_id"] = provider_id
            existing.last_login = datetime.utcnow().isoformat()
            save_users(self.users)
            return existing
        
        # Create new user
        user_id = str(uuid.uuid4())[:12]
        username = name or email.split("@")[0] if "@" in email else email[:20]
        # Generate deterministic password hash for OAuth users
        import hashlib
        import secrets
        salt = secrets.token_hex(8)
        pwd_hash = hashlib.sha256(f"{provider}:{provider_id}".encode()).hexdigest()
        auto_password_hash = f"{salt}:{pwd_hash}"
        
        user = User(
            id=user_id,
            email=email,
            username=username,
            password_hash=auto_password_hash,
            created_at=datetime.utcnow().isoformat(),
            metadata={f"{provider}_id": provider_id}
        )
        self.users[user_id] = user
        save_users(self.users)
        logger.info(f"Created OAuth user: {email} via {provider}")
        return user

# OAuth helper functions
async def verify_google_token(id_token: str) -> Optional[Dict]:
    """Verify Google ID token and return user info."""
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://oauth2.googleapis.com/tokeninfo",
                params={"id_token": id_token}
            )
            if resp.status_code == 200:
                data = resp.json()
                # Verify audience
                if data.get("aud") == GOOGLE_CLIENT_ID:
                    return {
                        "email": data.get("email"),
                        "name": data.get("name"),
                        "picture": data.get("picture"),
                        "provider_id": data.get("sub"),
                        "provider": "google"
                    }
    except Exception as e:
        logger.error(f"Google token verification failed: {e}")
    return None

def generate_apple_client_secret() -> str:
    """Generate Apple client secret JWT."""
    import jwt
    import time
    now = int(time.time())
    payload = {
        "iss": APPLE_TEAM_ID,
        "iat": now,
        "exp": now + 3600,
        "aud": "https://appleid.apple.com",
        "sub": APPLE_CLIENT_ID,
    }
    return jwt.encode(payload, APPLE_PRIVATE_KEY, algorithm="ES256", headers={"kid": APPLE_KEY_ID})

async def verify_apple_token(id_token: str) -> Optional[Dict]:
    """Verify Apple ID token and return user info."""
    try:
        import httpx
        import jwt
        # Get Apple's public keys
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://appleid.apple.com/auth/keys")
            keys = resp.json()["keys"]
        
        # Decode header to get kid
        header = jwt.get_unverified_header(id_token)
        kid = header.get("kid")
        
        # Find matching key
        key = None
        for k in keys:
            if k["kid"] == kid:
                key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(k))
                break
        
        if key:
            decoded = jwt.decode(
                id_token,
                key,
                algorithms=["RS256"],
                audience=APPLE_CLIENT_ID,
                issuer="https://appleid.apple.com"
            )
            return {
                "email": decoded.get("email"),
                "name": decoded.get("name"),
                "provider_id": decoded.get("sub"),
                "provider": "apple"
            }
    except Exception as e:
        logger.error(f"Apple token verification failed: {e}")
    return None

auth_service = AuthService()
security = HTTPBearer(auto_error=False)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> User:
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    user_id = payload.get("sub")
    user = auth_service.get_user(user_id)
    if not user:
        if user_id and str(user_id).startswith("guest_"):
            user = auth_service.get_or_create_guest_user(str(user_id))
        else:
            raise HTTPException(status_code=401, detail="User not found")
    
    return user

async def get_optional_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Optional[User]:
    if not credentials:
        return None
    payload = decode_token(credentials.credentials)
    if not payload:
        return None
    user_id = payload.get("sub")
    user = auth_service.get_user(user_id)
    if not user and user_id and str(user_id).startswith("guest_"):
        user = auth_service.get_or_create_guest_user(str(user_id))
    return user

# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "AuthService", "auth_service", "get_current_user", "get_optional_user",
    "UserRegister", "UserLogin", "TokenResponse", "ChatCreate", "ChatUpdate",
    "create_access_token", "verify_password"
]