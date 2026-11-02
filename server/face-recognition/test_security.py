import base64
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from web3.exceptions import TransactionNotFound

import main
import active_liveness
from voting_service import VotingService
from test_main import (setup_database, get_admin_token, make_landmarks,
                       VALID_CHALLENGE_IMAGES, issue_liveness_challenge, mock_live_capture)


def voter(identifier="security_voter"):
    with main.get_db() as conn:
        conn.execute("INSERT INTO voters(voter_id,face_encoding,id_verified) VALUES (?,?,1)",
                     (identifier,json.dumps(np.ones(128).tolist())))
        conn.commit()
    return identifier


def submitted(service, voter_id):
    raw = service.issue(voter_id)
    attempt, _ = service.reserve(voter_id,raw)
    with main.get_db() as conn:
        conn.execute("""UPDATE vote_attempts SET status='SUBMITTED',tx_hash=?,raw_transaction='abcd',chain_id=1337
            WHERE id=?""",("0x"+"12"*32,attempt["id"]))
        conn.commit()
    return raw, attempt


def receipt_chain(status=1):
    chain = MagicMock()
    chain.eth.chain_id = 1337
    chain.eth.block_number = 10
    chain.eth.get_transaction_receipt.return_value = {
        "status":status,"blockNumber":10,"blockHash":bytes.fromhex("34"*32)}
    chain.eth.get_block.return_value = {"hash":bytes.fromhex("34"*32)}
    return chain


def test_concurrent_issuance_returns_one_authorization():
    identifier = voter()
    with ThreadPoolExecutor(max_workers=8) as pool:
        credentials = list(pool.map(lambda _:main.issue_voting_credential(identifier),range(16)))
    assert len(set(credentials)) == 1
    with main.get_db() as conn:
        assert conn.execute("SELECT count(*) FROM voting_credentials WHERE revoked_at IS NULL").fetchone()[0] == 1


def test_two_tabs_reserve_exactly_one_ballot():
    identifier = voter()
    service = main.voting_service()
    raw = service.issue(identifier)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _:service.reserve(identifier,raw),range(16)))
    assert sum(fresh for _,fresh in results) == 1
    assert len({attempt["id"] for attempt,_ in results}) == 1
    assert service.issue(identifier) is None


def test_rpc_runs_without_database_write_lock(monkeypatch):
    identifier = voter()
    service = main.voting_service()
    raw = service.issue(identifier)
    def prepare(attempt, candidate, raw):
        with main.get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE voters SET student_name='lock-check' WHERE voter_id=?",(identifier,))
            conn.commit()
        raise RuntimeError("RPC unavailable")
    monkeypatch.setattr(service,"prepare",prepare)
    assert service.cast(identifier,1,raw)["status"] == "FAILED"


def test_uncertain_broadcast_never_releases_authorization(monkeypatch):
    identifier = voter()
    service = main.voting_service()
    _, attempt = submitted(service,identifier)
    chain = receipt_chain()
    chain.eth.get_transaction_receipt.side_effect = TransactionNotFound("not mined")
    chain.eth.send_raw_transaction.side_effect = TimeoutError()
    monkeypatch.setattr(service,"connection",lambda:(chain,None))
    service.reconcile()
    assert service.status(identifier)["status"] == "SUBMITTED"
    assert service.issue(identifier) is None
    chain.eth.send_raw_transaction.assert_called_once_with(bytes.fromhex("abcd"))
    assert main.voting_service().status(identifier)["status"] == "SUBMITTED"


def test_confirmation_database_failure_recovers_after_restart(monkeypatch):
    identifier = voter()
    service = main.voting_service()
    raw, attempt = submitted(service,identifier)
    chain = receipt_chain()
    monkeypatch.setattr(service,"connection",lambda:(chain,None))
    @contextmanager
    def failing_db():
        with main.get_db() as conn:
            class FailingConnection:
                def execute(self, sql, *args):
                    if "UPDATE voting_credentials SET consumed_at" in sql:
                        raise sqlite3.OperationalError("simulated disk failure")
                    return conn.execute(sql,*args)
                def commit(self):
                    conn.commit()
            yield FailingConnection()
    service.db = failing_db
    service.reconcile()
    restarted = main.voting_service()
    assert restarted.status(identifier)["status"] == "SUBMITTED"
    monkeypatch.setattr(restarted,"connection",lambda:(chain,None))
    restarted.reconcile()
    assert restarted.status(identifier)["success"]
    assert restarted.issue(identifier) is None
    assert restarted.reserve(identifier,raw)[1] is False
    with main.get_db() as conn:
        assert conn.execute("SELECT raw_transaction FROM vote_attempts WHERE id=?",(attempt["id"],)).fetchone()[0] is None


def test_confirmed_vote_remains_spent_even_if_credential_revoked(monkeypatch):
    identifier = voter()
    service = main.voting_service()
    submitted(service,identifier)
    monkeypatch.setattr(service,"connection",lambda:(receipt_chain(),None))
    service.reconcile()
    with main.get_db() as conn:
        conn.execute("UPDATE voting_credentials SET revoked_at='now'")
        conn.commit()
    assert service.issue(identifier) is None


def test_reverted_transaction_allows_safe_retry(monkeypatch):
    identifier = voter()
    service = main.voting_service()
    raw,_ = submitted(service,identifier)
    monkeypatch.setattr(service,"connection",lambda:(receipt_chain(0),None))
    service.reconcile()
    assert service.status(identifier)["status"] == "FAILED"
    assert service.reserve(identifier,raw)[1]


@pytest.mark.parametrize("case",["confirmations","reorg","chain"])
def test_unfinalized_receipt_never_shows_success(monkeypatch,case):
    identifier = voter()
    service = main.voting_service()
    submitted(service,identifier)
    chain = receipt_chain()
    if case=="confirmations":
        monkeypatch.setattr(main.settings,"BLOCKCHAIN_CONFIRMATIONS",2)
    elif case=="reorg":
        chain.eth.get_block.return_value={"hash":b"other"}
    else:
        chain.eth.chain_id=1
    monkeypatch.setattr(service,"connection",lambda:(chain,None))
    service.reconcile()
    assert not service.status(identifier)["success"]
    assert service.issue(identifier) is None


def test_expired_unsigned_reservation_can_recover():
    identifier=voter()
    service=main.voting_service()
    raw=service.issue(identifier)
    attempt,_=service.reserve(identifier,raw)
    with main.get_db() as conn:
        conn.execute("UPDATE vote_attempts SET created_at='2020-01-01' WHERE id=?",(attempt["id"],))
        conn.commit()
    service.reconcile()
    assert service.reserve(identifier,raw)[1]


@pytest.mark.parametrize("case",["expired","other_voter","other_election","unapproved"])
def test_invalid_authorizations_rejected(case):
    identifier=voter()
    other=voter("other")
    service=main.voting_service()
    raw=service.issue(identifier)
    with main.get_db() as conn:
        if case=="expired": conn.execute("UPDATE voting_credentials SET expires_at='2020-01-01'")
        if case=="other_election": conn.execute("UPDATE voting_credentials SET election_id='other'")
        if case=="unapproved": conn.execute("UPDATE voters SET id_verified=0 WHERE voter_id=?",(identifier,))
        conn.commit()
    with pytest.raises(HTTPException):
        service.reserve(other if case=="other_voter" else identifier,raw)


def test_challenge_survives_restart_and_is_consumed_atomically():
    challenge=active_liveness.issue(main.get_db,"voter")
    with main.get_db() as conn:
        conn.execute("UPDATE liveness_challenges SET created_at=created_at-5")
        conn.commit()
    main.init_db()
    def consume(_):
        try: return active_liveness.consume(main.get_db,challenge["challenge_id"],"voter",16)
        except HTTPException: return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes=list(pool.map(consume,range(4)))
    assert sum(value is not None for value in outcomes)==1


@pytest.mark.parametrize("case",["expired","voter","too_fast"])
def test_challenge_binding_and_expiry(case):
    item=active_liveness.issue(main.get_db,"voter")
    with main.get_db() as conn:
        if case=="expired": conn.execute("UPDATE liveness_challenges SET expires_at=0")
        if case=="voter": conn.execute("UPDATE liveness_challenges SET created_at=created_at-5")
        conn.commit()
    with pytest.raises(HTTPException):
        active_liveness.consume(main.get_db,item["challenge_id"],"other" if case=="voter" else "voter")


def test_repeated_and_cross_challenge_frames_rejected():
    images=[main.decode_base64_image(frame) for frame in VALID_CHALLENGE_IMAGES]
    with pytest.raises(HTTPException): active_liveness.reject_replays(main.get_db,[images[0]]*24)
    active_liveness.reject_replays(main.get_db,images)
    with pytest.raises(HTTPException): active_liveness.reject_replays(main.get_db,images)


@pytest.mark.parametrize("action",["left_then_blink","right_then_blink","blink_then_left","blink_then_right"])
def test_old_head_turn_challenges_require_refresh(action):
    with pytest.raises(HTTPException, match="changed"):
        active_liveness.validate(action, [make_landmarks(0)]*16, lambda _: .3, main._has_blink_sequence)


def test_blink_check_accepts_a_stationary_head_but_requires_eye_closure():
    frames = [make_landmarks(0) for _ in range(16)]
    ears = iter([value for value in [.3]*3+[.12]*4+[.3]*9 for _ in range(2)])
    active_liveness.validate("blink_once", frames, lambda _: next(ears), main._has_blink_sequence)
    with pytest.raises(HTTPException, match="eye movement"):
        active_liveness.validate("blink_once", frames, lambda _: .3, main._has_blink_sequence)


@pytest.mark.parametrize("case",["no_face","multiple","mismatch","service_failure"])
def test_login_fails_closed(case):
    identifier=voter()
    with TestClient(main.app) as client:
        challenge=issue_liveness_challenge(client,identifier)
        with patch("main.get_face_details") as details,patch("main.compare_faces") as compare:
            if case=="multiple": details.side_effect=HTTPException(400,"Only one face must be visible.")
            elif case=="service_failure": details.side_effect=HTTPException(503,"Face service unavailable")
            elif case=="mismatch":
                details.return_value=(np.ones(128),make_landmarks(0))
                compare.return_value=(False,.8)
            else: details.return_value=None
            response=client.post("/api/v1/verify-face",json={"voter_id":identifier,"challenge_id":challenge,"images_base64":VALID_CHALLENGE_IMAGES})
        assert response.status_code in (400,401,503)
        assert "auth_token" not in response.cookies


def test_identity_substitution_in_middle_is_rejected():
    identifier=voter()
    with TestClient(main.app) as client:
        challenge=issue_liveness_challenge(client,identifier)
        with patch("main.get_face_details") as details,patch("main.compare_faces") as compare,patch("main.calculate_ear") as ear:
            mock_live_capture(details,ear)
            compare.side_effect=[(True,.1)]*5+[(False,.8)]
            response=client.post("/api/v1/verify-face",json={"voter_id":identifier,"challenge_id":challenge,"images_base64":VALID_CHALLENGE_IMAGES})
        assert response.status_code==401


@pytest.mark.parametrize("case", ["timeout", "partial", "native_rejection", "worker_crash"])
def test_parallel_analysis_cannot_authenticate_on_failure(case, monkeypatch):
    from face_workers import FrameError
    identifier = voter()
    analysis = MagicMock()
    if case == "partial":
        analysis.return_value = [(np.ones(128), make_landmarks(0))]
    else:
        analysis.side_effect = FrameError("Only one face must be visible.") if case == "native_rejection" else RuntimeError(case)
    monkeypatch.setattr(main._face_workers, "analyze", analysis)
    with TestClient(main.app) as client:
        challenge = issue_liveness_challenge(client, identifier)
        response = client.post("/api/v1/verify-face", json={"voter_id": identifier, "challenge_id": challenge, "images_base64": VALID_CHALLENGE_IMAGES})
        assert response.status_code == (400 if case == "native_rejection" else 503)
        assert "auth_token" not in response.cookies


def test_challenge_preflight_avoids_wasted_capture():
    identifier = voter()
    with TestClient(main.app) as client:
        assert client.get("/api/v1/liveness/challenge", params={"voter_id": "missing"}).status_code == 404
        with main.get_db() as conn:
            conn.execute("UPDATE voters SET id_verified=0 WHERE voter_id=?", (identifier,))
            conn.commit()
        assert client.get("/api/v1/liveness/challenge", params={"voter_id": identifier}).status_code == 403
        with main.get_db() as conn:
            assert conn.execute("SELECT count(*) FROM liveness_challenges").fetchone()[0] == 0
        assert main._cv_slots.acquire(blocking=False)
        try:
            response = client.get("/api/v1/liveness/challenge", params={"voter_id": identifier})
            assert response.status_code == 503
            assert response.headers["Retry-After"] == "2"
        finally:
            main._cv_slots.release()


def test_origin_protection_and_validation_do_not_echo_secrets():
    with TestClient(main.app) as client:
        assert client.post("/api/v1/auth/logout",headers={"Origin":"https://evil.example"}).status_code==403
        secret="PRIVATE-BIOMETRIC-PAYLOAD"
        response=client.post("/api/v1/verify-face",json={"voter_id":"x","challenge_id":"x","images_base64":[secret]})
        assert response.status_code==422
        assert secret not in response.text
        assert client.post("/api/v1/register-user",content=b"x"*12_000_001).status_code==413


def test_oversized_decoded_image_rejected():
    image=np.zeros((1,3000,3),dtype=np.uint8)
    _, encoded=cv2.imencode(".png",image)
    with pytest.raises(ValueError): main.decode_base64_image(base64.b64encode(encoded).decode())


def test_account_revocation_and_refresh_logout():
    identifier=voter()
    with TestClient(main.app) as client:
        original=main.create_jwt(identifier,"user")
        client.cookies.set("auth_token",original)
        refreshed=client.post("/api/v1/auth/refresh")
        assert refreshed.status_code==200
        refreshed_token=refreshed.cookies["auth_token"]
        client.cookies.clear()
        client.cookies.set("auth_token",original)
        assert client.post("/api/v1/auth/logout").status_code==200
        with pytest.raises(HTTPException): main.decode_jwt(refreshed_token)
        token=main.create_jwt(identifier,"user")
        with main.get_db() as conn:
            conn.execute("UPDATE voters SET session_version=session_version+1 WHERE voter_id=?",(identifier,))
            conn.commit()
        with pytest.raises(HTTPException): main.decode_jwt(token)


def test_deleted_voter_cannot_reregister_or_lose_ballot_history():
    identifier=voter()
    service=main.voting_service()
    submitted(service,identifier)
    with TestClient(main.app) as client:
        assert client.delete(f"/api/v1/admin/voters/{identifier}",headers={"Authorization":f"Bearer {get_admin_token()}"}).status_code==200
        with patch("main.get_enrollment_embedding",return_value=np.ones(128)):
            response=client.post("/api/v1/register-user",json={"voter_id":identifier,"images_base64":VALID_CHALLENGE_IMAGES[:5]})
        assert response.status_code==403
    assert service.status(identifier)["status"]=="SUBMITTED"


def test_legacy_uncertain_credential_is_quarantined_on_migration():
    identifier=voter()
    with main.get_db() as conn:
        conn.execute("""INSERT INTO voting_credentials
            (credential_hash,voter_id,election_id,issued_at,expires_at,revoked_at)
            VALUES ('legacy',?,?,'2026-01-01','2026-01-02','2026-01-02')""",
            (identifier,main._current_election_id()))
        conn.commit()
    main.init_db()
    assert main.issue_voting_credential(identifier) is None
    assert main.voting_service().status(identifier)["status"]=="SUBMITTED"


def test_native_detector_rejects_blank_frame():
    assert main.get_face_details(np.zeros((240,320,3),dtype=np.uint8)) is None


def test_blink_requires_open_closed_open():
    assert not main._has_blink_sequence([(.3,.3)]*12)
    assert not main._has_blink_sequence([(.1,.1)]*6+[(.3,.3)]*6)
    assert not main._has_blink_sequence([(.3,.3)]*4+[(.1,.3)]+[(.3,.3)]*7)
    assert main._has_blink_sequence([(.3,.3)]*4+[(.1,.1)]+[(.3,.3)]*7)


def test_audit_uses_real_logs_and_signs_all_ledger_fields(monkeypatch):
    from web3.datastructures import AttributeDict
    import hashlib
    chain=receipt_chain()
    contract=MagicMock()
    contract.functions.getElectionState().call.return_value=2
    contract.functions.countCandidates().call.return_value=1
    contract.functions.getCandidate(1).call.return_value=(1,"Alice","A",1)
    event=AttributeDict.recursive({"transactionHash":bytes.fromhex("12"*32),
        "blockNumber":10,"blockHash":bytes.fromhex("34"*32),
        "args":{"candidateId":1,"credential":bytes.fromhex("56"*32),"timestamp":1_700_000_000}})
    contract.events.VoteCast.get_logs.return_value=[event]
    chain.eth.get_block.return_value=AttributeDict({"hash":bytes.fromhex("34"*32)})
    monkeypatch.setattr(main,"_get_blockchain_contract",lambda:(chain,contract))
    with TestClient(main.app) as client:
        response=client.get("/api/v1/admin/election/audit",headers={"Authorization":f"Bearer {get_admin_token()}"})
        assert response.status_code==200,response.text
        report=response.json()
        assert report["transaction_logs"][0]["block_number"]==10
        assert report["transaction_logs"][0]["candidate_id"]==1
        assert report["audit_digest"]=="0x"+hashlib.sha256(report["canonical_payload"].encode()).hexdigest()
        assert report["signature_algorithm"]=="HMAC-SHA256"
        contract.events.VoteCast.get_logs.assert_called_with(from_block=0,to_block=10)
