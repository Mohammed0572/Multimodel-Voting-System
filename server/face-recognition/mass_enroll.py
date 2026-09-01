import os
import sqlite3
import json
import face_recognition

DB_PATH = "face_voter_db.sqlite"
IMAGES_DIR = "enrollment_images"
CSBS_SEED_PATH = "csbs_students.json"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS voters (
            voter_id       TEXT PRIMARY KEY NOT NULL,
            role           TEXT NOT NULL DEFAULT 'user',
            face_encoding  TEXT NOT NULL DEFAULT '',
            student_name   TEXT NOT NULL DEFAULT '',
            branch         TEXT NOT NULL DEFAULT '',
            class_name     TEXT NOT NULL DEFAULT '',
            batch           TEXT NOT NULL DEFAULT '',
            id_verified    INTEGER NOT NULL DEFAULT 0,
            verified_by    TEXT,
            verified_at    TEXT
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
    }.items():
        if column not in existing_columns:
            cursor.execute(f"ALTER TABLE voters ADD COLUMN {column} {definition}")
    if os.path.exists(CSBS_SEED_PATH):
        for student in json.load(open(CSBS_SEED_PATH, encoding="utf-8")):
            cursor.execute(
                """INSERT INTO voters (voter_id, role, student_name, branch, class_name, batch)
                   VALUES (?, 'user', ?, 'CB', 'CSBS', ?)
                   ON CONFLICT(voter_id) DO UPDATE SET student_name=excluded.student_name,
                     branch=excluded.branch, class_name=excluded.class_name, batch=excluded.batch""",
                (student["usn"].lower(), student.get("student_name", ""), "2024" if student["usn"].startswith("1KG24") else "2023"),
            )
    conn.commit()
    return conn

def mass_enroll():
    if not os.path.exists(IMAGES_DIR):
        print(f"Directory '{IMAGES_DIR}' not found. Creating it.")
        os.makedirs(IMAGES_DIR)
        print("Please place voter images in this directory. The filename (without extension) will be used as the voter_id.")
        return

    conn = init_db()
    cursor = conn.cursor()

    from collections import defaultdict
    import numpy as np

    voter_samples = defaultdict(list)
    failed = 0

    for filename in sorted(os.listdir(IMAGES_DIR)):
        if not filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            continue

        raw_id = os.path.splitext(filename)[0]
        # Support voter_1, voter_2 or just voter
        voter_id = raw_id.split('_')[0].strip().lower() if '_' in raw_id else raw_id.strip().lower()
        filepath = os.path.join(IMAGES_DIR, filename)

        try:
            image = face_recognition.load_image_file(filepath)
            face_locations = face_recognition.face_locations(image)

            if len(face_locations) == 0:
                print(f"[{raw_id}] Failed: No face detected in {filename}")
                failed += 1
                continue
            if len(face_locations) > 1:
                print(f"[{raw_id}] Failed: Multiple faces detected in {filename}. Please use an image with only one face.")
                failed += 1
                continue

            # Generate encoding
            encoding = face_recognition.face_encodings(image, known_face_locations=face_locations)[0]
            voter_samples[voter_id].append(encoding)
            print(f"[{voter_id}] Processed sample from {filename}")

        except Exception as e:
            print(f"[{raw_id}] Error processing {filename}: {e}")
            failed += 1

    # Clean previous table entries and insert averaged encodings
    enrolled = 0
    for voter_id, enc_list in voter_samples.items():
        averaged = np.mean(enc_list, axis=0)
        encoding_json = json.dumps(averaged.tolist())

        cursor.execute(
            """
            INSERT INTO voters (voter_id, role, face_encoding)
            VALUES (?, ?, ?)
            ON CONFLICT(voter_id) DO UPDATE SET
                face_encoding = excluded.face_encoding
            """,
            (voter_id, 'user', encoding_json),
        )
        conn.commit()
        print(f"[{voter_id}] Successfully enrolled with {len(enc_list)} sample(s).")
        enrolled += 1

    conn.commit()
    conn.close()

    print("\n--- Mass Enrollment Summary ---")
    print(f"Successfully enrolled voters: {enrolled}")
    print(f"Failed image samples: {failed}")

if __name__ == "__main__":
    mass_enroll()
