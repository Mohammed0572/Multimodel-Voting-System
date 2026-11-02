"""Offline enrollment utility for trusted operators; uses the API's validation.

Place at least five images per voter in enrollment_images using
VOTER-ID__01.jpg ... VOTER-ID__05.jpg. Existing profiles require admin approval.
Raw operator-supplied files are not deleted automatically; remove them securely
when the enrollment task is finished.
"""
import base64
from collections import defaultdict
import json
from pathlib import Path

from fastapi import HTTPException
from main import get_db, init_db, get_enrollment_profile, _face_workers

IMAGES_DIR = Path(__file__).resolve().with_name("enrollment_images")


def _mass_enroll():
    IMAGES_DIR.mkdir(exist_ok=True)
    init_db()
    samples = defaultdict(list)
    for path in sorted(IMAGES_DIR.iterdir()):
        if path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            continue
        voter_id = path.stem.rsplit("__", 1)[0].strip().lower()
        if not voter_id or len(voter_id) > 100 or path.stat().st_size > 1_500_000:
            print("Skipped invalid enrollment file")
            continue
        samples[voter_id].append(base64.b64encode(path.read_bytes()).decode("ascii"))
    enrolled = 0
    for voter_id, frames in samples.items():
        try:
            encoded = json.dumps(get_enrollment_profile(frames[:10]))
            with get_db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute("SELECT deleted,role,face_encoding FROM voters WHERE voter_id=?", (voter_id,)).fetchone()
                if existing and (existing["deleted"] or existing["role"] != "user"):
                    raise HTTPException(403, "Inactive or non-voter account")
                if existing and existing["face_encoding"]:
                    conn.execute("UPDATE voters SET pending_face_encoding=? WHERE voter_id=?", (encoded,voter_id))
                else:
                    conn.execute("""INSERT INTO voters(voter_id,face_encoding) VALUES (?,?)
                        ON CONFLICT(voter_id) DO UPDATE SET face_encoding=excluded.face_encoding,
                        id_verified=0,session_version=voters.session_version+1""", (voter_id,encoded))
                conn.commit()
            enrolled += 1
        except HTTPException as error:
            print(f"Enrollment rejected: {error.detail}")
    print(f"Prepared {enrolled} enrollment profiles. Administrator approval is required.")


def mass_enroll():
    _face_workers.start()
    try:
        _mass_enroll()
    finally:
        _face_workers.close()


if __name__ == "__main__":
    mass_enroll()
