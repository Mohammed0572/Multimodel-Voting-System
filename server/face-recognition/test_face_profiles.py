import json
from unittest.mock import patch

import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main
import active_liveness
from main import get_enrollment_profile as real_enrollment_profile
from face_profiles import build_profile, parse_profile, matches_sface, SFACE_MODEL, DLIB_MODEL
from test_main import (setup_database, VALID_CHALLENGE_IMAGES, VALID_IMAGES_5,
                       get_admin_token, issue_liveness_challenge, make_landmarks, mock_live_capture)


def vector(index=0):
    result = np.zeros(128, dtype=np.float32)
    result[index] = 1
    return result


def seed(profile, identifier="profile_voter"):
    with main.get_db() as conn:
        conn.execute("INSERT INTO voters(voter_id,face_encoding,id_verified) VALUES (?,?,1)", (identifier, json.dumps(profile)))
        conn.commit()
    return identifier


def test_legacy_vectors_keep_their_model_and_scale():
    original = np.full(128, .2, dtype=np.float32)
    model, templates = parse_profile(json.dumps(original.tolist()))
    assert model == DLIB_MODEL
    np.testing.assert_array_equal(templates[0], original)


@pytest.mark.parametrize("profile", [
    {"model":"unknown","templates":[[1]*128]*3},
    {"model":SFACE_MODEL,"templates":[[1]*128]},
    {"model":SFACE_MODEL,"templates":[[0]*128]*3},
    {"model":SFACE_MODEL,"templates":[[float("nan")]*128]*3},
    [0]*128, [1]*127,
])
def test_bad_templates_fail_closed(profile):
    with pytest.raises(ValueError):
        parse_profile(json.dumps(profile))


def test_first_bad_sample_does_not_define_enrollment():
    profile = build_profile([vector(1), vector(), vector(), vector(), vector()])
    model, templates = parse_profile(json.dumps(profile))
    assert model == SFACE_MODEL and len(templates) == 4
    assert matches_sface(templates, vector())[0]
    assert not matches_sface(templates, vector(1))[0]
    with pytest.raises(ValueError):
        build_profile([vector()]*3+[vector(1)]*3)


def test_fast_update_is_activated_only_by_approval(monkeypatch):
    identifier = seed(np.ones(128).tolist())
    profile = build_profile([vector()]*5)
    monkeypatch.setattr(main, "get_enrollment_profile", lambda _: profile)
    old_token = main.create_jwt(identifier, "user")
    with TestClient(main.app) as client:
        result = client.post("/api/v1/register-user", json={"voter_id":identifier,"images_base64":VALID_IMAGES_5})
        assert result.status_code == 201 and result.json()["pending_review"]
        before = client.get("/api/v1/liveness/challenge", params={"voter_id":identifier}).json()
        assert before["face_update_pending"] and before["profile_model"] == DLIB_MODEL
        assert before["capture_mode"] == "guided"
        approval = client.post(f"/api/v1/admin/voters/{identifier}/approve-face-update", headers={"Authorization":f"Bearer {get_admin_token()}"})
        assert approval.status_code == 200
        after = client.get("/api/v1/liveness/challenge", params={"voter_id":identifier}).json()
        assert not after["face_update_pending"] and after["profile_model"] == SFACE_MODEL
        assert after["capture_mode"] == "quick" and after["face_updated_at"]
        slow = client.get("/api/v1/liveness/challenge", params={"voter_id":identifier,"guided":"true"}).json()
        assert slow["capture_mode"] == "guided"
    with pytest.raises(HTTPException):
        main.decode_jwt(old_token)


@pytest.mark.parametrize("substitute", [False, True])
def test_fast_login_checks_every_frame_and_order(substitute, monkeypatch):
    identifier = seed(build_profile([vector()]*5))
    observations = [(vector(), make_landmarks(0)) for _ in range(10)]
    if substitute:
        observations[8] = (vector(1), observations[8][1])
    def analyze(images, model):
        assert model == SFACE_MODEL and len(images) == 10
        return observations
    monkeypatch.setattr(main._face_workers, "analyze", analyze)
    ear_values = iter([value for value in [.3]*3+[.12]*3+[.3]*4 for _ in range(2)])
    monkeypatch.setattr(main, "calculate_ear", lambda _: next(ear_values))
    with TestClient(main.app) as client:
        challenge = issue_liveness_challenge(client, identifier)
        response = client.post("/api/v1/verify-face", json={"voter_id":identifier,"challenge_id":challenge,"images_base64":VALID_CHALLENGE_IMAGES[:10]})
        assert response.status_code == (401 if substitute else 200), response.text
        assert ("auth_token" in response.cookies) == (not substitute)


def test_pending_update_does_not_disable_current_identity():
    identifier = seed(np.ones(128).tolist())
    with main.get_db() as conn:
        conn.execute("UPDATE voters SET pending_face_encoding=? WHERE voter_id=?", (json.dumps(build_profile([vector(1)]*3)), identifier))
        conn.commit()
    with patch("main.get_face_details") as details, patch("main.calculate_ear") as ear, TestClient(main.app) as client:
        mock_live_capture(details, ear)
        challenge = issue_liveness_challenge(client, identifier)
        response = client.post("/api/v1/verify-face", json={"voter_id":identifier,"challenge_id":challenge,"images_base64":VALID_CHALLENGE_IMAGES})
        assert response.status_code == 200, response.text


def test_deliberate_long_closure_is_not_a_false_rejection():
    assert main._has_blink_sequence([(.3,.3)]*2+[(.12,.12)]*6+[(.3,.3)]*2)
    assert not main._has_blink_sequence([(.3,.3)]*2+[(.12,.3)]*6+[(.3,.3)]*2)
    assert not main._has_blink_sequence([(.3,.3)]*2+[(.12,.12)]*8)


def test_quick_capture_count_and_elapsed_time_are_bound_to_challenge(monkeypatch):
    monkeypatch.setattr(active_liveness.time, "time", lambda: 1000)
    challenge = active_liveness.issue(main.get_db, "quick", fast=True)
    monkeypatch.setattr(active_liveness.time, "time", lambda: 1000.5)
    with pytest.raises(HTTPException, match="too short"):
        active_liveness.consume(main.get_db, challenge["challenge_id"], "quick", 10)
    challenge = active_liveness.issue(main.get_db, "quick", fast=True)
    monkeypatch.setattr(active_liveness.time, "time", lambda: 1004)
    with pytest.raises(HTTPException, match="does not match"):
        active_liveness.consume(main.get_db, challenge["challenge_id"], "quick", 16)


@pytest.mark.parametrize("case", ["valid", "no_face", "partial"])
def test_actual_enrollment_pipeline_checks_worker_output(case, monkeypatch):
    observations = [(vector(), make_landmarks(0))]*5
    if case == "no_face": observations = [None]*5
    if case == "partial": observations = observations[:1]
    monkeypatch.setattr(main._face_workers, "analyze", lambda images, model: observations)
    if case == "valid":
        assert real_enrollment_profile(VALID_IMAGES_5)["model"] == SFACE_MODEL
    else:
        with pytest.raises(HTTPException) as error:
            real_enrollment_profile(VALID_IMAGES_5)
        assert error.value.status_code == (400 if case == "no_face" else 503)


def test_invalid_model_artifact_fails_before_inference(monkeypatch, tmp_path):
    import face_models
    face_models.model_path.cache_clear()
    try:
        monkeypatch.setattr(face_models, "MODEL_DIR", tmp_path)
        (tmp_path / face_models.MODELS["sface"][1]).write_bytes(b"not a model")
        with pytest.raises(RuntimeError, match="missing or invalid"):
            face_models.model_path("sface")
    finally:
        face_models.model_path.cache_clear()


def test_enrollment_database_does_not_change_with_launch_directory(monkeypatch, tmp_path):
    from pathlib import Path
    import config
    settings = config.Settings(_env_file=None, FACE_DB_PATH="./data/face_voter_db.sqlite")
    expected = str(Path(config.__file__).resolve().parent / "data" / "face_voter_db.sqlite")
    assert settings.resolved_face_db_path == expected
    monkeypatch.chdir(tmp_path)
    assert settings.resolved_face_db_path == expected
