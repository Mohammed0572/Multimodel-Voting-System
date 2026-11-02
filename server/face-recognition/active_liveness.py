"""Server-issued temporal challenges. These are presentation-attack heuristics,
not a trusted camera attestation or a certified anti-spoofing model.
"""
import hashlib
import secrets
import time

import numpy as np
from fastapi import HTTPException


def migrate(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS liveness_challenges (
            id TEXT PRIMARY KEY, voter_id TEXT NOT NULL, action TEXT NOT NULL,
            created_at REAL NOT NULL, expires_at REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS liveness_frames (
            fingerprint TEXT PRIMARY KEY, expires_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS revoked_sessions (
            jti TEXT PRIMARY KEY, expires_at REAL NOT NULL
        );
    """)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(liveness_challenges)")}
    if "min_seconds" not in columns:
        conn.execute("ALTER TABLE liveness_challenges ADD COLUMN min_seconds REAL NOT NULL DEFAULT 3")
    if "frame_count" not in columns:
        conn.execute("ALTER TABLE liveness_challenges ADD COLUMN frame_count INTEGER NOT NULL DEFAULT 0")


def issue(db, voter_id, fast=False):
    # Head movement is temporarily disabled. Keep the one-use challenge,
    # identity checks and server-validated bilateral close/reopen sequence.
    action = "blink_once"
    identifier = secrets.token_urlsafe(32)
    current = time.time()
    with db() as conn:
        conn.execute("DELETE FROM liveness_challenges WHERE expires_at<?",(current,))
        conn.execute("DELETE FROM liveness_frames WHERE expires_at<?",(current,))
        conn.execute("DELETE FROM revoked_sessions WHERE expires_at<?",(current,))
        conn.execute("INSERT INTO liveness_challenges(id,voter_id,action,created_at,expires_at,used,min_seconds,frame_count) VALUES (?,?,?,?,?,0,?,?)",
                     (identifier,voter_id,action,current,current+45,1.0 if fast else 2.0,10 if fast else 16))
        conn.commit()
    steps = ["Close both eyes, then open them when prompted"]
    return {"challenge_id":identifier,"challenge":action,"expires_in":45,
            "steps":steps,"capture_mode":"quick" if fast else "guided",
            "instruction":"Keep your head still. Close and reopen both eyes when prompted."}


def consume(db, identifier, voter_id, frame_count=None):
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM liveness_challenges WHERE id=?",(identifier,)).fetchone()
        if not row or row["used"]:
            raise HTTPException(401,"Live check missing or already used. Start again.")
        conn.execute("UPDATE liveness_challenges SET used=1 WHERE id=?",(identifier,))
        conn.commit()
    if row["voter_id"] != voter_id or time.time() > row["expires_at"]:
        raise HTTPException(401,"Live check expired or belongs to another voter.")
    if row["action"] != "blink_once":
        raise HTTPException(401,"The live check has changed. Refresh the page and start again.")
    if time.time() - row["created_at"] < row["min_seconds"]:
        raise HTTPException(401,"Live capture was too short. Follow the eye prompts.")
    if row["frame_count"] and frame_count != row["frame_count"]:
        raise HTTPException(401,"The capture does not match this live check. Start again.")
    return row["action"]


def reject_replays(db, images):
    # Hash decoded pixels, not the easily changed JPEG/base64 envelope.
    fingerprints = [hashlib.sha256(image.tobytes()).hexdigest() for image in images]
    if len(set(fingerprints)) != len(fingerprints):
        raise HTTPException(401,"Repeated camera frames detected. Use a live camera.")
    # A stationary head with a blink can change too little of a whole-frame
    # thumbnail. Exact duplicate pixels are rejected above; the eye landmarks
    # must independently prove close/reopen instead of demanding head motion.
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for fingerprint in fingerprints:
            if conn.execute("SELECT 1 FROM liveness_frames WHERE fingerprint=? AND expires_at>?",
                            (fingerprint,time.time())).fetchone():
                raise HTTPException(401,"Previously submitted camera frames cannot be reused.")
        conn.executemany("INSERT OR REPLACE INTO liveness_frames VALUES (?,?)",
                         [(fp,time.time()+600) for fp in fingerprints])
        conn.commit()


def yaw(landmarks):
    left = np.mean(landmarks["left_eye"],axis=0)
    right = np.mean(landmarks["right_eye"],axis=0)
    nose = np.mean(landmarks["nose_tip"],axis=0)
    width = float(np.linalg.norm(right-left))
    if width < 10:
        raise HTTPException(400,"Move closer and look toward the camera.")
    return float((nose[0]-(left[0]+right[0])/2)/width)


def validate(action, landmarks, ear, has_blink):
    if action != "blink_once":
        raise HTTPException(401, "The live check has changed. Refresh the page and start again.")
    if len(landmarks) not in (10, 16):
        raise HTTPException(401, "The live sequence is incomplete. Start again.")
    samples = [(ear(item["left_eye"]),ear(item["right_eye"])) for item in landmarks]
    if not has_blink(samples):
        raise HTTPException(401,"Face matched, but the eye movement was not confirmed. Close both eyes, then open them when prompted.")
