import os
import json
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
import numpy as np

# Set required environment variable before importing main
os.environ["FASTAPI_SECRET_KEY"] = "supersecretkey"
os.environ["ADMIN_USERNAME"] = "admin_user"
os.environ["ADMIN_PASSWORD"] = "securepassword123"

import main
from main import app, get_db

# Mock base64 image representing a tiny 1x1 png
DUMMY_IMAGE = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="

import tempfile

@pytest.fixture(autouse=True)
def setup_database():
    """Use a temporary SQLite database for testing."""
    original_db = main.DB_PATH
    fd, temp_path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    main.DB_PATH = temp_path
    main.init_db()
    
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


@patch("main.get_face_embedding")
def test_enroll_face_success(mock_embed):
    mock_embed.return_value = np.ones(128)
    
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/enroll-face",
            json={"voter_id": "test_user", "role": "user", "image_base64": DUMMY_IMAGE},
            headers={"Authorization": f"Bearer {get_admin_token()}"}
        )
        assert response.status_code == 201
        assert "enrolled successfully" in response.json()["message"]

@patch("main.get_face_embedding")
def test_register_user_persists_and_can_verify_after_restart(mock_embed):
    mock_embed.return_value = np.ones(128)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/register-user",
            json={
                "voter_id": "1KG23CB052",
                "image_base64": DUMMY_IMAGE,
                "images_base64": [DUMMY_IMAGE, DUMMY_IMAGE],
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
        mock_details.return_value = (np.ones(128), {"left_eye": [], "right_eye": []})
        mock_compare.return_value = (True, 0.0)
        mock_ear.side_effect = [0.3, 0.3, 0.2, 0.2]

        verify_response = restarted_client.post(
            "/api/v1/verify-face",
            json={"voter_id": "1KG23CB052", "images_base64": [DUMMY_IMAGE, DUMMY_IMAGE]},
        )

    assert verify_response.status_code == 200
    assert verify_response.json()["voter_id"] == "1kg23cb052"

@patch("main.get_face_details")
@patch("main.compare_faces")
@patch("main.calculate_ear")
def test_verify_face_success(mock_ear, mock_compare, mock_details):
    # Return embedding and dummy landmarks
    mock_details.return_value = (np.ones(128), {"left_eye": [], "right_eye": []})
    mock_compare.return_value = (True, 0.0)
    # Simulate a blink: high EAR then low EAR
    mock_ear.side_effect = [0.3, 0.3, 0.2, 0.2]
    
    with TestClient(app) as client:
        # 1. Enroll
        client.post(
            "/api/v1/enroll-face",
            json={"voter_id": "voter_1", "role": "user", "image_base64": DUMMY_IMAGE},
            headers={"Authorization": f"Bearer {get_admin_token()}"}
        )
        
        # 2. Verify
        response = client.post(
            "/api/v1/verify-face",
            json={"voter_id": "voter_1", "images_base64": [DUMMY_IMAGE, DUMMY_IMAGE]}
        )
        assert response.status_code == 200
        assert "auth_token" in response.cookies
        assert response.cookies["auth_token"] is not None
        assert response.json()["voter_id"] == "voter_1"

def test_enroll_requires_admin():
    with TestClient(app) as client:
        # No token
        response = client.post(
            "/api/v1/enroll-face",
            json={"voter_id": "test_user", "role": "user", "image_base64": DUMMY_IMAGE}
        )
        assert response.status_code == 401
        
        # User token
        user_token = main.create_jwt("voter_1", "user")
        response2 = client.post(
            "/api/v1/enroll-face",
            json={"voter_id": "test_user", "role": "user", "image_base64": DUMMY_IMAGE},
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response2.status_code == 403

def test_verify_face_rate_limiting():
    # Reset the rate limiter storage to start fresh
    if hasattr(app.state, "limiter") and app.state.limiter._storage:
        app.state.limiter._storage.reset()

    with TestClient(app) as client:
        # The limit is 5 per minute. Send 5 requests (which should bypass validation but fail on face detection, still triggering the limit)
        for _ in range(5):
            response = client.post(
                "/api/v1/verify-face",
                json={"voter_id": "test_user", "images_base64": [DUMMY_IMAGE, DUMMY_IMAGE]}
            )
            assert response.status_code != 429
        # The 6th request must trigger a 429 Too Many Requests response
        response = client.post(
            "/api/v1/verify-face",
            json={"voter_id": "test_user", "images_base64": [DUMMY_IMAGE, DUMMY_IMAGE]}
        )
        assert response.status_code == 429
        assert "Too many requests" in response.json()["detail"]


def test_admin_login():
    with TestClient(app) as client:
        # Valid login
        response = client.post(
            "/api/v1/admin-login",
            json={"username": "admin_user", "password": "securepassword123"}
        )
        assert response.status_code == 200
        assert "auth_token" in response.cookies

        # Invalid login
        response = client.post(
            "/api/v1/admin-login",
            json={"username": "admin_user", "password": "wrongpassword"}
        )
        assert response.status_code == 401

