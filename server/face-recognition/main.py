"""
Rate Limiting Integration — VotingSystem Face Auth API
=======================================================
Drop-in patch using slowapi + Redis backend.

Changes from original main.py:
1. Added Redis connection with fallback to in-memory
2. Added Limiter with per-route limits
3. Added custom error handler for 429 responses
4. Added /verify-face → 5/minute per IP
5. Added /enroll-face → 10/minute per IP (admin-only, less strict)
6. Added /health    → 60/minute (monitoring tools)
7. Added auth endpoints for session management

Install:
    pip install slowapi redis

Run:
    py -3.10 -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
"""

# ── Imports ──────────────────────────────────────────────────────────────────
import os
import json
import base64
import hashlib
import pickle
import sqlite3
import logging
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import cv2
import jwt
import numpy as np
import dotenv
import face_recognition
import redis as redis_client
from fastapi import FastAPI, HTTPException, Depends, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import bcrypt

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("face-auth")

# ── Environment ──────────────────────────────────────────────────────────────
from config import settings

SECRET_KEY: str = settings.resolved_secret_key
JWT_EXPIRY_HOURS: int = settings.JWT_EXPIRY_HOURS

def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("ascii")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("ascii"))
    except ValueError:
        return False
MATCH_TOLERANCE: float = settings.MATCH_TOLERANCE
EAR_MIN_CLOSED: float = settings.EAR_MIN_CLOSED
EAR_MIN_OPEN: float = settings.EAR_MIN_OPEN

# Redis connection string — read from env, fall back to localhost
REDIS_URL: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

ENCODINGS_PKL_PATH = (
    Path(__file__).resolve().parent.parent / "face_recognition" / "encodings.pkl"
)


# ═══════════════════════════════════════════════════════════════════════════
# RATE LIMITER SETUP
# ═══════════════════════════════════════════════════════════════════════════

def _build_limiter() -> Limiter:
    """
    Try to connect to Redis. If Redis is unavailable (e.g., dev without
    Docker), fall back to slowapi's in-memory store with a warning.

    In production, Redis MUST be running — in-memory doesn't persist
    across workers and won't protect a multi-process uvicorn deployment.
    """
    try:
        # Ping Redis to verify the connection before committing
        r = redis_client.from_url(REDIS_URL, socket_connect_timeout=2)
        r.ping()
        log.info("Rate limiter: Redis backend connected at %s", REDIS_URL)
        return Limiter(
            key_func=get_remote_address,
            storage_uri=REDIS_URL,
        )
    except Exception as exc:
        log.warning(
            "Redis unavailable (%s). Falling back to in-memory rate limiter. "
            "NOT suitable for multi-worker production deployments.",
            exc,
        )
        # In-memory fallback — omit storage_uri
        return Limiter(key_func=get_remote_address)


limiter = _build_limiter()


# ═══════════════════════════════════════════════════════════════════════════
# DATABASE SETUP  (unchanged from your original)
# ═══════════════════════════════════════════════════════════════════════════

DB_PATH = os.path.join(os.path.dirname(__file__), "face_voter_db.sqlite")


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")  
    # NORMAL is safe for app crashes; OS-level crash may lose last txn.
    # Acceptable for this deployment context (single-node, not safety-critical prod).
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS voters (
                voter_id       TEXT PRIMARY KEY NOT NULL,
                role           TEXT NOT NULL DEFAULT 'user',
                face_encoding  TEXT NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_voters_role ON voters(role);")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                admin_id      TEXT PRIMARY KEY NOT NULL,
                password_hash TEXT NOT NULL,
                created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                is_active     INTEGER NOT NULL DEFAULT 1
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_admins_active ON admins(is_active);")
        conn.commit()
    log.info("Database initialised at %s", DB_PATH)


def _average_encodings(encodings: list[np.ndarray]) -> np.ndarray:
    return np.mean(encodings, axis=0)


ENCODINGS_PKL_CHECKSUM_PATH = ENCODINGS_PKL_PATH.with_suffix(".sha256")


def _verify_pkl_integrity(pkl_path: Path) -> bytes:
    """Read the pickle file, compute SHA-256, and verify against stored checksum.
    
    On first run (no .sha256 file), compute and store the checksum.
    On subsequent runs, verify the file hasn't been tampered with.
    Returns the raw file bytes if verification passes.
    """
    raw = pkl_path.read_bytes()
    computed_hash = hashlib.sha256(raw).hexdigest()

    checksum_path = pkl_path.with_suffix(".sha256")

    if checksum_path.exists():
        stored_hash = checksum_path.read_text().strip()
        if computed_hash != stored_hash:
            raise RuntimeError(
                f"Integrity check FAILED for {pkl_path.name}. "
                f"Expected SHA-256: {stored_hash}, Got: {computed_hash}. "
                "The file may have been tampered with. Aborting."
            )
        log.info("   [INTEGRITY] %s checksum verified (%s)", pkl_path.name, computed_hash[:16])
    else:
        checksum_path.write_text(computed_hash)
        log.info("   [INTEGRITY] Stored initial SHA-256 for %s (%s)", pkl_path.name, computed_hash[:16])

    return raw


def sync_encodings_pkl() -> None:
    if not ENCODINGS_PKL_PATH.exists():
        log.warning("encodings.pkl not found at %s", ENCODINGS_PKL_PATH)
        return

    raw = _verify_pkl_integrity(ENCODINGS_PKL_PATH)
    data = pickle.loads(raw)

    names: list[str] = data.get("names", [])
    encodings: list = data.get("encodings", [])

    if len(names) != len(encodings):
        log.warning("encodings.pkl has mismatched names/encodings — skipping sync")
        return

    from collections import defaultdict
    grouped: dict[str, list[np.ndarray]] = defaultdict(list)
    for name, encoding in zip(names, encodings):
        voter_id = name.strip().lower()
        grouped[voter_id].append(np.asarray(encoding))

    with get_db() as conn:
        cursor = conn.cursor()
        synced = 0
        for voter_id, enc_list in grouped.items():
            cursor.execute("SELECT 1 FROM voters WHERE voter_id = ?", (voter_id,))
            if cursor.fetchone() is not None:
                continue
            averaged = _average_encodings(enc_list)
            encoding_json = json.dumps(averaged.tolist())
            cursor.execute(
                "INSERT INTO voters (voter_id, role, face_encoding) VALUES (?, ?, ?)",
                (voter_id, "user", encoding_json),
            )
            synced += 1
            log.info("   [SYNC] Imported '%s' (averaged %d sample(s))", voter_id, len(enc_list))
        conn.commit()

    log.info("Synced %d new face(s) from encodings.pkl", synced)


def _seed_admin() -> None:
    with get_db() as conn:
        cursor = conn.cursor()
        
        admin_pass = settings.ADMIN_PASSWORD
        
        if not admin_pass:
            raise ValueError("ADMIN_PASSWORD environment variable is missing. You MUST set a secure ADMIN_PASSWORD in the .env file before starting the server.")
            
        if len(admin_pass) < 12:
            raise ValueError("ADMIN_PASSWORD must be at least 12 characters long.")
            
        if not any(char.isdigit() for char in admin_pass):
            raise ValueError("ADMIN_PASSWORD must contain at least one digit.")
            
        if admin_pass.lower() in ["admin123", "password", "admin123456", "password123"]:
            raise ValueError("ADMIN_PASSWORD is set to a known weak value. Choose a stronger password.")

        hashed = get_password_hash(admin_pass)

        # Sync DB strictly with .env
        cursor.execute("DELETE FROM admins")
        cursor.execute(
            "INSERT INTO admins (admin_id, password_hash) VALUES (?, ?)",
            (settings.ADMIN_USERNAME, hashed),
        )
        log.info("   [SEED] Synced admin account (username and password) with .env")
            
        conn.commit()


# ═══════════════════════════════════════════════════════════════════════════
# IMAGE / FACE UTILITIES  (unchanged)
# ═══════════════════════════════════════════════════════════════════════════

# ── NEW: image size guard ────────────────────────────────────────────────────
MAX_IMAGE_B64_BYTES = 2_000_000   # ~1.5 MB decoded


def decode_base64_image(image_base64: str) -> np.ndarray:
    """Decode Base64 image. Rejects oversized payloads (DoS guard)."""
    if len(image_base64) > MAX_IMAGE_B64_BYTES:
        raise ValueError(
            f"Image payload too large ({len(image_base64)} bytes). "
            f"Maximum allowed: {MAX_IMAGE_B64_BYTES} bytes."
        )

    if "," in image_base64:
        image_base64 = image_base64.split(",", 1)[1]

    try:
        img_bytes = base64.b64decode(image_base64)
    except Exception as exc:
        raise ValueError(f"Base64 decoding failed: {exc}") from exc

    img_array = np.frombuffer(img_bytes, dtype=np.uint8)
    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

    if img is None:
        raise ValueError("cv2.imdecode returned None — not a valid image.")

    return img


def get_face_embedding(image: np.ndarray) -> Optional[np.ndarray]:
    details = get_face_details(image)
    return details[0] if details else None


def get_face_details(image: np.ndarray) -> Optional[tuple[np.ndarray, dict]]:
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    face_locations = face_recognition.face_locations(rgb, model="hog")

    if not face_locations:
        return None

    if len(face_locations) > 1:
        face_locations = [
            max(face_locations, key=lambda loc: (loc[2] - loc[0]) * (loc[1] - loc[3]))
        ]

    encodings = face_recognition.face_encodings(rgb, face_locations)
    if not encodings:
        return None

    landmarks = face_recognition.face_landmarks(rgb, face_locations)
    if not landmarks:
        return None

    return encodings[0], landmarks[0]


def calculate_ear(eye_points: list) -> float:
    A = np.linalg.norm(np.array(eye_points[1]) - np.array(eye_points[5]))
    B = np.linalg.norm(np.array(eye_points[2]) - np.array(eye_points[4]))
    C = np.linalg.norm(np.array(eye_points[0]) - np.array(eye_points[3]))
    return float((A + B) / (2.0 * C))


def compare_faces(
    known_encoding: np.ndarray,
    test_encoding: np.ndarray,
    tolerance: float = MATCH_TOLERANCE,
) -> tuple[bool, float]:
    distance = float(face_recognition.face_distance([known_encoding], test_encoding)[0])
    return distance <= tolerance, distance


# ═══════════════════════════════════════════════════════════════════════════
# JWT HELPERS  (unchanged)
# ═══════════════════════════════════════════════════════════════════════════

security = HTTPBearer(auto_error=False)


def create_jwt(voter_id: str, role: str) -> str:
    payload = {
        "voter_id": voter_id,
        "role": role,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def decode_jwt(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired. Please log in again.",
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
        )


async def require_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    # Accept token from Authorization Bearer header OR HttpOnly cookie
    token: Optional[str] = None
    if credentials is not None:
        token = credentials.credentials
    else:
        token = request.cookies.get("auth_token")

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Provide a Bearer token or log in first.",
        )
    payload = decode_jwt(token)
    if payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return payload


# ═══════════════════════════════════════════════════════════════════════════
# FASTAPI APPLICATION
# ═══════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting Face Authentication API...")
    init_db()
    sync_encodings_pkl()
    _seed_admin()
    log.info("Face Authentication API ready.")
    yield
    log.info("Face Authentication API shutting down.")


app = FastAPI(
    title="Voting DApp — Face Auth API",
    version="3.1.0",
    description="Facial-recognition authentication for the Decentralized Voting System.",
    lifespan=lifespan,
)

# ── HTTPS Enforcement and Security Headers ───────────────────────────────────
# app.add_middleware(HTTPSRedirectMiddleware)

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'self'"
    return response

# ── Attach limiter to app state ──────────────────────────────────────────────
app.state.limiter = limiter

# ── Custom 429 handler — returns clean JSON instead of slowapi's default ─────
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    log.warning(
        "[RATE LIMIT] %s blocked on %s — limit: %s",
        request.client.host if request.client else "unknown",
        request.url.path,
        exc.detail,
    )
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "detail": "Too many requests. Please wait before trying again.",
            "limit": str(exc.detail),
            "path": str(request.url.path),
        },
        headers={"Retry-After": "60"},
    )


# ── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Schemas ───────────────────────────────────────────────────────────────────

class FaceVerifyRequest(BaseModel):
    voter_id: str
    images_base64: list[str]

    @field_validator("images_base64")
    @classmethod
    def must_have_images(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("images_base64 must not be empty.")
        return v

    @field_validator("voter_id")
    @classmethod
    def voter_id_must_not_be_empty(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("voter_id must not be empty.")
        if len(cleaned) > 100:
            raise ValueError("voter_id must be 100 characters or fewer.")
        return cleaned


class AdminLoginRequest(BaseModel):
    username: str
    password: str

class AuthResponse(BaseModel):
    role: str
    voter_id: str
    # token is now delivered via HttpOnly cookie, NOT in the response body
    # distance REMOVED — was leaking face match proximity to client


class EnrollRequest(BaseModel):
    voter_id: str
    role: str = "user"
    image_base64: str

    @field_validator("voter_id")
    @classmethod
    def voter_id_must_not_be_empty(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("voter_id must not be empty.")
        if len(cleaned) > 100:
            raise ValueError("voter_id must be 100 characters or fewer.")
        return cleaned



@app.post("/api/v1/auth/refresh")
async def auth_refresh(request: Request, response: Response):
    """
    Refresh an existing auth token.
    
    If the current token is valid and not yet expired, issue a fresh token
    with a new expiry window. This prevents users from being logged out
    during active voting sessions.
    """
    token = request.cookies.get("auth_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = decode_jwt(token)
    voter_id = payload.get("voter_id")
    role = payload.get("role")

    if not voter_id or not role:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    new_token = create_jwt(voter_id, role)

    response.set_cookie(
        key="auth_token",
        value=new_token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=JWT_EXPIRY_HOURS * 3600,
    )

    log.info("[REFRESH] Token renewed for %s (role=%s)", voter_id, role)
    return {"role": role, "voter_id": voter_id, "message": "Token refreshed"}


# ═══════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/health")
@limiter.limit("60/minute")          # monitoring tools get generous allowance
async def health(request: Request):  # Request param required by slowapi
    """Quick health check for monitoring."""
    return {"status": "ok", "service": "face-auth", "version": "3.1.0"}


# Cookie configuration constants
_COOKIE_NAME = "auth_token"
_COOKIE_MAX_AGE = int(timedelta(hours=JWT_EXPIRY_HOURS).total_seconds())  # seconds


@app.post("/api/v1/admin-login")
@limiter.limit("5/minute")
async def admin_login(request: Request, body: AdminLoginRequest, response: Response):
    """
    Password-based login for administrators.
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT password_hash, is_active FROM admins WHERE admin_id = ?", (body.username,))
        row = cursor.fetchone()

        if row is None or not row["is_active"]:
            log.warning("Failed admin login attempt for '%s'", body.username)
            raise HTTPException(status_code=401, detail="Invalid credentials or account disabled")

        if not verify_password(body.password, row["password_hash"]):
            log.warning("Invalid password for admin '%s'", body.username)
            raise HTTPException(status_code=401, detail="Invalid credentials or account disabled")

    # Valid credentials -> issue token in cookie
    token = create_jwt(body.username, "admin")

    response.set_cookie(
        key="auth_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=JWT_EXPIRY_HOURS * 3600,
    )

    log.info("Admin '%s' logged in successfully via password", body.username)
    return {"role": "admin", "voter_id": body.username}


@app.post("/api/v1/verify-face", response_model=AuthResponse)
@limiter.limit("5/minute")           # 5 attempts per IP per minute
async def verify_face(request: Request, payload: FaceVerifyRequest):
    """
    Authenticate a voter by comparing a webcam sequence against the stored
    128D face encoding, with EAR-based blink liveness detection.

    Rate limited: 5 requests/minute per IP.
    """
    voter_id = payload.voter_id.strip().lower()

    if len(payload.images_base64) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Liveness detection requires a sequence of images (at least 2).",
        )

    # Decode images and extract face details
    frame_details = []
    for img_b64 in payload.images_base64:
        try:
            image = decode_base64_image(img_b64)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid image in sequence: {exc}",
            )

        details = get_face_details(image)
        if details is not None:
            frame_details.append(details)

    if not frame_details:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No faces detected in the provided image sequence.",
        )

    base_embedding = frame_details[0][0]

    # Consistency check + EAR collection across frames
    ears = []
    for emb, landmarks in frame_details:
        match, _ = compare_faces(base_embedding, emb, tolerance=0.4)
        if not match:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Multiple different faces or inconsistent face detected across frames.",
            )

        if "left_eye" in landmarks and "right_eye" in landmarks:
            left_ear = calculate_ear(landmarks["left_eye"])
            right_ear = calculate_ear(landmarks["right_eye"])
            ears.append((left_ear + right_ear) / 2.0)

    # Liveness: blink detection via EAR
    if len(ears) > 1:
        min_ear = min(ears)
        max_ear = max(ears)
        if min_ear > EAR_MIN_CLOSED or max_ear < EAR_MIN_OPEN:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Liveness check failed. Please blink while verifying.",
            )

    embedding = base_embedding

    # Fetch stored encoding
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT role, face_encoding FROM voters WHERE voter_id = ?",
            (voter_id,),
        )
        row = cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Voter ID not found. Please register first.",
        )

    role: str = row["role"]

    try:
        stored_encoding = np.array(json.loads(row["face_encoding"]), dtype=np.float64)
    except (json.JSONDecodeError, TypeError) as exc:
        log.error("Corrupt face encoding for voter '%s': %s", voter_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stored face encoding is corrupted. Please re-enroll.",
        )

    if stored_encoding.shape != (128,):
        log.error("Invalid encoding shape for voter '%s': %s", voter_id, stored_encoding.shape)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stored face encoding has invalid dimensions. Please re-enroll.",
        )

    is_match, distance = compare_faces(stored_encoding, embedding)

    log.info(
        "[VERIFY] voter=%s  distance=%.4f  tolerance=%s  match=%s",
        voter_id, distance, MATCH_TOLERANCE, "YES" if is_match else "NO",
    )

    if not is_match:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            # distance NOT included in client-facing message
            detail="Face verification failed. The face does not match the registered voter.",
        )

    token = create_jwt(voter_id, role)

    response = JSONResponse(
        content={"role": role, "voter_id": voter_id},
        status_code=status.HTTP_200_OK,
    )
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=_COOKIE_MAX_AGE,
        path="/",
    )
    log.info("[AUTH] voter='%s' role='%s' — HttpOnly cookie issued.", voter_id, role)
    return response


# ═══════════════════════════════════════════════════════════════════════════
# SESSION ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════


@app.get("/api/v1/auth/me")
@limiter.limit("30/minute")
async def auth_me(request: Request):
    """
    Returns the current session's voter_id and role by reading the HttpOnly
    auth cookie. Returns 401 if the cookie is absent or invalid.
    """
    token = request.cookies.get(_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )
    payload = decode_jwt(token)
    return {"voter_id": payload.get("voter_id"), "role": payload.get("role")}


@app.post("/api/v1/auth/logout")
@limiter.limit("10/minute")
async def auth_logout(request: Request):
    """
    Clears the auth cookie, effectively logging the user out.
    """
    response = JSONResponse(content={"message": "Logged out successfully."})
    response.delete_cookie(key=_COOKIE_NAME, path="/", samesite="strict")
    log.info("[AUTH] Logout — cookie cleared for %s", request.client.host if request.client else "unknown")
    return response


@app.post("/api/v1/enroll-face", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")          # admin actions — less strict than verify
async def enroll_face(
    request: Request,                # required by slowapi
    payload: EnrollRequest,
    _admin: dict = Depends(require_admin),
):
    """
    Register or update a voter's face encoding.
    Requires admin Bearer token.
    Rate limited: 10 requests/minute per IP.
    """
    voter_id = payload.voter_id.strip().lower()
    role = payload.role.strip()

    if role not in ("user", "admin"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="role must be 'user' or 'admin'.",
        )

    try:
        image = decode_base64_image(payload.image_base64)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid image: {exc}",
        )

    embedding = get_face_embedding(image)
    if embedding is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No face detected in the enrollment image.",
        )

    encoding_json = json.dumps(embedding.tolist())

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO voters (voter_id, role, face_encoding)
            VALUES (?, ?, ?)
            ON CONFLICT(voter_id) DO UPDATE SET
                role = excluded.role,
                face_encoding = excluded.face_encoding
            """,
            (voter_id, role, encoding_json),
        )
        conn.commit()

    log.info("[ENROLL] voter='%s' role='%s' enrolled/updated by admin.", voter_id, role)
    return {"message": f"Voter '{voter_id}' enrolled successfully.", "role": role}
