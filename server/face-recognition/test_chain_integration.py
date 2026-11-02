"""Real signed transactions on an isolated ephemeral Ganache chain; no live funds."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from eth_account import Account
from fastapi.testclient import TestClient
from web3 import Web3

import main
from test_main import get_admin_token, setup_database
from test_security import voter

get_blockchain_contract = main._get_blockchain_contract


def test_real_chain_submission_concurrency_and_restart_recovery(monkeypatch):
    root=Path(__file__).resolve().parents[2]
    artifact_path=root/"src/contracts/Voting.json"
    if not shutil.which("node") or not artifact_path.exists() or not (root/"node_modules/ganache").exists():
        pytest.skip("Run pnpm install and pnpm run compile:contracts first")
    account=Account.create()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0))
        port=sock.getsockname()[1]
    script="""const ganache=require('ganache');
    ganache.server({logging:{quiet:true},chain:{chainId:1337},wallet:{accounts:[{
    secretKey:process.env.INTEGRATION_KEY,balance:'0x3635c9adc5dea00000'}]}})
    .listen(Number(process.env.INTEGRATION_PORT),'127.0.0.1');"""
    env={**os.environ,"INTEGRATION_KEY":Web3.to_hex(account.key),"INTEGRATION_PORT":str(port)}
    process=subprocess.Popen(["node","-e",script],cwd=root,env=env,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
    try:
        web3=Web3(Web3.HTTPProvider(f"http://127.0.0.1:{port}",request_kwargs={"timeout":5}))
        for _ in range(100):
            if web3.is_connected(): break
            if process.poll() is not None: pytest.fail("Ganache failed to start")
            time.sleep(.1)
        assert web3.is_connected()
        artifact=json.loads(artifact_path.read_text())
        factory=web3.eth.contract(abi=artifact["abi"],bytecode=artifact["bytecode"])
        deployed=web3.eth.wait_for_transaction_receipt(factory.constructor(account.address).transact({"from":account.address}))
        contract=web3.eth.contract(address=deployed.contractAddress,abi=artifact["abi"])
        contract.functions.addCandidate("Alice","A").transact({"from":account.address})
        contract.functions.addCandidate("Bob","B").transact({"from":account.address})
        contract.functions.startElection().transact({"from":account.address})
        monkeypatch.setattr(main.settings,"BLOCKCHAIN_RPC_URL",f"http://127.0.0.1:{port}")
        monkeypatch.setattr(main.settings,"BLOCKCHAIN_CONTRACT_ADDRESS",contract.address)
        monkeypatch.setattr(main.settings,"BLOCKCHAIN_RELAYER_ADDRESS",account.address)
        monkeypatch.setattr(main.settings,"BLOCKCHAIN_RELAYER_PRIVATE_KEY",Web3.to_hex(account.key))
        service=main.voting_service()
        identifier=voter("chain_voter")
        raw=service.issue(identifier)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:service.cast(identifier,1,raw),range(2)))
        assert sorted(result["replayed"] for result in results)==[False,True]
        service.reconcile()
        assert service.status(identifier)["status"]=="CONFIRMED"
        assert contract.functions.getCandidate(1).call()[3]==1
        assert contract.functions.checkCredential(Web3.keccak(bytes.fromhex(raw))).call()
        assert main.voting_service().issue(identifier) is None

        # Crash after the signed outbox commits, before successful broadcast.
        second=voter("recover_voter")
        raw2=service.issue(second)
        attempt,_=service.reserve(second,raw2)
        real_connection=service.connection
        connection=real_connection()
        with monkeypatch.context() as local:
            local.setattr(service,"connection",lambda:connection)
            local.setattr(connection[0].eth,"send_raw_transaction",lambda _: (_ for _ in ()).throw(TimeoutError()))
            service.prepare(attempt,2,raw2)
        assert contract.functions.getCandidate(2).call()[3]==0
        restarted=main.voting_service()
        restarted.reconcile()  # Rebroadcasts the identical durable transaction.
        restarted.reconcile()  # Canonical receipt confirms it.
        assert restarted.status(second)["success"]
        assert contract.functions.getCandidate(2).call()[3]==1
        assert restarted.issue(second) is None

        # Independent voters use distinct durable nonces across concurrent workers.
        ids=[voter("parallel_a"),voter("parallel_b")]
        tokens=[service.issue(item) for item in ids]
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda pair:main.voting_service().cast(pair[0],1,pair[1]),zip(ids,tokens)))
        service.reconcile()
        assert all(service.status(item)["success"] for item in ids)
        assert contract.functions.getCandidate(1).call()[3]==3

        contract.functions.endElection().transact({"from":account.address})
        next_deployment=web3.eth.wait_for_transaction_receipt(
            factory.constructor(account.address).transact({"from":account.address})
        )
        next_contract=web3.eth.contract(
            address=next_deployment.contractAddress,abi=artifact["abi"]
        )
        monkeypatch.setattr(
            main, "_get_blockchain_contract", get_blockchain_contract
        )
        with TestClient(main.app) as client:
            response=client.post(
                "/api/v1/admin/election/activate",
                headers={"Authorization":f"Bearer {get_admin_token()}"},
                json={
                    "contract_address":next_contract.address,
                    "owner_address":account.address,
                    "name":"Next election",
                },
            )
        assert response.status_code==200, response.text
        assert main._current_election_id()==next_contract.address.lower()
        assert main.voting_service().election==next_contract.address.lower()
        assert next_contract.functions.getElectionState().call()==0
    finally:
        process.terminate()
        process.wait(timeout=10)
