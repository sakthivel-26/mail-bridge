from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import httpx
import json
import base64
import os
import re
import time
import uuid
import sqlite3
import bcrypt
from pathlib import Path
from typing import Any, Literal
from dotenv import load_dotenv
from google.auth.transport import requests
from google.oauth2 import id_token
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "API is running"}

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

app = FastAPI(title="MailBridge API", version="1.0.0")

# Allow frontend to talk to backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static files
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

MYMEMORY_SAFE_CHUNK_CHARS = 450
SESSION_TTL_SECONDS = 24 * 60 * 60  # 24 hours
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
MCP_SEND_EMAIL_URL = os.getenv("MCP_SEND_EMAIL_URL", "").strip()
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8001").strip()

# Database setup
DB_PATH = Path(__file__).parent / "mailbridge.db"

def _init_db():
    """Initialize SQLite database with user and session tables."""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    # Users table: email only (no Gmail credentials)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    
    # Sessions table: token, user_id, expires_at
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    
    conn.commit()
    conn.close()

_init_db()

# In-memory session cache for faster lookups
AUTH_SESSIONS: dict[str, dict[str, Any]] = {}


def _chunk_text(text: str, max_chars: int = MYMEMORY_SAFE_CHUNK_CHARS) -> list[str]:
    """Split text into chunks within API limits while preserving whitespace."""
    chunks: list[str] = []
    current = ""

    for token in re.split(r"(\s+)", text):
        if not token:
            continue

        if len(token) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(token), max_chars):
                chunks.append(token[i:i + max_chars])
            continue

        if len(current) + len(token) > max_chars and current:
            chunks.append(current)
            current = token
        else:
            current += token

    if current:
        chunks.append(current)

    return chunks





def _normalize_email(value: str) -> str:
    return (value or "").strip().strip('"').strip("'").lower()


def _normalize_password(value: str) -> str:
    raw = (value or "").strip().strip('"').strip("'")
    return raw


def _hash_password(password: str) -> str:
    """Hash password using bcrypt."""
    salt = bcrypt.gensalt(rounds=10)
    return bcrypt.hashpw(password.encode(), salt).decode()


def _verify_password(password: str, hashed: str) -> bool:
    """Verify password against bcrypt hash."""
    return bcrypt.checkpw(password.encode(), hashed.encode())


def _get_user_by_email(email: str) -> dict[str, Any] | None:
    """Fetch user from database by email."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (_normalize_email(email),))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


async def _send_email_via_mcp(to: str, subject: str, body: str) -> None:
    """Send email via MCP Gmail Server."""
    # Support either a full send-email URL or a server base URL.
    if MCP_SEND_EMAIL_URL:
        mcp_url = MCP_SEND_EMAIL_URL
    else:
        mcp_url = f"{MCP_SERVER_URL.rstrip('/')}/send-email"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                mcp_url,
                json={"to": to, "subject": subject, "body": body},
                timeout=10.0
            )
        
        if response.status_code != 200:
            error_detail = response.json().get("detail", "Unknown error")
            raise HTTPException(status_code=500, detail=f"MCP server error: {error_detail}")
    
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail=(
                "Gmail MCP Server is not reachable. "
                "Check MCP_SERVER_URL or MCP_SEND_EMAIL_URL, or start local MCP server "
                "with: python gmail_mcp_server.py"
            )
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Email send failed: {str(e)}")


def _create_user(email: str) -> dict[str, Any]:
    """Create new user in database."""
    email_norm = _normalize_email(email)
    
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email_norm, _hash_password(""), time.time())
        )
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        
        return {"id": user_id, "email": email_norm}
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=409, detail="User already registered. Please login.")


def _create_auth_session(user_id: int) -> str:
    """Create session token in database."""
    token = uuid.uuid4().hex
    expires_at = time.time() + SESSION_TTL_SECONDS
    
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user_id, expires_at)
    )
    conn.commit()
    conn.close()
    
    # Cache in memory for faster lookup
    AUTH_SESSIONS[token] = {"user_id": user_id, "expires_at": expires_at}
    return token


def _get_auth_session(token: str) -> dict[str, Any]:
    """Retrieve and validate session token."""
    # Check in-memory cache first
    session = AUTH_SESSIONS.get(token)
    
    if session and time.time() <= session["expires_at"]:
        return session
    
    # If not in cache or expired, fetch from database
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sessions WHERE token = ?", (token,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=401, detail="Login required")
    
    session_data = dict(row)
    
    if time.time() > session_data["expires_at"]:
        # Clean up expired session
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
        conn.close()
        AUTH_SESSIONS.pop(token, None)
        raise HTTPException(status_code=401, detail="Session expired. Please login again")
    
    # Update cache
    AUTH_SESSIONS[token] = session_data
    return session_data


class GoogleAuthRequest(BaseModel):
    id_token: str  # ID token from Google Sign-In


class AuthLoginResponse(BaseModel):
    token: str
    email: str
    expires_in_seconds: int


# ---------- MODELS ----------

class TranslateRequest(BaseModel):
    text: str
    from_lang: str = "en"
    to_lang: str = "zh-CN"

class SendEmailRequest(BaseModel):
    to: str
    subject: str
    body: str          # already translated text
    from_lang: str = "en"
    to_lang: str = "zh-CN"

class TranslateAndSendRequest(BaseModel):
    to: str
    subject: str
    body: str          # original text (will be translated then sent)
    from_lang: str = "en"
    to_lang: str = "zh-CN"


# ---------- ROUTES ----------

@app.get("/")
def root():
    index_path = Path(__file__).parent / "static" / "index.html"
    return FileResponse(index_path)


@app.post("/translate")
async def translate(req: TranslateRequest):
    """Translate text using Google Translate free web endpoint."""
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    url = "https://translate.googleapis.com/translate_a/single"
    chunks = _chunk_text(req.text)

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            translated_parts = []
            for chunk in chunks:
                params = {
                    "client": "gtx",
                    "sl": req.from_lang,
                    "tl": req.to_lang,
                    "dt": "t",
                    "q": chunk,
                }
                res = await client.get(url, params=params)
                res.raise_for_status()
                data = res.json()

                # Response shape: [[[translated, source, ...], ...], ...]
                if not isinstance(data, list) or not data or not isinstance(data[0], list):
                    raise HTTPException(status_code=502, detail="Invalid response from translation provider")

                segment_text = "".join(
                    part[0] for part in data[0] if isinstance(part, list) and part and isinstance(part[0], str)
                )
                if not segment_text:
                    raise HTTPException(status_code=502, detail="Empty translation from provider")

                translated_parts.append(segment_text)

            translated = "".join(translated_parts)
            return {
                "success": True,
                "translated_text": translated,
                "lang_pair": f"{req.from_lang}|{req.to_lang}",
            }

        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail=f"Translation service error: {str(e)}")
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=502, detail=f"Translation provider HTTP error: {e.response.status_code}")


@app.post("/send-email")
async def send_email(req: SendEmailRequest, x_auth_token: str | None = Header(default=None, alias="X-Auth-Token")):
    """Send email using the MCP Gmail Server."""
    if not x_auth_token:
        raise HTTPException(status_code=401, detail="Login required")

    session = _get_auth_session(x_auth_token)
    user_id = session["user_id"]
    
    # Validate email recipient
    if not req.to or not req.subject or not req.body:
        raise HTTPException(status_code=400, detail="Email fields (to, subject, body) are required")
    
    # Send via MCP server
    await _send_email_via_mcp(req.to, req.subject, req.body)
    
    return {"success": True, "message": f"Email sent to {req.to}"}


@app.post("/translate-and-send")
async def translate_and_send(
    req: TranslateAndSendRequest,
    x_auth_token: str | None = Header(default=None, alias="X-Auth-Token"),
):
    """Translate email then send using the MCP Gmail Server."""
    if not x_auth_token:
        raise HTTPException(status_code=401, detail="Login required")

    session = _get_auth_session(x_auth_token)
    user_id = session["user_id"]

    # Validate input
    if not req.to or not req.subject or not req.body:
        raise HTTPException(status_code=400, detail="Email fields (to, subject, body) are required")

    # Step 1: Translate
    translate_req = TranslateRequest(text=req.body, from_lang=req.from_lang, to_lang=req.to_lang)
    translation = await translate(translate_req)
    translated_text = translation["translated_text"]

    # Step 2: Send via MCP
    await _send_email_via_mcp(req.to, req.subject, translated_text)

    return {
        "success": True,
        "translated_text": translated_text,
        "message": f"Email sent to {req.to}",
    }




@app.post("/auth/google", response_model=AuthLoginResponse)
def auth_google(req: GoogleAuthRequest):
    """Authenticate with Google OAuth ID token."""
    try:
        # Verify ID token with Google
        request_obj = requests.Request()
        idinfo = id_token.verify_oauth2_token(req.id_token, request_obj, GOOGLE_CLIENT_ID)
        
        # Extract email from token
        email = idinfo.get("email", "").lower()
        if not email:
            raise HTTPException(status_code=400, detail="Google token missing email")
        
        # Get or create user
        user = _get_user_by_email(email)
        if not user:
            # Auto-register if user doesn't exist
            user = _create_user(email)
        
        # Create session
        token = _create_auth_session(user["id"])
        
        return {
            "token": token,
            "email": user["email"],
            "expires_in_seconds": SESSION_TTL_SECONDS,
        }
    except ValueError as e:
        raise HTTPException(status_code=401, detail=f"Invalid Google token: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=401, detail="Google authentication failed")


@app.get("/auth/me")
def auth_me(x_auth_token: str | None = Header(default=None, alias="X-Auth-Token")):
    """Return active auth session info."""
    if not x_auth_token:
        raise HTTPException(status_code=401, detail="Login required")

    session = _get_auth_session(x_auth_token)
    user_id = session["user_id"]
    
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT email FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=401, detail="User not found")

    return {
        "email": row["email"],
        "expires_at": session["expires_at"],
    }


@app.post("/auth/logout")
def auth_logout(x_auth_token: str | None = Header(default=None, alias="X-Auth-Token")):
    """Logout current session token."""
    if x_auth_token:
        AUTH_SESSIONS.pop(x_auth_token, None)
        # Also delete from database
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE token = ?", (x_auth_token,))
        conn.commit()
        conn.close()
    return {"success": True}


@app.get("/health")
def health():
    return {"status": "ok", "service": "MailBridge"}
