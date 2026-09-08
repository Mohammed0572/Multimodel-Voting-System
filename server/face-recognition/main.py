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
import secrets
import pickle
import sqlite3
import logging
import re
import asyncio
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
from pydantic import BaseModel, field_validator
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

_cv_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="face-cv")

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

DB_PATH = settings.FACE_DB_PATH or str(Path(__file__).resolve().with_name("face_voter_db.sqlite"))
CSBS_SEED_PATH = str(Path(__file__).resolve().with_name("csbs_students.json"))


@contextmanager
def get_db():
    if DB_PATH != ":memory:":
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
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
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_admins_active ON admins(is_active);")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS voting_credentials (
                credential_hash TEXT PRIMARY KEY NOT NULL,
                voter_id TEXT NOT NULL,
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
        if os.getenv("RESET_VOTING_CREDENTIALS_ON_START", "false").lower() == "true":
            cursor.execute("DELETE FROM voting_credentials")
            log.info("Demo mode: reset voting credentials for the new local election.")
        if os.path.exists(CSBS_SEED_PATH):
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


def issue_voting_credential(voter_id: str) -> Optional[str]:
    raw_credential = secrets.token_bytes(32)
    credential_hash = hashlib.sha256(raw_credential).hexdigest()

    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(
        minutes=settings.VOTING_CREDENTIAL_TTL_MINUTES
    )

    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")

        voter = conn.execute(
            """
            SELECT voter_id, id_verified, deleted
            FROM voters
            WHERE voter_id = ?
            """,
            (voter_id,),
        ).fetchone()

        if voter is None:
            conn.rollback()
            raise HTTPException(
                status_code=404,
                detail="Voter is not registered.",
            )

        if voter["deleted"]:
            conn.rollback()
            raise HTTPException(
                status_code=403,
                detail="Voter account has been deleted.",
            )

        if not voter["id_verified"]:
            conn.rollback()
            raise HTTPException(
                status_code=403,
                detail="Voter identity has not been approved.",
            )

        existing = conn.execute(
            """
            SELECT consumed_at, expires_at
            FROM voting_credentials
            WHERE voter_id = ?
                            AND consumed_at IS NULL
                            AND revoked_at IS NULL
            ORDER BY issued_at DESC
            LIMIT 1
            """,
            (voter_id,),
        ).fetchone()

        if existing:
            try:
                exp = datetime.fromisoformat(existing["expires_at"])
                if exp > datetime.now(timezone.utc):
                    conn.execute(
                        """
                        UPDATE voting_credentials
                        SET revoked_at = ?
                        WHERE voter_id = ?
                          AND consumed_at IS NULL
                          AND revoked_at IS NULL
                        """,
                        (datetime.now(timezone.utc).isoformat(), voter_id),
                    )
            except HTTPException:
                raise
            except Exception:
                pass

        conn.execute(
            """
            INSERT INTO voting_credentials (
                credential_hash,
                voter_id,
                issued_at,
                expires_at,
                consumed_at,
                revoked_at,
                tx_hash
            )
            VALUES (?, ?, ?, ?, NULL, NULL, NULL)
            """,
            (
                credential_hash,
                voter_id,
                issued_at.isoformat(),
                expires_at.isoformat(),
            ),
        )

        conn.commit()

    return raw_credential.hex()


def _credential_hash_from_cookie(credential: str) -> str:
    try:
        raw = bytes.fromhex(credential)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid voting credential.") from exc
    if len(raw) != 32:
        raise HTTPException(status_code=401, detail="Invalid voting credential.")
    return hashlib.sha256(raw).hexdigest()


def _relayer_configuration() -> tuple[str, str]:
    contract_address = settings.BLOCKCHAIN_CONTRACT_ADDRESS
    relayer_address = settings.BLOCKCHAIN_RELAYER_ADDRESS
    private_key = settings.BLOCKCHAIN_RELAYER_PRIVATE_KEY

    if not contract_address:
        raise HTTPException(
            status_code=503,
            detail="Blockchain contract address is not configured.",
        )

    if not relayer_address:
        raise HTTPException(
            status_code=503,
            detail="Blockchain relayer address is not configured.",
        )

    if not private_key:
        raise HTTPException(
            status_code=503,
            detail="Blockchain relayer private key is not configured.",
        )

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

    if not private_key.startswith("0x") or len(private_key) != 66:
        raise HTTPException(
            status_code=503,
            detail="Blockchain relayer private key is invalid.",
        )

    return contract_address, private_key


def relay_vote(candidate_id: int, credential: bytes) -> str:
    contract_address, private_key = _relayer_configuration()

    web3 = Web3(Web3.HTTPProvider(settings.BLOCKCHAIN_RPC_URL))

    if not web3.is_connected():
        raise HTTPException(
            status_code=503,
            detail="Blockchain node is unavailable.",
        )

    try:
        checksum_address = Web3.to_checksum_address(contract_address)
        account = web3.eth.account.from_key(private_key)
    except Exception as exc:
        log.exception("Invalid blockchain configuration")
        raise HTTPException(
            status_code=503,
            detail="Blockchain configuration is invalid.",
        ) from exc

    if account.address.lower() != settings.BLOCKCHAIN_RELAYER_ADDRESS.lower():
        raise HTTPException(
            status_code=503,
            detail="Configured private key does not match relayer address.",
        )

    abi = [
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
        }
    ]

    contract = web3.eth.contract(
        address=checksum_address,
        abi=abi,
    )

    credential_digest = Web3.keccak(credential)

    try:
        nonce = web3.eth.get_transaction_count(
            account.address,
            "pending",
        )

        gas_estimate = contract.functions.vote(
            candidate_id,
            credential_digest,
        ).estimate_gas({
            "from": account.address,
        })

        tx_data = {
            "from": account.address,
            "nonce": nonce,
            "chainId": web3.eth.chain_id,
            "gas": int(gas_estimate * 1.20),
        }
        try:
            priority_fee = web3.eth.max_priority_fee
            tx_data["maxPriorityFeePerGas"] = priority_fee
            tx_data["maxFeePerGas"] = priority_fee * 2 + web3.eth.gas_price
        except Exception:
            tx_data["gasPrice"] = web3.eth.gas_price

        transaction = contract.functions.vote(
            candidate_id,
            credential_digest,
        ).build_transaction(tx_data)

        signed = account.sign_transaction(transaction)

        raw_transaction = getattr(
            signed,
            "raw_transaction",
            getattr(signed, "rawTransaction", None),
        )

        tx_hash = web3.eth.send_raw_transaction(raw_transaction)

        receipt = web3.eth.wait_for_transaction_receipt(
            tx_hash,
            timeout=120,
        )

    except Exception as exc:
        log.exception("Vote relay failed")
        raise HTTPException(
            status_code=502,
            detail="Blockchain transaction could not be submitted.",
        ) from exc

    if receipt.get("status") != 1:
        raise HTTPException(
            status_code=502,
            detail="Blockchain transaction failed.",
        )

    return tx_hash.hex()


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


def validate_face_image_quality(image: np.ndarray) -> None:
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

    if sharpness < 35:
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


def get_face_details(
    image: np.ndarray,
    need_encoding: bool = True,
) -> Optional[tuple[Optional[np.ndarray], dict]]:
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    height, width = rgb.shape[:2]
    if height < 80 or width < 80:
        return None

    detection_scale = 0.25 if min(height, width) >= 320 else 1.0
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

    landmarks = face_recognition.face_landmarks(rgb, scaled_locations)
    if not landmarks:
        return None

    encoding: Optional[np.ndarray] = None
    if need_encoding:
        encodings = face_recognition.face_encodings(rgb, scaled_locations)
        if not encodings:
            return None
        encoding = validate_embedding(encodings[0])

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
    return float((A + B) / (2.0 * C))


def compare_faces(
    known_encoding: np.ndarray,
    test_encoding: np.ndarray,
    tolerance: float = MATCH_TOLERANCE,
) -> tuple[bool, float]:
    known = validate_embedding(known_encoding)
    test = validate_embedding(test_encoding)
    distance = float(face_recognition.face_distance([known], test)[0])
    return distance <= tolerance, distance


_LIVENESS_CHALLENGES: dict[str, dict] = {}


def create_liveness_challenge() -> str:
    return secrets.choice([
        "blink",
        "turn_left",
        "turn_right",
        "smile",
    ])


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
    allow_origins=settings.frontend_origins,
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
    name: Optional[str] = None
    usn: Optional[str] = None
    branch: Optional[str] = None
    validity: Optional[str] = None
    dob: Optional[str] = None
    # token is now delivered via HttpOnly cookie, NOT in the response body
    # distance REMOVED — was leaking face match proximity to client


class EnrollRequest(BaseModel):
    voter_id: str
    role: str = "user"
    image_base64: str = ""
    images_base64: Optional[list[str]] = None
    name: Optional[str] = None
    usn: Optional[str] = None
    branch: Optional[str] = None
    validity: Optional[str] = None
    dob: Optional[str] = None

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
        if v is not None and not v:
            raise ValueError("images_base64 must not be empty when provided.")
        return v


class ExtractIDRequest(BaseModel):
    image_base64: str


class EligibilityVerificationRequest(BaseModel):
    verified: bool


class CastVoteRequest(BaseModel):
    candidate_id: int



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

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, usn, branch, validity, dob FROM voters WHERE voter_id = ?",
            (voter_id.lower(),),
        )
        row = cursor.fetchone()

    new_token = create_jwt(voter_id, role)

    res = JSONResponse(
        content={
            "role": role,
            "voter_id": voter_id,
            "name": row["name"] if row else None,
            "usn": row["usn"] if row else None,
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
        samesite="lax",
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
    reader = get_ocr_reader()
    if reader is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OCR service is unavailable (easyocr is not installed or initialized).",
        )

    img = decode_base64_image(body.image_base64)
    # easyocr reads BGR/RGB directly
    results = reader.readtext(img, detail=0)

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

    res = JSONResponse(
        content={"role": "admin", "voter_id": body.username},
        status_code=status.HTTP_200_OK,
    )
    res.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
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
    128D face encoding, with EAR-based blink liveness detection.

    Rate limited: 5 requests/minute per IP.
    """
    voter_id = payload.voter_id.strip().lower()

    if len(payload.images_base64) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Liveness detection requires a sequence of images (at least 2).",
        )

    def process_frame(image_base64: str):
        try:
            image = decode_base64_image(image_base64)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid image in sequence: {exc}",
            ) from exc
        return image, get_face_details(image, need_encoding=False)

    loop = asyncio.get_running_loop()
    processed_frames = await asyncio.gather(
        *[
            loop.run_in_executor(_cv_executor, process_frame, image_base64)
            for image_base64 in payload.images_base64
        ]
    )
    usable_frames = [
        (index, image, details)
        for index, (image, details) in enumerate(processed_frames)
        if details is not None
    ]

    if not usable_frames:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No faces detected in the provided image sequence.",
        )

    encoding_indexes = {usable_frames[0][0], usable_frames[-1][0]}
    encoding_jobs = [
        loop.run_in_executor(_cv_executor, get_face_details, image, True)
        for index, image, _ in usable_frames
        if index in encoding_indexes
    ]
    encoded_frames = [
        details
        for details in await asyncio.gather(*encoding_jobs)
        if details is not None and details[0] is not None
    ]

    if not encoded_frames:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not get a clear face reading. Please try again.",
        )

    base_embedding = encoded_frames[0][0]

    # Consistency check + EAR collection across frames
    ears = []
    for emb, landmarks in encoded_frames:
        match, _ = compare_faces(base_embedding, emb, tolerance=0.4)
        if not match:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Multiple different faces or inconsistent face detected across frames.",
            )

    for _, _, (_, landmarks) in usable_frames:
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

    # Fetch stored encoding and registration details
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT role, face_encoding, name, usn, branch, validity, dob, id_verified FROM voters WHERE voter_id = ?",
            (voter_id,),
        )
        row = cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Voter ID not found. Please register first.",
        )

    role: str = row["role"]
    profile_name = row["name"]
    profile_usn = row["usn"]
    profile_branch = row["branch"]
    profile_validity = row["validity"]
    profile_dob = row["dob"]
    is_eligible = bool(row["id_verified"])

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
    voting_credential = issue_voting_credential(voter_id) if is_eligible and role == "user" else None

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
    )
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=_COOKIE_MAX_AGE,
        path="/",
    )
    if voting_credential:
        response.set_cookie(
            key=_CREDENTIAL_COOKIE,
            value=voting_credential,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite="lax",
            max_age=_CREDENTIAL_MAX_AGE,
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
    voter_id = payload.get("voter_id")
    if not voter_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session.",
        )

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, usn, branch, validity, dob FROM voters WHERE voter_id = ?",
            (str(voter_id).lower(),),
        )
        row = cursor.fetchone()

    return {
        "voter_id": voter_id,
        "role": payload.get("role"),
        "name": row["name"] if row else None,
        "usn": row["usn"] if row else None,
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
    voter_id: Optional[str] = None
    token = request.cookies.get(_COOKIE_NAME)
    if token:
        try:
            voter_id = str(decode_jwt(token).get("voter_id", "")).strip().lower()
        except HTTPException:
            pass

    raw_credential = request.cookies.get(_CREDENTIAL_COOKIE)
    credential_hash: Optional[str] = None
    if raw_credential:
        try:
            credential_hash = _credential_hash_from_cookie(raw_credential)
        except HTTPException:
            pass

    if voter_id or credential_hash:
        with get_db() as conn:
            if credential_hash:
                conn.execute(
                    """
                    UPDATE voting_credentials
                    SET revoked_at = ?
                    WHERE credential_hash = ?
                      AND consumed_at IS NULL
                      AND revoked_at IS NULL
                    """,
                    (datetime.now(timezone.utc).isoformat(), credential_hash),
                )
            elif voter_id:
                conn.execute(
                    """
                    UPDATE voting_credentials
                    SET revoked_at = ?
                    WHERE credential_hash = (
                        SELECT credential_hash
                        FROM voting_credentials
                        WHERE voter_id = ?
                          AND consumed_at IS NULL
                          AND revoked_at IS NULL
                        ORDER BY issued_at DESC
                        LIMIT 1
                    )
                    """,
                    (datetime.now(timezone.utc).isoformat(), voter_id),
                )
            conn.commit()

    response = JSONResponse(content={"message": "Logged out successfully."})
    response.delete_cookie(key=_COOKIE_NAME, path="/", samesite="lax")
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
async def admin_voters(request: Request, _admin: dict = Depends(require_admin)):
    """Return the CSBS voter registry from SQLite for the admin dashboard."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT voter_id, role
                 , student_name, branch, class_name, batch, id_verified, verified_by, verified_at
            FROM voters
            WHERE voter_id LIKE '1kg23cb%'
               OR voter_id = '1kg24cb400'
            ORDER BY voter_id
            """
        ).fetchall()

    students = []
    for row in rows:
        voter_id = row["voter_id"].upper()
        students.append({
            "usn": voter_id,
            "branch": "CB",
            "className": "CSBS",
            "batch": "2024" if voter_id.startswith("1KG24") else "2023",
            "number": 60 if voter_id == "1KG24CB400" else int(voter_id[-3:]),
            "role": row["role"],
            "studentName": row["student_name"],
            "idVerified": bool(row["id_verified"]),
            "verifiedBy": row["verified_by"],
            "verifiedAt": row["verified_at"],
        })
    return {"students": students, "total": len(students)}


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
            SET id_verified = ?, verified_by = ?, verified_at = ?
            WHERE voter_id = ? AND (voter_id LIKE '1kg23cb%' OR voter_id = '1kg24cb400')
            """,
            (int(payload.verified), admin["voter_id"], datetime.now(timezone.utc).isoformat(), normalized_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="CSBS voter not found.")
        conn.commit()
    return {"voter_id": normalized_id.upper(), "id_verified": payload.verified}


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
        conn.execute("DELETE FROM voting_credentials WHERE voter_id = ?", (normalized_id,))
        conn.execute("DELETE FROM voters WHERE voter_id = ?", (normalized_id,))
        conn.commit()

    return {"voter_id": normalized_id.upper(), "deleted": True}


@app.get("/api/v1/voter/eligibility")
@limiter.limit("30/minute")
async def voter_eligibility(request: Request):
    """Return the logged-in voter's eligibility details from SQLite."""
    token = request.cookies.get(_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    session = decode_jwt(token)
    voter_id = session.get("voter_id", "").strip().lower()
    with get_db() as conn:
        row = conn.execute(
            """SELECT voter_id, student_name, branch, class_name, batch, id_verified,
                      (SELECT tx_hash FROM voting_credentials vc WHERE vc.voter_id = voters.voter_id ORDER BY vc.issued_at DESC LIMIT 1) AS tx_hash,
                      COALESCE((SELECT consumed_at IS NOT NULL FROM voting_credentials vc WHERE vc.voter_id = voters.voter_id ORDER BY vc.issued_at DESC LIMIT 1), 0) AS has_voted
               FROM voters WHERE voter_id = ?""",
            (voter_id,),
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
        "credential_ready": bool(request.cookies.get(_CREDENTIAL_COOKIE)),
    }
    response = JSONResponse(result)
    if result["eligible"] and not result["voted"] and not request.cookies.get(_CREDENTIAL_COOKIE):
        credential = issue_voting_credential(voter_id)
        if credential:
            response.set_cookie(
                key=_CREDENTIAL_COOKIE, value=credential, httponly=True,
                secure=settings.COOKIE_SECURE, samesite="lax",
                max_age=_CREDENTIAL_MAX_AGE, path="/",
            )
            result["credential_ready"] = True
    return response


@app.get("/api/v1/liveness/challenge")
@limiter.limit("20/minute")
async def liveness_challenge(request: Request):
    """Return a single-use random liveness challenge expiring in 30 seconds."""
    challenge = create_liveness_challenge()
    challenge_id = secrets.token_hex(16)
    _LIVENESS_CHALLENGES[challenge_id] = {
        "challenge": challenge,
        "created_at": datetime.now(timezone.utc),
        "expires_in": 30,
    }
    return {
        "challenge": challenge,
        "challenge_id": challenge_id,
        "expires_in": 30,
    }


@app.post("/api/v1/voter/cast")
@limiter.limit("5/minute")
async def cast_vote(
    request: Request,
    payload: CastVoteRequest,
    current_user: dict = Depends(require_voter),
):
    raw_credential = request.cookies.get(_CREDENTIAL_COOKIE)

    if not raw_credential:
        raise HTTPException(
            status_code=401,
            detail="Voting credential is missing or expired.",
        )

    try:
        credential = bytes.fromhex(raw_credential)
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail="Voting credential is invalid.",
        )

    if len(credential) != 32:
        raise HTTPException(
            status_code=401,
            detail="Voting credential is invalid.",
        )

    credential_hash = hashlib.sha256(credential).hexdigest()
    voter_id = current_user.get("voter_id", "").strip().lower()

    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        credential_row = conn.execute(
            """
            SELECT credential_hash, voter_id, expires_at,
                     consumed_at, revoked_at, tx_hash
            FROM voting_credentials
            WHERE credential_hash = ?
            """,
            (credential_hash,),
        ).fetchone()

        if credential_row is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid voting credential.",
            )

        if credential_row["voter_id"].lower() != voter_id:
            raise HTTPException(
                status_code=403,
                detail="Credential does not belong to this voter.",
            )

        if credential_row["consumed_at"] is not None:
            raise HTTPException(
                status_code=409,
                detail="This voting credential has already been used.",
            )

        if credential_row["revoked_at"] is not None:
            raise HTTPException(
                status_code=401,
                detail="Voting credential has been revoked.",
            )

        expires_at = datetime.fromisoformat(credential_row["expires_at"])
        if expires_at <= datetime.now(timezone.utc):
            raise HTTPException(
                status_code=401,
                detail="Voting credential has expired.",
            )

        voter = conn.execute(
            """
            SELECT id_verified, deleted, voted
            FROM voters
            WHERE voter_id = ?
            """,
            (voter_id,),
        ).fetchone()

        if voter is None or voter["deleted"] or not voter["id_verified"]:
            raise HTTPException(
                status_code=403,
                detail="Voter is not eligible.",
            )

        if voter["voted"]:
            raise HTTPException(
                status_code=409,
                detail="This voter has already voted.",
            )

        transaction_hash = relay_vote(payload.candidate_id, credential)

        conn.execute("BEGIN IMMEDIATE")

        updated = conn.execute(
            """
            UPDATE voting_credentials
            SET consumed_at = ?,
                tx_hash = ?
            WHERE credential_hash = ?
              AND consumed_at IS NULL
                            AND revoked_at IS NULL
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                transaction_hash,
                credential_hash,
            ),
        )

        if updated.rowcount != 1:
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail="Credential was consumed by another request.",
            )

        conn.execute(
            """
            UPDATE voters
            SET voted = 1
            WHERE voter_id = ?
              AND voted = 0
            """,
            (voter_id,),
        )

        conn.commit()

    response = JSONResponse({
        "success": True,
        "transaction_hash": transaction_hash,
        "tx_hash": transaction_hash,
        "credential_consumed": True,
    })

    response.delete_cookie(
        key=_CREDENTIAL_COOKIE,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        path="/",
    )

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

    embedding = get_enrollment_embedding(payload.images_base64 or [payload.image_base64])

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

    embedding = get_enrollment_embedding(payload.images_base64 or [payload.image_base64])

    encoding_json = json.dumps(embedding.tolist())

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO voters (voter_id, role, face_encoding, name, usn, branch, validity, dob)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(voter_id) DO UPDATE SET
                face_encoding = excluded.face_encoding,
                name = excluded.name,
                usn = excluded.usn,
                branch = excluded.branch,
                validity = excluded.validity,
                dob = excluded.dob
            """,
            (voter_id, role, encoding_json, payload.name, payload.usn, payload.branch, payload.validity, payload.dob),
        )
        conn.commit()

    log.info("[REGISTER] voter='%s' self-registered.", voter_id)
    return {"message": f"Voter '{voter_id}' registered successfully.", "role": role}
