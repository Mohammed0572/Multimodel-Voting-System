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
import hmac
import secrets
import pickle
import sqlite3
import logging
import re
import asyncio
import time
from threading import BoundedSemaphore
from io import BytesIO
from PIL import Image
import active_liveness
from voting_service import VotingService, migrate as migrate_votes
from concurrent.futures import ThreadPoolExecutor
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
from fastapi.exceptions import RequestValidationError
from request_limits import RequestSizeLimit
from face_workers import FaceWorkers, FrameError
from face_profiles import parse_profile, build_profile, matches_sface, SFACE_MODEL
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import bcrypt
from web3 import Web3

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
_CREDENTIAL_COOKIE = "voting_credential"
_CREDENTIAL_MAX_AGE = settings.VOTING_CREDENTIAL_TTL_MINUTES * 60

# dlib's Windows build can terminate the entire process when multiple face
# detection/encoding calls run concurrently. Serialize native CV work so a
# voter request cannot take down the API process.
_cv_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="face-cv")
_cv_slots = BoundedSemaphore(1)
_face_workers = FaceWorkers(settings.FACE_WORKERS, settings.FACE_PROCESSING_TIMEOUT_SECONDS)

async def run_cv(function, *args):
    # Fail quickly under contention rather than queue voters behind expensive
    # enrollments or OCR. Native login inference uses isolated process workers.
    if not _cv_slots.acquire(blocking=False):
        raise HTTPException(503, "Face service is busy. Please try again shortly.")
    def execute():
        try:
            return function(*args)
        finally:
            _cv_slots.release()
    return await asyncio.shield(asyncio.get_running_loop().run_in_executor(_cv_executor, execute))


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
REDIS_URL: str = settings.REDIS_URL

ENCODINGS_PKL_PATH = Path(__file__).resolve().with_name("encodings.pkl")


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
        log.info("Rate limiter: Redis backend connected")
        return Limiter(
            key_func=get_remote_address,
            storage_uri=REDIS_URL,
        )
    except Exception:
        if settings.REQUIRE_REDIS:
            raise RuntimeError("Redis is required but unavailable")
        log.warning("Redis unavailable; using local per-process rate limiting")
        # In-memory fallback — omit storage_uri
        return Limiter(key_func=get_remote_address)


limiter = _build_limiter()


# ═══════════════════════════════════════════════════════════════════════════
# DATABASE SETUP  (unchanged from your original)
# ═══════════════════════════════════════════════════════════════════════════

DB_PATH = settings.resolved_face_db_path
CSBS_SEED_PATH = str(Path(__file__).resolve().with_name("csbs_students.json"))


@contextmanager
def get_db():
    if DB_PATH != ":memory:":
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=FULL;")
    conn.execute("PRAGMA foreign_keys=ON;")
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
                face_encoding  TEXT NOT NULL,
                name           TEXT,
                usn            TEXT,
                branch         TEXT,
                validity       TEXT,
                dob            TEXT
            )
        """)

        # Try to add columns if table already existed without them
        for col in ["name", "usn", "branch", "validity", "dob"]:
            try:
                cursor.execute(f"ALTER TABLE voters ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass # Column already exists

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_voters_role ON voters(role);")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deleted_voters (
                voter_id   TEXT PRIMARY KEY NOT NULL,
                deleted_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(voters)").fetchall()}
        for column, definition in {
            "student_name": "TEXT NOT NULL DEFAULT ''",
            "branch": "TEXT NOT NULL DEFAULT ''",
            "class_name": "TEXT NOT NULL DEFAULT ''",
            "batch": "TEXT NOT NULL DEFAULT ''",
            "id_verified": "INTEGER NOT NULL DEFAULT 0",
            "verified_by": "TEXT",
            "verified_at": "TEXT",
            "deleted": "INTEGER NOT NULL DEFAULT 0",
            "voted": "INTEGER NOT NULL DEFAULT 0",
            "last_voted_election_id": "TEXT",
            "pending_face_encoding": "TEXT",
            "face_updated_at": "TEXT",
            "session_version": "INTEGER NOT NULL DEFAULT 0",
        }.items():
            if column not in existing_columns:
                cursor.execute(f"ALTER TABLE voters ADD COLUMN {column} {definition}")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                admin_id      TEXT PRIMARY KEY NOT NULL,
                password_hash TEXT NOT NULL,
                created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                is_active     INTEGER NOT NULL DEFAULT 1
            )
        """)
        if "session_version" not in {row[1] for row in conn.execute("PRAGMA table_info(admins)")}:
            conn.execute("ALTER TABLE admins ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_admins_active ON admins(is_active);")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS voting_credentials (
                credential_hash TEXT PRIMARY KEY NOT NULL,
                voter_id TEXT NOT NULL,
                election_id TEXT NOT NULL DEFAULT '',
                issued_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                consumed_at TEXT,
                revoked_at TEXT,
                tx_hash TEXT
            )
        """)
        try:
            cursor.execute("ALTER TABLE voting_credentials ADD COLUMN revoked_at TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE voting_credentials ADD COLUMN tx_hash TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute(
                "ALTER TABLE voting_credentials ADD COLUMN election_id TEXT NOT NULL DEFAULT ''"
            )
        except sqlite3.OperationalError:
            pass
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS election_metadata (
                election_id TEXT PRIMARY KEY NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS active_election (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                contract_address TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            "INSERT OR IGNORE INTO active_election (id, contract_address) VALUES (1, ?)",
            (settings.BLOCKCHAIN_CONTRACT_ADDRESS.strip(),),
        )
        if os.getenv("RESET_ACTIVE_ELECTION", "").lower() == "true":
            cursor.execute(
                "UPDATE active_election SET contract_address = ? WHERE id = 1",
                (settings.BLOCKCHAIN_CONTRACT_ADDRESS.strip(),),
            )
        migrate_votes(conn)
        active_liveness.migrate(conn)
        if settings.SEED_DEMO_ROSTER and os.path.exists(CSBS_SEED_PATH):
            for student in json.loads(Path(CSBS_SEED_PATH).read_text()):
                cursor.execute(
                    """
                    INSERT INTO voters (voter_id, role, face_encoding, student_name, branch, class_name, batch)
                    SELECT ?, 'user', '', ?, 'CB', 'CSBS', ?
                    WHERE NOT EXISTS (
                        SELECT 1 FROM deleted_voters WHERE voter_id = ?
                    )
                    ON CONFLICT(voter_id) DO UPDATE SET
                        student_name = excluded.student_name,
                        branch = excluded.branch,
                        class_name = excluded.class_name,
                        batch = excluded.batch
                    """,
                    (
                        student["usn"].lower(),
                        student.get("student_name", ""),
                        "2024" if student["usn"].startswith("1KG24") else "2023",
                        student["usn"].lower(),
                    ),
                )
        conn.commit()
    log.info("Database initialised at %s", DB_PATH)


def voting_service():
    return VotingService(get_db, settings, VOTING_ABI, _active_contract_address)


def issue_voting_credential(voter_id: str) -> Optional[str]:
    return voting_service().issue(voter_id)


def _credential_hash_from_cookie(credential: str) -> str:
    try:
        raw = bytes.fromhex(credential)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid voting credential.") from exc
    if len(raw) != 32:
        raise HTTPException(status_code=401, detail="Invalid voting credential.")
    return hashlib.sha256(raw).hexdigest()


def _active_contract_address() -> str:
    with get_db() as conn:
        row = conn.execute(
            "SELECT contract_address FROM active_election WHERE id = 1"
        ).fetchone()
    return (
        (row["contract_address"] if row else "")
        or settings.BLOCKCHAIN_CONTRACT_ADDRESS
    ).strip()


def _current_election_id() -> str:
    """Use the active deployed contract address as the stable election ID."""
    return (_active_contract_address() or "default").lower()


def _relayer_configuration() -> tuple[str, str, str]:
    contract_address = _active_contract_address()
    relayer_address = settings.BLOCKCHAIN_RELAYER_ADDRESS
    private_key = settings.BLOCKCHAIN_RELAYER_PRIVATE_KEY

    if not contract_address:
        raise HTTPException(
            status_code=503,
            detail="Blockchain contract address is not configured.",
        )

    if not private_key:
        raise HTTPException(
            status_code=503,
            detail="Blockchain relayer private key is not configured.",
        )

    if not private_key.startswith("0x") or len(private_key) != 66:
        raise HTTPException(
            status_code=503,
            detail="Blockchain relayer private key is invalid.",
        )

    try:
        from eth_account import Account
        account = Account.from_key(private_key)
    except Exception:
        raise HTTPException(503, "Blockchain relayer key is invalid.")
    if relayer_address and relayer_address.lower() != account.address.lower():
        raise HTTPException(503, "Relayer key and address do not match.")
    relayer_address = account.address

    if not re.fullmatch(r"0x[a-fA-F0-9]{40}", contract_address):
        raise HTTPException(
            status_code=503,
            detail="Blockchain contract address is invalid.",
        )

    if not re.fullmatch(r"0x[a-fA-F0-9]{40}", relayer_address):
        raise HTTPException(
            status_code=503,
            detail="Blockchain relayer address is invalid.",
        )

    return contract_address, relayer_address, private_key


VOTING_ABI = [
    {
        "inputs": [],
        "name": "getElectionState",
        "outputs": [
            {
                "internalType": "enum Voting.ElectionState",
                "name": "",
                "type": "uint8",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "getCountCandidates",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "countCandidates",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "candidateId", "type": "uint256"}
        ],
        "name": "getCandidate",
        "outputs": [
            {"internalType": "uint256", "name": "id", "type": "uint256"},
            {"internalType": "string", "name": "name", "type": "string"},
            {"internalType": "string", "name": "party", "type": "string"},
            {"internalType": "uint256", "name": "voteCount", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {
                "internalType": "uint256",
                "name": "candidateId",
                "type": "uint256",
            },
            {
                "internalType": "bytes32",
                "name": "credential",
                "type": "bytes32",
            },
        ],
        "name": "vote",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": True,
                "internalType": "uint256",
                "name": "candidateId",
                "type": "uint256",
            },
            {
                "indexed": True,
                "internalType": "bytes32",
                "name": "credential",
                "type": "bytes32",
            },
            {
                "indexed": False,
                "internalType": "uint256",
                "name": "timestamp",
                "type": "uint256",
            },
        ],
        "name": "VoteCast",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [],
        "name": "ElectionStarted",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [],
        "name": "ElectionEnded",
        "type": "event",
    },
    {
        "inputs": [],
        "name": "owner",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "relayer",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
]


def _get_blockchain_contract():
    contract_address = _active_contract_address()
    if not contract_address or not re.fullmatch(r"0x[a-fA-F0-9]{40}", contract_address):
        return None, None
    try:
        web3 = Web3(Web3.HTTPProvider(settings.BLOCKCHAIN_RPC_URL))
        if not web3.is_connected():
            return None, None
        checksum_address = Web3.to_checksum_address(contract_address)
        contract = web3.eth.contract(address=checksum_address, abi=VOTING_ABI)
        return web3, contract
    except Exception as exc:
        log.warning("Blockchain node connection or contract load failed")
        return None, None


def _validate_new_election_contract(contract_address: str, owner_address: str) -> None:
    relayer_address = _relayer_configuration()[1]
    web3 = Web3(
        Web3.HTTPProvider(
            settings.BLOCKCHAIN_RPC_URL, request_kwargs={"timeout": 10}
        )
    )
    if not web3.is_connected():
        raise HTTPException(503, "Blockchain node is unavailable.")

    address = Web3.to_checksum_address(contract_address)
    if not web3.eth.get_code(address):
        raise HTTPException(400, "The new election contract has no deployed code.")

    contract = web3.eth.contract(address=address, abi=VOTING_ABI)
    try:
        state = int(contract.functions.getElectionState().call())
        candidates = int(contract.functions.countCandidates().call())
        owner = contract.functions.owner().call()
        relayer = contract.functions.relayer().call()
    except Exception as exc:
        raise HTTPException(
            400, "The deployed address is not a compatible voting contract."
        ) from exc

    if state != 0 or candidates != 0:
        raise HTTPException(
            409, "A new election must use a contract with no candidates and no votes."
        )
    if owner.lower() != owner_address.lower():
        raise HTTPException(
            403, "The connected wallet does not own the new election contract."
        )
    if relayer.lower() != relayer_address.lower():
        raise HTTPException(
            400, "The new contract relayer does not match the configured vote service."
        )


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
            
        if len(admin_pass.encode("utf-8")) > 72:
            raise ValueError("ADMIN_PASSWORD must be at most 72 UTF-8 bytes")
        if len(admin_pass) < 12:
            raise ValueError("ADMIN_PASSWORD must be at least 12 characters long.")
            
        if not any(char.isdigit() for char in admin_pass):
            raise ValueError("ADMIN_PASSWORD must contain at least one digit.")
            
        if admin_pass.lower() in ["admin123", "password", "admin123456", "password123"]:
            raise ValueError("ADMIN_PASSWORD is set to a known weak value. Choose a stronger password.")

        existing = cursor.execute("SELECT password_hash FROM admins WHERE admin_id=?", (settings.ADMIN_USERNAME,)).fetchone()
        cursor.execute("UPDATE admins SET is_active=0 WHERE admin_id!=?",(settings.ADMIN_USERNAME,))
        if not existing or not verify_password(admin_pass,existing["password_hash"]):
            hashed = get_password_hash(admin_pass)
            cursor.execute("""INSERT INTO admins(admin_id,password_hash) VALUES (?,?)
                ON CONFLICT(admin_id) DO UPDATE SET password_hash=excluded.password_hash,
                is_active=1,session_version=admins.session_version+1""",(settings.ADMIN_USERNAME,hashed))
        else:
            cursor.execute("UPDATE admins SET is_active=1 WHERE admin_id=?",(settings.ADMIN_USERNAME,))
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
        img_bytes = base64.b64decode(image_base64, validate=True)
        with Image.open(BytesIO(img_bytes), formats=("JPEG", "PNG")) as header:
            if header.width > 2048 or header.height > 2048 or header.width * header.height > 3_000_000:
                raise ValueError("Image dimensions exceed the supported camera size.")
    except Exception as exc:
        raise ValueError(f"Base64 decoding failed: {exc}") from exc

    img_array = np.frombuffer(img_bytes, dtype=np.uint8)
    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

    if img is None:
        raise ValueError("cv2.imdecode returned None — not a valid image.")

    height, width = img.shape[:2]
    if max(height,width) > 960:
        scale = 960 / max(height,width)
        img = cv2.resize(img,(round(width*scale),round(height*scale)),interpolation=cv2.INTER_AREA)
    return img


def validate_face_image_quality(image: np.ndarray, check_blur: bool = True) -> None:
    if image is None or image.size == 0:
        raise HTTPException(
            status_code=400,
            detail="Image is empty.",
        )

    height, width = image.shape[:2]

    if width < 320 or height < 240:
        raise HTTPException(
            status_code=400,
            detail="Camera resolution is too low.",
        )

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    brightness = float(np.mean(gray))
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    if brightness < 35:
        raise HTTPException(
            status_code=400,
            detail="Image is too dark.",
        )

    if brightness > 235:
        raise HTTPException(
            status_code=400,
            detail="Image is overexposed.",
        )

    if check_blur and sharpness < 35:
        raise HTTPException(
            status_code=400,
            detail="Image is blurry. Hold the camera steady.",
        )


def validate_embedding(embedding: np.ndarray) -> np.ndarray:
    vector = np.asarray(embedding, dtype=np.float32)

    if vector.shape != (128,):
        raise ValueError("Invalid face embedding shape.")

    if not np.isfinite(vector).all():
        raise ValueError("Face embedding contains invalid values.")

    norm = float(np.linalg.norm(vector))

    if norm <= 0:
        raise ValueError("Face embedding is empty.")

    return vector


def get_face_embedding(image: np.ndarray) -> Optional[np.ndarray]:
    details = get_face_details(image)
    if details and details[0] is not None:
        return validate_embedding(details[0])
    return None


def get_enrollment_embedding(
    images_base64: list[str],
) -> np.ndarray:
    embeddings: list[np.ndarray] = []

    if len(images_base64) < 5:
        raise HTTPException(
            status_code=400,
            detail="At least five enrollment images are required.",
        )

    for index, image_base64 in enumerate(images_base64, start=1):
        try:
            image = decode_base64_image(image_base64)
            validate_face_image_quality(image)

            details = get_face_details(image)

            if details is None:
                continue

            embedding, _landmarks = details

            if embedding is not None:
                embeddings.append(validate_embedding(embedding))

        except HTTPException:
            continue
        except Exception:
            log.exception("Enrollment frame %s failed", index)

    if len(embeddings) < 3:
        raise HTTPException(
            status_code=400,
            detail="At least three valid face frames are required.",
        )

    reference = embeddings[0]
    distances = [
        float(face_recognition.face_distance([reference], item)[0])
        for item in embeddings[1:]
    ]

    consistent = [
        reference,
        *[
            embedding
            for embedding, distance in zip(embeddings[1:], distances)
            if distance <= 0.60
        ],
    ]

    if len(consistent) < 3:
        raise HTTPException(
            status_code=400,
            detail="Enrollment images are inconsistent.",
        )

    averaged = np.mean(consistent, axis=0)
    return validate_embedding(averaged)


def get_enrollment_profile(images_base64):
    if not 5 <= len(images_base64) <= 10:
        raise HTTPException(400, "Five to ten enrollment images are required.")
    images = []
    for encoded in images_base64:
        try:
            image = decode_base64_image(encoded)
            validate_face_image_quality(image)
            images.append(image)
        except ValueError:
            raise HTTPException(400, "Invalid enrollment image.") from None
    try:
        details = _face_workers.analyze(images, model=SFACE_MODEL)
        if len(details) != len(images):
            raise RuntimeError("Incomplete enrollment analysis")
        return build_profile([item[0] for item in details if item is not None])
    except FrameError as error:
        raise HTTPException(400, str(error)) from None
    except ValueError as error:
        raise HTTPException(400, str(error)) from None
    except Exception:
        raise HTTPException(503, "Face enrollment is temporarily unavailable. Please retry.") from None


def get_face_details(
    image: np.ndarray,
    need_encoding: bool = True,
    normalize_illumination: bool = False,
) -> Optional[tuple[Optional[np.ndarray], dict]]:
    working_image = image
    if normalize_illumination:
        # Local contrast normalization helps with shadows without loosening
        # the face-match threshold. Login can also fall back to the original
        # pixels for profiles enrolled before this enhancement.
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        lightness, channel_a, channel_b = cv2.split(lab)
        lightness = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(lightness)
        working_image = cv2.cvtColor(
            cv2.merge((lightness, channel_a, channel_b)),
            cv2.COLOR_LAB2BGR,
        )
    rgb = cv2.cvtColor(working_image, cv2.COLOR_BGR2RGB)

    height, width = rgb.shape[:2]
    if height < 80 or width < 80:
        return None

    # Half-size detection keeps enough face detail for ordinary laptop cameras
    # while remaining much cheaper than running HOG over the full frame.
    detection_scale = 0.5 if min(height, width) >= 320 else 1.0
    if detection_scale == 1.0:
        small_rgb = rgb
    else:
        small_rgb = cv2.resize(rgb, (0, 0), fx=detection_scale, fy=detection_scale)

    face_locations = face_recognition.face_locations(
        small_rgb,
        model="hog",
    )

    if len(face_locations) == 0:
        return None

    if len(face_locations) > 1:
        raise HTTPException(
            status_code=400,
            detail="Only one face must be visible.",
        )

    # Rescale locations back to original image for encoding
    scaled_locations = [
        tuple(int(coord / detection_scale) for coord in loc) for loc in face_locations
    ]

    top, right, bottom, left = scaled_locations[0]
    if min(right-left, bottom-top) < 80:
        raise HTTPException(400, "Move closer. Your face is too small in the image.")
    landmarks = face_recognition.face_landmarks(rgb, scaled_locations)
    if not landmarks:
        return None

    encoding: Optional[np.ndarray] = None
    if need_encoding:
        encodings = face_recognition.face_encodings(rgb, scaled_locations)
        if not encodings:
            return None
        encoding = validate_embedding(encodings[0])

    if abs(active_liveness.yaw(landmarks[0])) > 0.65:
        raise HTTPException(400, "Look toward the camera; avoid turning too far.")
    return encoding, landmarks[0]


def verify_against_stored_encoding(
    stored_encoding: np.ndarray,
    live_images: list[np.ndarray],
) -> tuple[bool, float]:
    distances: list[float] = []

    for image in live_images:
        try:
            validate_face_image_quality(image)
        except HTTPException:
            continue

        details = get_face_details(image)

        if details is None:
            continue

        embedding, _landmarks = details

        if embedding is None:
            continue

        embedding = validate_embedding(embedding)

        distance = float(
            face_recognition.face_distance(
                [stored_encoding],
                embedding,
            )[0]
        )

        distances.append(distance)

    if len(distances) < 3:
        return False, 1.0

    distances.sort()

    best_distances = distances[:3]
    median_distance = float(np.median(best_distances))

    return (
        median_distance <= settings.MATCH_TOLERANCE,
        median_distance,
    )


def calculate_ear(eye_points: list) -> float:
    A = np.linalg.norm(np.array(eye_points[1]) - np.array(eye_points[5]))
    B = np.linalg.norm(np.array(eye_points[2]) - np.array(eye_points[4]))
    C = np.linalg.norm(np.array(eye_points[0]) - np.array(eye_points[3]))
    return float((A + B) / (2.0 * C)) if C > 0 else 0.0


def _has_blink_sequence(eye_samples: list[tuple[Optional[float], Optional[float]]]) -> bool:
    """Require open -> bilateral closure -> open, including longer closures.

    The old sliding baseline could fall inside a deliberately closed interval
    and reject the same close/open action that the screen requested.
    """
    if len(eye_samples) < 6:
        return False
    try:
        values = np.asarray(eye_samples, dtype=float)
    except (ValueError, TypeError):
        return False
    if values.shape != (len(eye_samples), 2) or not np.isfinite(values).all():
        return False
    minimum_open = max(.18, EAR_MIN_OPEN * .70)
    if np.any(values[:2] < minimum_open) or np.any(values[-2:] < minimum_open):
        return False
    baseline = np.minimum(np.median(values[:2], axis=0), np.median(values[-2:], axis=0))
    closed = np.all((values[2:-2] <= baseline*.85) & (baseline-values[2:-2] >= .03), axis=1)
    return bool(np.any(closed))


def compare_faces(
    known_encoding: np.ndarray,
    test_encoding: np.ndarray,
    tolerance: float = MATCH_TOLERANCE,
) -> tuple[bool, float]:
    known = validate_embedding(known_encoding)
    test = validate_embedding(test_encoding)
    distance = float(face_recognition.face_distance([known], test)[0])
    return distance <= tolerance, distance


# ═══════════════════════════════════════════════════════════════════════════
# JWT HELPERS  (unchanged)
# ═══════════════════════════════════════════════════════════════════════════

security = HTTPBearer(auto_error=False)


def create_jwt(voter_id: str, role: str, version=None) -> str:
    with get_db() as conn:
        if role == "admin":
            row = conn.execute("SELECT session_version FROM admins WHERE admin_id=?",(voter_id,)).fetchone()
        else:
            row = conn.execute("SELECT session_version FROM voters WHERE voter_id=?",(voter_id,)).fetchone()
    payload = {
        "version": version if version is not None else row[0] if row else -1,
        "voter_id": voter_id,
        "role": role,
        "jti": secrets.token_urlsafe(32),
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def decode_jwt(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"],
            options={"require": ["exp", "iat", "jti", "voter_id", "role", "version"]})
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Session expired or invalid. Please log in again.")
    with get_db() as conn:
        if conn.execute("SELECT 1 FROM revoked_sessions WHERE jti=?", (payload["jti"],)).fetchone():
            raise HTTPException(401, "Session has been signed out.")
        if payload["role"] == "admin":
            account = conn.execute("SELECT session_version FROM admins WHERE admin_id=? AND is_active=1", (payload["voter_id"],)).fetchone()
        elif payload["role"] == "user":
            account = conn.execute("SELECT session_version FROM voters WHERE voter_id=? AND deleted=0 AND role='user'", (payload["voter_id"],)).fetchone()
        else:
            account = None
    if not account or account[0] != payload["version"]:
        raise HTTPException(401, "Account is no longer active.")
    return payload


def revoke_session(payload):
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO revoked_sessions VALUES (?,?)", (payload["jti"],time.time() + JWT_EXPIRY_HOURS * 3600))
        conn.commit()


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


async def require_voter(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    token: Optional[str] = None
    if credentials is not None:
        token = credentials.credentials
    else:
        token = request.cookies.get("auth_token")

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Voter login required.",
        )
    payload = decode_jwt(token)
    if payload.get("role") != "user":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Voter access required.",
        )
    return payload


# ═══════════════════════════════════════════════════════════════════════════
# FASTAPI APPLICATION
# ═══════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting Face Authentication API...")
    if len(SECRET_KEY.encode()) < 32:
        raise RuntimeError("SECRET_KEY must contain at least 32 bytes of random secret material")
    init_db()
    if settings.IMPORT_LEGACY_PICKLE:
        sync_encodings_pkl()
    _seed_admin()
    if _active_contract_address():
        _relayer_configuration()
    if settings.COOKIE_SAMESITE == "none" and not settings.COOKIE_SECURE:
        raise RuntimeError("SameSite=None requires COOKIE_SECURE=true")
    await run_in_threadpool(_face_workers.start)
    log.info("Face Authentication API ready: %d warmed face workers.", settings.FACE_WORKERS)
    async def reconcile_loop():
        while True:
            try:
                await run_in_threadpool(voting_service().reconcile)
            except Exception:
                log.warning("Reconciliation deferred")
            await asyncio.sleep(10)
    reconciler = asyncio.create_task(reconcile_loop())
    try:
        yield
    finally:
        reconciler.cancel()
        try:
            await reconciler
        except asyncio.CancelledError:
            pass
        await run_in_threadpool(_face_workers.close)
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
    origin = request.headers.get("origin")
    # CORS alone does not stop cross-site state changes using cookies.
    if (request.method not in ("GET", "HEAD", "OPTIONS") or request.url.path.endswith(("/eligibility", "/challenge"))):
        if origin and origin not in settings.frontend_origins:
            return JSONResponse({"detail": "Untrusted request origin."}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site" and not origin:
            return JSONResponse({"detail": "Cross-site request denied."}, status_code=403)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
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
    allow_origins=settings.frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.add_middleware(RequestSizeLimit)

@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError):
    # Never echo rejected biometric images, passwords or raw credentials.
    return JSONResponse({"detail": "Invalid request fields.", "errors": [
        {"loc": error["loc"], "type": error["type"]} for error in exc.errors()
    ]}, status_code=422)

# ── Schemas ───────────────────────────────────────────────────────────────────

class FaceVerifyRequest(BaseModel):
    voter_id: str
    challenge_id: str
    images_base64: list[str] = Field(min_length=10, max_length=16)

    @field_validator("images_base64")
    @classmethod
    def must_have_images(cls, v: list[str]) -> list[str]:
        if any(len(frame) > MAX_IMAGE_B64_BYTES for frame in v):
            raise ValueError("Image payload too large.")
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

    @field_validator("challenge_id")
    @classmethod
    def challenge_id_must_not_be_empty(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned or len(cleaned) > 128:
            raise ValueError("A valid liveness challenge is required.")
        return cleaned


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=72)

class AuthResponse(BaseModel):
    role: str
    voter_id: str
    name: Optional[str] = Field(default=None, max_length=200)
    usn: Optional[str] = Field(default=None, max_length=100)
    branch: Optional[str] = Field(default=None, max_length=200)
    validity: Optional[str] = Field(default=None, max_length=50)
    dob: Optional[str] = Field(default=None, max_length=50)
    # token is now delivered via HttpOnly cookie, NOT in the response body
    # distance REMOVED — was leaking face match proximity to client


class EnrollRequest(BaseModel):
    voter_id: str
    role: str = "user"
    image_base64: str = Field(default="", max_length=MAX_IMAGE_B64_BYTES)
    images_base64: Optional[list[str]] = Field(default=None, min_length=5, max_length=10)
    name: Optional[str] = Field(default=None, max_length=200)
    usn: Optional[str] = Field(default=None, max_length=100)
    branch: Optional[str] = Field(default=None, max_length=200)
    validity: Optional[str] = Field(default=None, max_length=50)
    dob: Optional[str] = Field(default=None, max_length=50)

    @field_validator("voter_id")
    @classmethod
    def voter_id_must_not_be_empty(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("voter_id must not be empty.")
        if len(cleaned) > 100:
            raise ValueError("voter_id must be 100 characters or fewer.")
        return cleaned

    @field_validator("images_base64")
    @classmethod
    def image_sequence_must_not_be_empty(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v and any(len(frame) > MAX_IMAGE_B64_BYTES for frame in v):
            raise ValueError("Image payload too large.")
        if v is not None and not v:
            raise ValueError("images_base64 must not be empty when provided.")
        return v


class ExtractIDRequest(BaseModel):
    image_base64: str = Field(max_length=MAX_IMAGE_B64_BYTES)


class EligibilityVerificationRequest(BaseModel):
    verified: bool


class ElectionNameRequest(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def election_name_must_not_be_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Election name must not be empty.")
        if len(cleaned) > 120:
            raise ValueError("Election name must be 120 characters or fewer.")
        return cleaned


class ElectionActivationRequest(ElectionNameRequest):
    contract_address: str
    owner_address: str

    @field_validator("contract_address", "owner_address")
    @classmethod
    def validate_wallet_address(cls, value: str) -> str:
        cleaned = value.strip()
        if not re.fullmatch(r"0x[a-fA-F0-9]{40}", cleaned):
            raise ValueError("A valid wallet address is required.")
        return Web3.to_checksum_address(cleaned)


class CastVoteRequest(BaseModel):
    candidate_id: int = Field(strict=True, gt=0, le=2**31-1)



@app.post("/api/v1/auth/refresh")
@limiter.limit("30/minute")
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

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, usn, branch, validity, dob, student_name FROM voters WHERE voter_id = ?",
            (voter_id.lower(),),
        )
        row = cursor.fetchone()

    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM revoked_sessions WHERE jti=?",(payload["jti"],)).fetchone():
            raise HTTPException(401, "Session has been signed out.")
        new_token = jwt.encode({**payload, "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS)}, SECRET_KEY, algorithm="HS256")
        conn.commit()

    resolved_name = (row["name"] or row["student_name"]) if row else None
    resolved_usn = (row["usn"] or str(voter_id).upper()) if row else str(voter_id).upper()

    res = JSONResponse(
        content={
            "role": role,
            "voter_id": voter_id,
            "name": resolved_name,
            "usn": resolved_usn,
            "branch": row["branch"] if row else None,
            "validity": row["validity"] if row else None,
            "dob": row["dob"] if row else None,
            "message": "Token refreshed",
        },
        status_code=status.HTTP_200_OK,
    )
    res.set_cookie(
        key=_COOKIE_NAME,
        value=new_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=_COOKIE_MAX_AGE,
        path="/",
    )

    log.info("[REFRESH] Token renewed for %s (role=%s)", voter_id, role)
    return res


# ═══════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

ocr_reader = None


def get_ocr_reader():
    global ocr_reader
    if ocr_reader is None:
        try:
            import easyocr  # type: ignore[import-untyped,import-not-found]
            ocr_reader = easyocr.Reader(["en"], gpu=False)
        except Exception as exc:
            log.warning("EasyOCR could not be initialized: %s", exc)
            ocr_reader = None
    return ocr_reader


@app.post("/api/v1/extract-id")
@limiter.limit("10/minute")
async def extract_id(request: Request, body: ExtractIDRequest):
    """Extracts Name, USN, Branch, Validity, and DOB from an ID card image."""
    reader = await run_cv(get_ocr_reader)
    if reader is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OCR service is unavailable (easyocr is not installed or initialized).",
        )

    try:
        img = decode_base64_image(body.image_base64)
    except ValueError:
        raise HTTPException(400, "Invalid ID image.")
    results = await run_cv(lambda: reader.readtext(img, detail=0))

    details = {
        "name": "",
        "usn": "",
        "branch": "",
        "validity": "",
        "dob": "",
    }

    usn_pattern = re.compile(r"\d[A-Z]{2}\d{2}[A-Z]{2}\d{3}", re.IGNORECASE)
    dob_pattern = re.compile(r"\d{2}[/-]\d{2}[/-]\d{4}")

    for i, text in enumerate(results):
        text = text.strip()

        usn_match = usn_pattern.search(text)
        if usn_match and not details["usn"]:
            details["usn"] = usn_match.group().upper()

        dob_match = dob_pattern.search(text)
        if dob_match and not details["dob"]:
            details["dob"] = dob_match.group()

        elif "validity" in text.lower() or "valid till" in text.lower() or "expiry" in text.lower():
            if i + 1 < len(results):
                details["validity"] = results[i + 1]

    # fallback heuristics
    return {"extracted": details, "raw": results}

@app.get("/health")
@limiter.limit("60/minute")          # monitoring tools get generous allowance
async def health(request: Request):  # Request param required by slowapi
    """Quick health check for monitoring."""
    return {"status": "ok", "service": "face-auth", "version": "3.3.0", "face_engine_version": 3}


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
        cursor.execute("SELECT password_hash, is_active, session_version FROM admins WHERE admin_id = ?", (body.username,))
        row = cursor.fetchone()

        if row is None or not row["is_active"]:
            log.warning("Failed admin login attempt for '%s'", body.username)
            raise HTTPException(status_code=401, detail="Invalid credentials or account disabled")

        if not await run_in_threadpool(verify_password, body.password, row["password_hash"]):
            log.warning("Invalid password for admin '%s'", body.username)
            raise HTTPException(status_code=401, detail="Invalid credentials or account disabled")

    # Valid credentials -> issue token in cookie
    token = create_jwt(body.username, "admin", version=row["session_version"])

    res = JSONResponse(
        content={"role": "admin", "voter_id": body.username},
        status_code=status.HTTP_200_OK,
    )
    res.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=_COOKIE_MAX_AGE,
        path="/",
    )

    log.info("Admin '%s' logged in successfully via password", body.username)
    return res


@app.post("/api/v1/verify-face", response_model=AuthResponse)
@limiter.limit("5/minute")           # 5 attempts per IP per minute
async def verify_face(request: Request, payload: FaceVerifyRequest):
    """
    Authenticate a voter by comparing a webcam sequence against the stored
    face profile, with a one-use bilateral eye-close/open challenge.

    Rate limited: 5 requests/minute per IP.
    """
    voter_id = payload.voter_id.strip().lower()

    challenge_action = active_liveness.consume(get_db, payload.challenge_id, voter_id, len(payload.images_base64))

    # Check that this voter has a face profile before spending time decoding
    # frames. The CSBS roster is preloaded with empty templates until signup.
    with get_db() as conn:
        row = conn.execute(
            "SELECT role, face_encoding, pending_face_encoding, name, usn, branch, validity, dob, id_verified, student_name, voted, session_version "
            "FROM voters WHERE voter_id = ? AND deleted=0 AND role='user'",
            (voter_id,),
        ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voter ID not found. Register this voter first.",
        )
    if not row["id_verified"]:
        raise HTTPException(403, "Administrator approval is required before login.")
    if not row["face_encoding"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This voter ID is on the roster but has no face profile yet. Complete face registration, then try again.",
        )
    try:
        profile_model, templates = parse_profile(row["face_encoding"])
    except (json.JSONDecodeError, TypeError, ValueError):
        log.error("Corrupt face encoding for voter '%s'", voter_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The saved face profile is invalid. Please register your face again.",
        )

    timings = {}
    def process_sequence():
        started = time.perf_counter()
        images = []
        for encoded in payload.images_base64:
            try:
                image = decode_base64_image(encoded)
            except ValueError:
                raise HTTPException(400, "Invalid camera image.")
            # Identity/detection evaluate every frame. Background blur alone
            # must not reject login; enrollment retains sharpness checks.
            validate_face_image_quality(image, check_blur=False)
            images.append(image)
        active_liveness.reject_replays(get_db, images)
        timings["decode"] = (time.perf_counter()-started)*1000
        observations = []
        distances = []
        inference_started = time.perf_counter()
        details_sequence = _face_workers.analyze(images, model=profile_model)
        if len(details_sequence) != len(images):
            raise HTTPException(503, "Incomplete face analysis. Start a new live check.")
        for details in details_sequence:
            if details is None or details[0] is None:
                raise HTTPException(400, "Keep one face visible throughout the live check.")
            matched, distance = (matches_sface(templates, details[0]) if profile_model == SFACE_MODEL
                                 else compare_faces(templates[0], details[0]))
            if not matched:
                if row["pending_face_encoding"]:
                    raise HTTPException(409, "Your replacement face is awaiting administrator approval. Login still uses your previous face profile.")
                raise HTTPException(401, "Your face did not match the active profile. Keep your face lit and hold still. If you updated it, check that the administrator approved the replacement.")
            observations.append(details[1])
            distances.append(distance)
        active_liveness.validate(challenge_action, observations, calculate_ear, _has_blink_sequence)
        timings["inference"] = (time.perf_counter()-inference_started)*1000
        log.info("Live sequence validated: model=%s frames=%d decode_ms=%.1f inference_ms=%.1f workers=%d",
                 profile_model, len(images), timings["decode"], timings["inference"], settings.FACE_WORKERS)
        return float(np.median(distances))

    # One admitted CV request; its frame jobs run in isolated native processes.
    try:
        await run_cv(process_sequence)
    except FrameError as error:
        raise HTTPException(400, str(error)) from None
    except HTTPException as error:
        log.info("Live verification rejected: %s", error.detail)
        raise
    except Exception:
        log.warning("Face processing unavailable")
        raise HTTPException(503, "Face verification is temporarily unavailable. Please try again.")

    role: str = row["role"]
    profile_name = row["name"] or row["student_name"]
    profile_usn = row["usn"] or voter_id.upper()
    profile_branch = row["branch"]
    profile_validity = row["validity"]
    profile_dob = row["dob"]
    is_eligible = bool(row["id_verified"])

    with get_db() as conn:
        latest = conn.execute("SELECT session_version,id_verified,deleted FROM voters WHERE voter_id=?",(voter_id,)).fetchone()
        if not latest or latest["deleted"] or not latest["id_verified"] or latest["session_version"] != row["session_version"]:
            raise HTTPException(401, "Account changed during verification. Start again.")
    token = create_jwt(voter_id, role, version=row["session_version"])
    voting_credential = (
        issue_voting_credential(voter_id)
        if is_eligible and role == "user"
        else None
    )

    response = JSONResponse(
        content={
            "role": role,
            "voter_id": voter_id,
            "name": profile_name,
            "usn": profile_usn,
            "branch": profile_branch,
            "validity": profile_validity,
            "dob": profile_dob,
        },
        status_code=status.HTTP_200_OK,
        headers={"Server-Timing": ", ".join(f"{name};dur={duration:.1f}" for name, duration in timings.items())},
    )
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=_COOKIE_MAX_AGE,
        path="/",
    )
    if voting_credential:
        response.set_cookie(
            key=_CREDENTIAL_COOKIE,
            value=voting_credential,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAMESITE,
            max_age=_CREDENTIAL_MAX_AGE,
            path="/",
        )
    else:
        response.delete_cookie(
            key=_CREDENTIAL_COOKIE,
            path="/",
            samesite=settings.COOKIE_SAMESITE,
            secure=settings.COOKIE_SECURE,
            httponly=True,
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
    voter_id = payload.get("voter_id")
    if not voter_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session.",
        )

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, usn, branch, validity, dob, student_name FROM voters WHERE voter_id = ?",
            (str(voter_id).lower(),),
        )
        row = cursor.fetchone()

    resolved_name = (row["name"] or row["student_name"]) if row else None
    resolved_usn = (row["usn"] or str(voter_id).upper()) if row else str(voter_id).upper()

    return {
        "voter_id": voter_id,
        "role": payload.get("role"),
        "name": resolved_name,
        "usn": resolved_usn,
        "branch": row["branch"] if row else None,
        "validity": row["validity"] if row else None,
        "dob": row["dob"] if row else None,
    }


@app.post("/api/v1/auth/logout")
@limiter.limit("10/minute")
async def auth_logout(request: Request):
    """
    Clears the auth cookie, effectively logging the user out.
    """
    token = request.cookies.get(_COOKIE_NAME)
    if token:
        try:
            payload = decode_jwt(token)
            revoke_session(payload)
        except HTTPException:
            pass
    # A pending or confirmed authorization is never released by logout.

    response = JSONResponse(content={"message": "Logged out successfully."})
    response.delete_cookie(key=_COOKIE_NAME, path="/", samesite=settings.COOKIE_SAMESITE)
    response.delete_cookie(
        key=_CREDENTIAL_COOKIE,
        path="/",
        samesite=settings.COOKIE_SAMESITE,
        secure=settings.COOKIE_SECURE,
        httponly=True,
    )
    log.info("[AUTH] Logout — cookie cleared for %s", request.client.host if request.client else "unknown")
    return response


@app.get("/api/v1/admin/voters")
@limiter.limit("30/minute")
async def admin_voters(
    request: Request,
    response: Response,
    _admin: dict = Depends(require_admin),
):
    """Return the CSBS voter registry from SQLite for the admin dashboard."""
    # Participation is time-sensitive and account-specific; do not let the
    # browser reuse a cached pre-vote roster response.
    response.headers["Cache-Control"] = "private, no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    election_id = _current_election_id()
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT voter_id, role
                 , student_name, name, branch, class_name, batch, id_verified, verified_by, verified_at
                 , pending_face_encoding
                 , (EXISTS(
                     SELECT 1 FROM voting_credentials vc
                     WHERE vc.voter_id = voters.voter_id
                       AND vc.election_id = ?
                       AND vc.consumed_at IS NOT NULL
                   ) OR voters.last_voted_election_id = ?) AS has_voted
            FROM voters
            WHERE deleted=0
            ORDER BY voter_id
            """,
            (election_id, election_id),
        ).fetchall()

    students = []
    for row in rows:
        voter_id = row["voter_id"].upper()
        students.append({
            "usn": voter_id,
            "branch": row["branch"],
            "className": row["class_name"],
            "batch": row["batch"],
            "number": len(students) + 1,
            "role": row["role"],
            "studentName": row["student_name"] or row["name"] or "",
            "idVerified": bool(row["id_verified"]),
            "faceUpdatePending": bool(row["pending_face_encoding"]),
            "hasVoted": bool(row["has_voted"]),
            "verifiedBy": row["verified_by"],
            "verifiedAt": row["verified_at"],
        })
    return {
        "students": students,
        "total": len(students),
        "election_id": election_id,
    }


@app.patch("/api/v1/admin/voters/{voter_id}/verify")
@limiter.limit("30/minute")
async def verify_voter_eligibility(
    request: Request,
    voter_id: str,
    payload: EligibilityVerificationRequest,
    admin: dict = Depends(require_admin),
):
    """Record an admin's physical ID-card eligibility check in SQLite."""
    normalized_id = voter_id.strip().lower()
    with get_db() as conn:
        cursor = conn.execute(
            """
            UPDATE voters
            SET session_version=session_version+1, id_verified = ?, verified_by = ?, verified_at = ?
            WHERE voter_id = ? AND deleted=0
            """,
            (int(payload.verified), admin["voter_id"], datetime.now(timezone.utc).isoformat(), normalized_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Voter not found.")
        conn.commit()
    log.info("Eligibility approval changed: eligible=%s", payload.verified)
    return {"voter_id": normalized_id.upper(), "id_verified": payload.verified}


@app.post("/api/v1/admin/voters/{voter_id}/approve-face-update")
@limiter.limit("30/minute")
async def approve_face_update(
    request: Request,
    voter_id: str,
    admin: dict = Depends(require_admin),
):
    """Activate a replacement face profile after an admin identity check."""
    normalized_id = voter_id.strip().lower()
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        pending = conn.execute("SELECT pending_face_encoding FROM voters WHERE voter_id=? AND deleted=0", (normalized_id,)).fetchone()
        if pending and pending["pending_face_encoding"]:
            try:
                parse_profile(pending["pending_face_encoding"])
            except (ValueError, TypeError):
                raise HTTPException(409, "The replacement profile is invalid. Request a fresh enrollment.") from None
        cursor = conn.execute(
            """
            UPDATE voters
            SET session_version=session_version+1, face_encoding = pending_face_encoding,
                pending_face_encoding = NULL,
                face_updated_at = datetime('now'),
                verified_by = ?, verified_at = ?
            WHERE voter_id = ? AND deleted=0 AND pending_face_encoding IS NOT NULL
            """,
            (admin["voter_id"], datetime.now(timezone.utc).isoformat(), normalized_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="No pending face update for this voter.")
        conn.commit()
    return {"voter_id": normalized_id.upper(), "face_update_approved": True}


@app.get("/api/v1/election")
@limiter.limit("60/minute")
async def election_info(request: Request, response: Response):
    """Return the current contract's public display name."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    election_id = _current_election_id()
    with get_db() as conn:
        row = conn.execute(
            "SELECT name FROM election_metadata WHERE election_id = ?",
            (election_id,),
        ).fetchone()
    return {
        "election_id": election_id,
        "contract_address": _active_contract_address(),
        "name": row["name"] if row else "",
    }


@app.put("/api/v1/admin/election")
@limiter.limit("20/minute")
async def update_election_info(
    request: Request,
    payload: ElectionNameRequest,
    _admin: dict = Depends(require_admin),
):
    """Save the current election's display name for the voting portal."""
    election_id = _current_election_id()
    updated_at = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO election_metadata (election_id, name, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(election_id) DO UPDATE SET
                name = excluded.name,
                updated_at = excluded.updated_at
            """,
            (election_id, payload.name, updated_at),
        )
        conn.commit()
    return {"election_id": election_id, "name": payload.name}


@app.post("/api/v1/admin/election/activate")
@limiter.limit("5/minute")
async def activate_new_election(
    request: Request,
    payload: ElectionActivationRequest,
    _admin: dict = Depends(require_admin),
):
    """Make a newly deployed, empty voting contract the active election."""
    current_address = _active_contract_address()
    if not current_address:
        raise HTTPException(409, "There is no active election to replace.")
    if payload.contract_address.lower() == current_address.lower():
        raise HTTPException(409, "The new election must use a different contract.")

    _, current_contract = _get_blockchain_contract()
    if current_contract is None:
        raise HTTPException(503, "The current election contract is unavailable.")
    try:
        current_state = int(current_contract.functions.getElectionState().call())
    except Exception as exc:
        raise HTTPException(503, "The current election state is unavailable.") from exc
    if current_state != 2:
        raise HTTPException(409, "End the current election before creating a new one.")

    _validate_new_election_contract(
        payload.contract_address,
        payload.owner_address,
    )
    election_id = payload.contract_address.lower()
    updated_at = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE active_election SET contract_address = ? WHERE id = 1",
            (payload.contract_address,),
        )
        conn.execute(
            """
            INSERT INTO election_metadata (election_id, name, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(election_id) DO UPDATE SET
                name = excluded.name,
                updated_at = excluded.updated_at
            """,
            (election_id, payload.name, updated_at),
        )
        conn.commit()
    return {
        "election_id": election_id,
        "contract_address": payload.contract_address,
        "name": payload.name,
    }


@app.get("/api/v1/election/analytics")
@limiter.limit("60/minute")
def election_analytics(request: Request):
    """
    Public live election analytics:
    Returns election state, registered voter count, verified voter count,
    total votes cast, turnout rate, on-chain candidate results and leading candidate / winner.
    """
    election_id = _current_election_id()

    with get_db() as conn:
        meta_row = conn.execute(
            "SELECT name FROM election_metadata WHERE election_id = ?",
            (election_id,),
        ).fetchone()
        election_name = (
            meta_row["name"]
            if meta_row and meta_row["name"]
            else "General Student Council Election"
        )

        reg_row = conn.execute(
            "SELECT COUNT(*) AS c FROM voters WHERE deleted = 0"
        ).fetchone()
        total_registered = reg_row["c"] if reg_row else 0

        ver_row = conn.execute(
            "SELECT COUNT(*) AS c FROM voters WHERE deleted = 0 AND id_verified = 1"
        ).fetchone()
        total_verified = ver_row["c"] if ver_row else 0

        voted_row = conn.execute(
            """
            SELECT COUNT(DISTINCT voter_id) AS c
            FROM voting_credentials
            WHERE election_id = ? AND consumed_at IS NOT NULL
            """,
            (election_id,),
        ).fetchone()
        db_votes_cast = voted_row["c"] if voted_row else 0

    web3, contract = _get_blockchain_contract()
    if web3 is None or contract is None:
        raise HTTPException(503, "Blockchain audit data is unavailable. No ledger report was generated.")
    state_code = 0
    state_str = "NotStarted"
    chain_id = 1337
    latest_block = 0
    contract_address = _active_contract_address()
    candidates = []
    total_onchain_votes = 0

    if web3 is not None and contract is not None:
        try:
            chain_id = web3.eth.chain_id
            latest_block = max(0,web3.eth.block_number-settings.BLOCKCHAIN_CONFIRMATIONS+1)
            raw_state = contract.functions.getElectionState().call(block_identifier=latest_block)
            state_code = int(raw_state)
            state_map = {0: "NotStarted", 1: "Active", 2: "Ended"}
            state_str = state_map.get(state_code, "NotStarted")

            count = contract.functions.countCandidates().call(block_identifier=latest_block)
            for idx in range(1, count + 1):
                cand = contract.functions.getCandidate(idx).call(block_identifier=latest_block)
                cand_id = int(cand[0])
                c_name = str(cand[1])
                c_party = str(cand[2])
                c_votes = int(cand[3])
                total_onchain_votes += c_votes
                candidates.append({
                    "id": cand_id,
                    "name": c_name,
                    "party": c_party,
                    "votes": c_votes,
                    "percentage": 0.0,
                })
        except Exception as exc:
            log.warning("Could not read election state from blockchain")
            raise HTTPException(503, "Blockchain analytics are unavailable.") from exc

    total_votes = total_onchain_votes
    if total_votes > 0:
        for c in candidates:
            c["percentage"] = round((c["votes"] / total_votes) * 100, 2)

    turnout_pct = (
        round((total_votes / total_verified * 100), 2)
        if total_verified > 0
        else 0.0
    )

    sorted_candidates = sorted(candidates, key=lambda x: x["votes"], reverse=True)
    leading_candidate = (
        sorted_candidates[0] if (sorted_candidates and total_votes > 0) else None
    )
    winner = (
        sorted_candidates[0]
        if (sorted_candidates and state_code == 2 and total_votes > 0 and
            (len(sorted_candidates)==1 or sorted_candidates[0]["votes"]>sorted_candidates[1]["votes"]))
        else None
    )

    return {
        "election_id": election_id,
        "election_name": election_name,
        "state": state_str,
        "state_code": state_code,
        "blockchain_connected": bool(contract is not None),
        "contract_address": contract_address,
        "chain_id": chain_id,
        "latest_block_number": latest_block,
        "turnout": {
            "total_registered": total_registered,
            "total_verified": total_verified,
            "total_votes_cast": total_votes,
            "turnout_percentage": turnout_pct,
        },
        "candidates": candidates,
        "leading_candidate": leading_candidate,
        "winner": winner,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/admin/election/audit")
@limiter.limit("20/minute")
def election_audit_report(
    request: Request,
    _admin: dict = Depends(require_admin),
):
    """
    Administrative signed cryptographic audit report:
    Extracts all on-chain transactions, block hashes, credential digests,
    computes canonical SHA-256 Merkle/digest and digital signature.
    """
    election_id = _current_election_id()
    contract_address = _active_contract_address()
    relayer_address = settings.BLOCKCHAIN_RELAYER_ADDRESS or ""

    with get_db() as conn:
        meta_row = conn.execute(
            "SELECT name FROM election_metadata WHERE election_id = ?",
            (election_id,),
        ).fetchone()
        election_name = (
            meta_row["name"]
            if meta_row and meta_row["name"]
            else "General Student Council Election"
        )

        reg_row = conn.execute(
            "SELECT COUNT(*) AS c FROM voters WHERE deleted = 0"
        ).fetchone()
        total_registered = reg_row["c"] if reg_row else 0

        ver_row = conn.execute(
            "SELECT COUNT(*) AS c FROM voters WHERE deleted = 0 AND id_verified = 1"
        ).fetchone()
        total_verified = ver_row["c"] if ver_row else 0

    web3, contract = _get_blockchain_contract()
    if web3 is None or contract is None:
        raise HTTPException(503, "Blockchain audit data is unavailable. No ledger report was generated.")
    state_code = 0
    state_str = "NotStarted"
    chain_id = 1337
    candidates = []
    transaction_logs = []
    block_hash_cache: dict[int, str] = {}

    if web3 is not None and contract is not None:
        try:
            chain_id = web3.eth.chain_id
            latest_block = max(0,web3.eth.block_number-settings.BLOCKCHAIN_CONFIRMATIONS+1)
            raw_state = contract.functions.getElectionState().call(block_identifier=latest_block)
            state_code = int(raw_state)
            state_map = {0: "NotStarted", 1: "Active", 2: "Ended"}
            state_str = state_map.get(state_code, "NotStarted")

            count = contract.functions.countCandidates().call(block_identifier=latest_block)
            for idx in range(1, count + 1):
                cand = contract.functions.getCandidate(idx).call(block_identifier=latest_block)
                candidates.append({
                    "id": int(cand[0]),
                    "name": str(cand[1]),
                    "party": str(cand[2]),
                    "votes": int(cand[3]),
                })

            events = contract.events.VoteCast.get_logs(from_block=0, to_block=latest_block)
            for idx, evt in enumerate(events, start=1):
                tx_h = Web3.to_hex(evt.transactionHash)
                blk_num = evt.blockNumber
                if blk_num not in block_hash_cache:
                    try:
                        blk = web3.eth.get_block(blk_num)
                        block_hash_cache[blk_num] = Web3.to_hex(blk.hash)
                    except Exception:
                        raise HTTPException(503, "Blockchain block data is unavailable.")

                blk_h = block_hash_cache[blk_num]
                if Web3.to_hex(evt.blockHash) != blk_h:
                    raise HTTPException(503, "Blockchain changed during audit. Try again.")
                cand_id = int(evt.args.candidateId)
                cred_digest = Web3.to_hex(evt.args.credential)
                ts = int(evt.args.timestamp)
                iso_time = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

                transaction_logs.append({
                    "index": idx,
                    "tx_hash": tx_h,
                    "block_number": blk_num,
                    "block_hash": blk_h,
                    "candidate_id": cand_id,
                    "credential_hash": cred_digest,
                    "timestamp": iso_time,
                })
        except Exception as exc:
            log.warning("Could not read complete blockchain audit")
            raise HTTPException(503, "Complete blockchain audit data is unavailable.") from exc

    total_votes = sum(c["votes"] for c in candidates) if candidates else len(transaction_logs)
    for c in candidates:
        c["percentage"] = (
            round((c["votes"] / total_votes * 100), 2) if total_votes > 0 else 0.0
        )

    sorted_candidates = sorted(candidates, key=lambda x: x["votes"], reverse=True)
    winner = sorted_candidates[0] if (sorted_candidates and state_code==2 and total_votes>0 and
        (len(sorted_candidates)==1 or sorted_candidates[0]["votes"]>sorted_candidates[1]["votes"])) else None
    turnout_pct = (
        round((total_votes / total_verified * 100), 2)
        if total_verified > 0
        else 0.0
    )

    canonical = json.dumps({"schema":"ACADEMIC_AUDIT_V2","contract_address":contract_address,
        "chain_id":chain_id,"state":state_str,"election_name":election_name,
        "total_registered":total_registered,"total_verified":total_verified,
        "total_votes":total_votes,"candidates":candidates,"transactions":transaction_logs},
        sort_keys=True,separators=(",",":"),ensure_ascii=True)
    audit_digest = "0x" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    signer_address = relayer_address
    signature_hex = ""
    signature_algo = "ECDSA-secp256k1"
    private_key = settings.BLOCKCHAIN_RELAYER_PRIVATE_KEY

    try:
        if private_key and private_key.startswith("0x") and len(private_key) == 66:
            from eth_account import Account
            from eth_account.messages import encode_defunct

            account = Account.from_key(private_key)
            signer_address = account.address
            signable_msg = encode_defunct(text=audit_digest)
            signed = account.sign_message(signable_msg)
            signature_hex = signed.signature.hex()
    except Exception as sign_exc:
        log.warning("ECDSA audit signing unavailable")

    if not signature_hex:
        signature_algo = "HMAC-SHA256"
        signature_hex = (
            "0x"
            + hmac.new(
                SECRET_KEY.encode(), audit_digest.encode(), hashlib.sha256
            ).hexdigest()
        )
        signer_address = signer_address or "ELECTION_AUTHORITY_SERVER"

    return {
        "election_id": election_id,
        "election_name": election_name,
        "state": state_str,
        "state_code": state_code,
        "contract_address": contract_address,
        "chain_id": chain_id,
        "relayer_address": relayer_address,
        "signer_address": signer_address,
        "audit_digest": audit_digest,
        "canonical_payload": canonical,
        "signature": signature_hex,
        "signature_algorithm": signature_algo,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "turnout_stats": {
            "total_registered": total_registered,
            "total_verified": total_verified,
            "total_votes_cast": total_votes,
            "turnout_percentage": turnout_pct,
        },
        "candidate_results": candidates,
        "winner": winner,
        "transaction_logs": transaction_logs,
    }


@app.delete("/api/v1/admin/voters/{voter_id}")
@limiter.limit("30/minute")
async def delete_voter(
    request: Request,
    voter_id: str,
    _admin: dict = Depends(require_admin),
):
    """Remove a voter and any server-side voting credentials issued to them."""
    normalized_id = voter_id.strip().lower()
    if not normalized_id:
        raise HTTPException(status_code=400, detail="Voter ID is required.")

    with get_db() as conn:
        voter = conn.execute(
            "SELECT voter_id FROM voters WHERE voter_id = ?",
            (normalized_id,),
        ).fetchone()
        if voter is None:
            raise HTTPException(status_code=404, detail="Voter not found.")

        conn.execute(
            "INSERT OR IGNORE INTO deleted_voters (voter_id) VALUES (?)",
            (normalized_id,),
        )
        conn.execute("UPDATE voters SET deleted=1, face_encoding='', pending_face_encoding=NULL WHERE voter_id=?", (normalized_id,))
        conn.commit()

    return {"voter_id": normalized_id.upper(), "deleted": True}


@app.get("/api/v1/voter/eligibility")
@limiter.limit("30/minute")
async def voter_eligibility(request: Request, current_user: dict = Depends(require_voter)):
    """Return the logged-in voter's eligibility details from SQLite."""
    token = request.cookies.get(_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    session = decode_jwt(token)
    voter_id = session.get("voter_id", "").strip().lower()
    election_id = _current_election_id()
    with get_db() as conn:
        row = conn.execute(
            """SELECT voter_id, student_name, branch, class_name, batch, id_verified,
                      (SELECT tx_hash FROM voting_credentials vc
                       WHERE vc.voter_id = voters.voter_id AND vc.election_id = ?
                       ORDER BY vc.issued_at DESC LIMIT 1) AS tx_hash,
                      (EXISTS(SELECT 1 FROM voting_credentials vc
                             WHERE vc.voter_id = voters.voter_id AND vc.election_id = ?
                               AND vc.consumed_at IS NOT NULL)
                       OR voters.last_voted_election_id = ?) AS has_voted
               FROM voters WHERE voter_id = ?""",
            (election_id, election_id, election_id, voter_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Voter is not registered.")
    result = {
        "voter_id": row["voter_id"].upper(),
        "student_name": row["student_name"],
        "branch": row["branch"],
        "class_name": row["class_name"],
        "batch": row["batch"],
        "eligible": bool(row["id_verified"]),
        "voted": bool(row["has_voted"]),
        "tx_hash": row["tx_hash"],
        "credential_ready": False,
    }
    vote_status = voting_service().status(voter_id)
    result["vote_status"] = vote_status["status"]
    raw_credential = request.cookies.get(_CREDENTIAL_COOKIE)
    if raw_credential and result["eligible"] and not result["voted"]:
        try:
            supplied_hash = _credential_hash_from_cookie(raw_credential)
        except HTTPException:
            supplied_hash = ""
        if supplied_hash:
            with get_db() as conn:
                result["credential_ready"] = conn.execute(
                    """
                    SELECT 1 FROM voting_credentials
                    WHERE credential_hash = ? AND election_id = ?
                      AND consumed_at IS NULL AND revoked_at IS NULL AND voter_id=? AND expires_at>?
                    """,
                    (supplied_hash, election_id, voter_id, datetime.now(timezone.utc).isoformat()),
                ).fetchone() is not None
    if vote_status["status"] in ("PENDING", "SUBMITTED", "CONFIRMED"):
        result["credential_ready"] = False
    if result["eligible"] and not result["voted"] and not result["credential_ready"]:
        credential = issue_voting_credential(voter_id)
        if credential:
            result["credential_ready"] = True
            response = JSONResponse(result)
            response.set_cookie(
                key=_CREDENTIAL_COOKIE, value=credential, httponly=True,
                secure=settings.COOKIE_SECURE, samesite=settings.COOKIE_SAMESITE,
                max_age=_CREDENTIAL_MAX_AGE, path="/",
            )
            return response
    response = JSONResponse(result)
    if result["voted"]:
        response.delete_cookie(
            key=_CREDENTIAL_COOKIE,
            path="/",
            samesite=settings.COOKIE_SAMESITE,
            secure=settings.COOKIE_SECURE,
            httponly=True,
        )
    elif raw_credential and not result["credential_ready"]:
        response.delete_cookie(
            key=_CREDENTIAL_COOKIE,
            path="/",
            samesite=settings.COOKIE_SAMESITE,
            secure=settings.COOKIE_SECURE,
            httponly=True,
        )
    return response


@app.get("/api/v1/liveness/challenge")
@limiter.limit("20/minute")
async def liveness_challenge(request: Request, voter_id: str, guided: bool = False):
    """Preflight before asking the voter to record a single-use live challenge."""
    normalized_voter_id = voter_id.strip().lower()
    if not normalized_voter_id or len(normalized_voter_id) > 100:
        raise HTTPException(status_code=400, detail="Enter a valid Voter ID first.")

    if not _cv_slots.acquire(blocking=False):
        raise HTTPException(503, "Face service is busy. Please try again shortly.", headers={"Retry-After": "2"})
    _cv_slots.release()
    with get_db() as conn:
        voter = conn.execute("SELECT face_encoding,pending_face_encoding,face_updated_at,id_verified FROM voters WHERE voter_id=? AND deleted=0 AND role='user'", (normalized_voter_id,)).fetchone()
    if voter is None:
        raise HTTPException(404, "Voter ID not found. Register this voter first.")
    if not voter["face_encoding"]:
        raise HTTPException(409, "Complete face registration before starting the live check.")
    if not voter["id_verified"]:
        raise HTTPException(403, "Administrator approval is required before login.")

    try:
        profile_model, _ = parse_profile(voter["face_encoding"])
    except (ValueError, TypeError):
        raise HTTPException(409, "The active face profile is invalid. Ask an administrator to review your enrollment.") from None
    result = active_liveness.issue(get_db, normalized_voter_id, fast=profile_model == SFACE_MODEL and not guided)
    result.update(face_engine_version=3, profile_model=profile_model, face_update_pending=bool(voter["pending_face_encoding"]), face_updated_at=voter["face_updated_at"])
    return result


@app.post("/api/v1/voter/cast")
@limiter.limit("5/minute")
async def cast_vote(
    request: Request,
    payload: CastVoteRequest,
    current_user: dict = Depends(require_voter),
):
    raw = request.cookies.get(_CREDENTIAL_COOKIE)
    if not raw:
        raise HTTPException(401, "Voting credential is missing. Refresh your session.")
    result = await run_in_threadpool(voting_service().cast, current_user["voter_id"],payload.candidate_id,raw)
    response = JSONResponse(result, status_code=200 if result["success"] else 422 if result["status"]=="FAILED" else 202)
    if result["success"]:
        response.delete_cookie(_CREDENTIAL_COOKIE,path="/")
    return response


@app.get("/api/v1/voter/vote-status")
@limiter.limit("60/minute")
async def vote_status(request: Request, current_user: dict = Depends(require_voter)):
    # Reconciliation also runs periodically and after restart.
    return voting_service().status(current_user["voter_id"])


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

    if role != "user":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Face enrollment is only for voter accounts.",
        )

    profile = await run_cv(get_enrollment_profile, payload.images_base64 or [payload.image_base64])

    encoding_json = json.dumps(profile)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO voters (voter_id, role, face_encoding, face_updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(voter_id) DO UPDATE SET
                role = excluded.role,
                face_encoding = excluded.face_encoding,
                pending_face_encoding = NULL,
                face_updated_at = datetime('now'),
                session_version = voters.session_version+1
            """,
            (voter_id, role, encoding_json),
        )
        conn.commit()

    log.info("[ENROLL] voter='%s' role='%s' enrolled/updated by admin.", voter_id, role)
    return {"message": f"Voter '{voter_id}' enrolled successfully.", "role": role}

@app.post("/api/v1/register-user", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def register_user(
    request: Request,
    payload: EnrollRequest
):
    """
    Self-registration endpoint using ID card details and face.
    Rate limited: 10 requests/minute per IP.
    """
    voter_id = payload.voter_id.strip().lower()
    role = "user" # Always user for self-registration

    profile = await run_cv(get_enrollment_profile, payload.images_base64 or [payload.image_base64])

    encoding_json = json.dumps(profile)

    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT role, face_encoding, deleted FROM voters WHERE voter_id = ?",
            (voter_id,),
        ).fetchone()
        if existing and existing["deleted"]:
            conn.rollback()
            raise HTTPException(status_code=403, detail="This voter account has been deleted.")
        if existing and existing["role"] != "user":
            conn.rollback()
            raise HTTPException(status_code=409, detail="This ID belongs to a non-voter account.")

        if existing and existing["face_encoding"]:
            # Never replace an active login profile through public self-service.
            # Queue the new embedding for an admin to compare with the physical ID.
            conn.execute(
                "UPDATE voters SET pending_face_encoding = ? WHERE voter_id = ?",
                (encoding_json, voter_id),
            )
            conn.commit()
            log.info("[REGISTER] voter='%s' submitted a face update for admin review.", voter_id)
            return {
                "message": "Replacement face image submitted for admin review.",
                "role": role,
                "pending_review": True,
            }

        conn.execute(
            """
            INSERT INTO voters (voter_id, role, face_encoding, name, usn, branch, validity, dob, face_updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(voter_id) DO UPDATE SET
                face_encoding = excluded.face_encoding,
                name = excluded.name,
                face_updated_at = datetime('now'),
                usn = excluded.usn,
                branch = excluded.branch,
                validity = excluded.validity,
                dob = excluded.dob,
                id_verified = 0,
                session_version = voters.session_version+1
            """,
            (voter_id, role, encoding_json, payload.name, payload.usn, payload.branch, payload.validity, payload.dob),
        )
        conn.commit()

    log.info("[REGISTER] voter='%s' self-registered.", voter_id)
    return {"message": f"Voter '{voter_id}' registered successfully.", "role": role, "pending_review": False}
