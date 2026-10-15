import os
import json
import base64
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
import numpy as np
import cv2

# Set required environment variable before importing main
os.environ["FASTAPI_SECRET_KEY"] = "test-secret-key-with-at-least-thirty-two-bytes"
os.environ["ADMIN_USERNAME"] = "admin_user"
os.environ["ADMIN_PASSWORD"] = "securepassword123"
os.environ["REDIS_URL"] = "memory://"

import main
from main import (
    app,
    get_db,
    validate_face_image_quality,
    validate_embedding,
    _relayer_configuration,
)


def _make_valid_image_b64() -> str:
    img = np.zeros((240, 320, 3), dtype=np.uint8)
    img[::2, ::2] = 180
    img[1::2, 1::2] = 100
    _, buf = cv2.imencode(".jpg", img)
    return base64.b64encode(buf).decode()


VALID_IMAGE = _make_valid_image_b64()
VALID_IMAGES_5 = [VALID_IMAGE] * 5
CHALLENGE_FRAME_COUNT = 8
VALID_CHALLENGE_IMAGES = [VALID_IMAGE] * CHALLENGE_FRAME_COUNT
LIVE_YAW_SEQUENCE = [0.0, -0.2, -0.2, 0.0, 0.2, 0.2, 0.0, 0.2]

import tempfile


@pytest.fixture(autouse=True)
def setup_database():
    """Use a temporary SQLite database for testing."""
    original_db = main.DB_PATH
    fd, temp_path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    main.DB_PATH = temp_path
    main.init_db()
    main._LIVENESS_CHALLENGES.clear()

    limiter = getattr(app.state, "limiter", None)
    storage = getattr(limiter, "_storage", None)
    if storage is not None:
        storage.reset()

    # Seed the admin user manually to bypass lifespan
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO admins (admin_id, password_hash) VALUES (?, ?)",
            ("admin_user", main.get_password_hash("securepassword123")),
        )
        conn.commit()

    yield
    main.DB_PATH = original_db
    try:
        os.remove(temp_path)
    except OSError:
        pass


def get_admin_token():
    return main.create_jwt("admin", "admin")


def issue_liveness_challenge(client, voter_id):
    response = client.get(
        "/api/v1/liveness/challenge",
        params={"voter_id": voter_id},
    )
    assert response.status_code == 200
    return response.json()["challenge_id"]


def make_landmarks(yaw):
    return {
        "left_eye": [(30, 40)] * 6,
        "right_eye": [(70, 40)] * 6,
        "nose_tip": [(50 + yaw * 40, 55)] * 5,
    }


def mock_live_capture(mock_details, mock_ear, yaw_sequence=LIVE_YAW_SEQUENCE):
    embedding = np.ones(128, dtype=np.float32)
    mock_details.side_effect = [
        (embedding.copy(), make_landmarks(yaw)) for yaw in yaw_sequence
    ]
    eye_ratios = [0.3] * len(yaw_sequence)
    for start in range(0, len(eye_ratios), CHALLENGE_FRAME_COUNT):
        blink_start = start + CHALLENGE_FRAME_COUNT // 2 - 1
        eye_ratios[blink_start : blink_start + 3] = [0.3, 0.16, 0.3]
    mock_ear.side_effect = [ratio for ratio in eye_ratios for _ in range(2)]


def test_health():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


def test_admin_can_delete_voter_and_credentials():
    with get_db() as conn:
        conn.execute(
            "INSERT INTO voters (voter_id, role, face_encoding) VALUES (?, ?, ?)",
            ("delete_me", "user", "[1, 2, 3]"),
        )
        conn.execute(
            "INSERT INTO voting_credentials (credential_hash, voter_id, issued_at, expires_at) VALUES (?, ?, ?, ?)",
            ("credential-to-delete", "delete_me", "2026-01-01", "2026-01-01"),
        )
        conn.commit()

    with TestClient(app) as client:
        response = client.delete(
            "/api/v1/admin/voters/delete_me",
            headers={"Authorization": f"Bearer {get_admin_token()}"},
        )

    assert response.status_code == 200
    with get_db() as conn:
        assert conn.execute("SELECT 1 FROM voters WHERE voter_id = ?", ("delete_me",)).fetchone() is None
        assert conn.execute("SELECT 1 FROM voting_credentials WHERE voter_id = ?", ("delete_me",)).fetchone() is None


@patch("main.get_enrollment_embedding")
def test_enroll_face_success(mock_embed):
    mock_embed.return_value = np.ones(128, dtype=np.float32)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/enroll-face",
            json={"voter_id": "test_user", "role": "user", "images_base64": VALID_IMAGES_5},
            headers={"Authorization": f"Bearer {get_admin_token()}"},
        )
        assert response.status_code == 201
        assert "enrolled successfully" in response.json()["message"]


@patch("main.get_enrollment_embedding")
def test_register_user_persists_and_can_verify_after_restart(mock_embed):
    mock_embed.return_value = np.ones(128, dtype=np.float32)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/register-user",
            json={
                "voter_id": "1KG23CB052",
                "images_base64": VALID_IMAGES_5,
                "name": "Test User",
                "usn": "1KG23CB052",
            },
        )
        assert response.status_code == 201

    with get_db() as conn:
        row = conn.execute(
            "SELECT voter_id, role, face_encoding, name, usn FROM voters WHERE voter_id = ?",
            ("1kg23cb052",),
        ).fetchone()

    assert row is not None
    assert row["role"] == "user"
    assert row["name"] == "Test User"
    assert row["usn"] == "1KG23CB052"
    assert np.array(json.loads(row["face_encoding"])).shape == (128,)

    with patch("main.get_face_details") as mock_details, \
         patch("main.compare_faces") as mock_compare, \
         patch("main.calculate_ear") as mock_ear, \
         TestClient(app) as restarted_client:
        mock_live_capture(mock_details, mock_ear)
        mock_compare.return_value = (True, 0.0)

        challenge_id = issue_liveness_challenge(restarted_client, "1KG23CB052")
        verify_response = restarted_client.post(
            "/api/v1/verify-face",
            json={
                "voter_id": "1KG23CB052",
                "challenge_id": challenge_id,
                "images_base64": VALID_CHALLENGE_IMAGES,
            },
        )

    assert verify_response.status_code == 200
    assert verify_response.json()["voter_id"] == "1kg23cb052"


@patch("main.get_face_details")
@patch("main.compare_faces")
@patch("main.calculate_ear")
def test_verify_face_success(mock_ear, mock_compare, mock_details):
    # Return embedding and dummy landmarks
    mock_live_capture(mock_details, mock_ear)
    mock_compare.return_value = (True, 0.0)

    with patch("main.get_enrollment_embedding") as mock_enroll, TestClient(app) as client:
        mock_enroll.return_value = np.ones(128, dtype=np.float32)

        # 1. Enroll
        client.post(
            "/api/v1/enroll-face",
            json={"voter_id": "voter_1", "role": "user", "images_base64": VALID_IMAGES_5},
            headers={"Authorization": f"Bearer {get_admin_token()}"},
        )

        # 2. Verify
        challenge_id = issue_liveness_challenge(client, "voter_1")
        response = client.post(
            "/api/v1/verify-face",
            json={
                "voter_id": "voter_1",
                "challenge_id": challenge_id,
                "images_base64": VALID_CHALLENGE_IMAGES,
            },
        )
        assert response.status_code == 200
        assert "auth_token" in response.cookies
        assert response.cookies["auth_token"] is not None
        assert response.json()["voter_id"] == "voter_1"

        replayed = client.post(
            "/api/v1/verify-face",
            json={
                "voter_id": "voter_1",
                "challenge_id": challenge_id,
                "images_base64": VALID_CHALLENGE_IMAGES,
            },
        )
        assert replayed.status_code == 401
        assert "already used" in replayed.json()["detail"]


@patch("main.get_face_details")
@patch("main.compare_faces")
@patch("main.calculate_ear")
def test_blink_login_succeeds_without_head_movement(mock_ear, mock_compare, mock_details):
    mock_live_capture(
        mock_details,
        mock_ear,
        yaw_sequence=[0.0] * CHALLENGE_FRAME_COUNT,
    )
    mock_compare.return_value = (True, 0.0)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO voters (voter_id, role, face_encoding, id_verified) VALUES (?, ?, ?, ?)",
            ("static_voter", "user", json.dumps(np.ones(128).tolist()), 1),
        )
        conn.commit()

    with TestClient(app) as client:
        challenge_id = issue_liveness_challenge(client, "static_voter")
        response = client.post(
            "/api/v1/verify-face",
            json={
                "voter_id": "static_voter",
                "challenge_id": challenge_id,
                "images_base64": VALID_CHALLENGE_IMAGES,
            },
        )

    assert response.status_code == 200
    assert response.cookies.get("auth_token")


def test_enroll_requires_admin():
    with TestClient(app) as client:
        # No token
        response = client.post(
            "/api/v1/enroll-face",
            json={"voter_id": "test_user", "role": "user", "images_base64": VALID_IMAGES_5},
        )
        assert response.status_code == 401

        # User token
        user_token = main.create_jwt("voter_1", "user")
        response2 = client.post(
            "/api/v1/enroll-face",
            json={"voter_id": "test_user", "role": "user", "images_base64": VALID_IMAGES_5},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response2.status_code == 403


def test_verify_face_rate_limiting():
    if hasattr(app.state, "limiter") and app.state.limiter._storage:
        app.state.limiter._storage.reset()

    with patch("main.get_face_details") as mock_details, TestClient(app) as client:
        mock_details.return_value = None
        for _ in range(5):
            response = client.post(
                "/api/v1/verify-face",
                json={"voter_id": "test_user", "challenge_id": "unused", "images_base64": [VALID_IMAGE, VALID_IMAGE]},
            )
            assert response.status_code != 429
        response = client.post(
            "/api/v1/verify-face",
            json={"voter_id": "test_user", "challenge_id": "unused", "images_base64": [VALID_IMAGE, VALID_IMAGE]},
        )
        assert response.status_code == 429
        assert "Too many requests" in response.json()["detail"]


def test_admin_login():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/admin-login",
            json={"username": "admin_user", "password": "securepassword123"},
        )
        assert response.status_code == 200
        assert "auth_token" in response.cookies

        response = client.post(
            "/api/v1/admin-login",
            json={"username": "admin_user", "password": "wrongpassword"},
        )
        assert response.status_code == 401


@patch("main.get_face_details")
@patch("main.compare_faces")
@patch("main.calculate_ear")
def test_logout_allows_login_with_new_voting_credential(mock_ear, mock_compare, mock_details):
    mock_live_capture(mock_details, mock_ear, yaw_sequence=LIVE_YAW_SEQUENCE * 2)
    mock_compare.return_value = (True, 0.0)

    with patch("main.get_enrollment_embedding") as mock_enroll, TestClient(app) as client:
        mock_enroll.return_value = np.ones(128, dtype=np.float32)
        client.post(
            "/api/v1/enroll-face",
            json={"voter_id": "logout_user", "role": "user", "images_base64": VALID_IMAGES_5},
            headers={"Authorization": f"Bearer {get_admin_token()}"},
        )
        with get_db() as conn:
            conn.execute(
                "UPDATE voters SET id_verified = 1 WHERE voter_id = ?",
                ("logout_user",),
            )
            conn.commit()

        first_challenge = issue_liveness_challenge(client, "logout_user")
        first_login = client.post(
            "/api/v1/verify-face",
            json={
                "voter_id": "logout_user",
                "challenge_id": first_challenge,
                "images_base64": VALID_CHALLENGE_IMAGES,
            },
        )
        first_credential = first_login.cookies.get(main._CREDENTIAL_COOKIE)
        assert first_login.status_code == 200
        assert first_credential

        client.cookies.delete(main._CREDENTIAL_COOKIE)
        logout = client.post("/api/v1/auth/logout")
        assert logout.status_code == 200

        second_challenge = issue_liveness_challenge(client, "logout_user")
        second_login = client.post(
            "/api/v1/verify-face",
            json={
                "voter_id": "logout_user",
                "challenge_id": second_challenge,
                "images_base64": VALID_CHALLENGE_IMAGES,
            },
        )
        assert second_login.status_code == 200, second_login.text
        assert second_login.cookies.get(main._CREDENTIAL_COOKIE)
        assert second_login.cookies.get(main._CREDENTIAL_COOKIE) != first_credential


# ── Additional Tests for Upgrade Features ─────────────────────────────────────

def test_image_quality_validation():
    # Empty
    with pytest.raises(main.HTTPException) as exc1:
        validate_face_image_quality(np.array([]))
    assert exc1.value.status_code == 400

    # Low resolution
    tiny = np.zeros((100, 100, 3), dtype=np.uint8)
    with pytest.raises(main.HTTPException) as exc2:
        validate_face_image_quality(tiny)
    assert "resolution" in exc2.value.detail.lower()

    # Dark image
    dark = np.zeros((240, 320, 3), dtype=np.uint8)
    with pytest.raises(main.HTTPException) as exc3:
        validate_face_image_quality(dark)
    assert "dark" in exc3.value.detail.lower()


def test_validate_embedding():
    # Valid
    vec = np.ones(128, dtype=np.float32)
    validated = validate_embedding(vec)
    assert validated.shape == (128,)

    # Wrong shape
    with pytest.raises(ValueError):
        validate_embedding(np.ones(64))

    # Infinite
    bad_vec = np.ones(128, dtype=np.float32)
    bad_vec[0] = np.nan
    with pytest.raises(ValueError):
        validate_embedding(bad_vec)


def test_liveness_challenge_endpoint():
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/liveness/challenge",
            params={"voter_id": "voter_1"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["challenge"] == "blink_once"
        assert "challenge_id" in data
        assert "instruction" in data
        assert data["expires_in"] == 30
