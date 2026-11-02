"""Durable ballot reservations and a signed-transaction outbox.

All network work happens outside SQLite transactions. An uncertain broadcast
never releases a voter's reservation. The relayer key must be exclusive to this
service and all workers must share the same database.
"""
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from web3 import Web3
from web3.exceptions import TransactionNotFound

log = logging.getLogger("vote-relay")


def now():
    return datetime.now(timezone.utc).isoformat()


def migrate(conn):
    columns = {row[1] for row in conn.execute("PRAGMA table_info(voting_credentials)")}
    if "issuance_nonce" not in columns:
        conn.execute("ALTER TABLE voting_credentials ADD COLUMN issuance_nonce TEXT")
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS credential_voter_election
            ON voting_credentials(voter_id, election_id);
        CREATE TABLE IF NOT EXISTS vote_attempts (
            id TEXT PRIMARY KEY, voter_id TEXT NOT NULL, election_id TEXT NOT NULL,
            credential_hash TEXT NOT NULL, status TEXT NOT NULL
                CHECK(status IN ('PENDING','SUBMITTED','CONFIRMED','FAILED')),
            created_at TEXT NOT NULL, tx_hash TEXT, raw_transaction TEXT,
            chain_id INTEGER, relayer TEXT, nonce INTEGER, block_number INTEGER,
            block_hash TEXT, failure TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS one_ballot_per_voter
            ON vote_attempts(voter_id, election_id) WHERE status != 'FAILED';
        CREATE TABLE IF NOT EXISTS relayer_nonces (
            chain_id INTEGER, relayer TEXT, next_nonce INTEGER NOT NULL,
            PRIMARY KEY(chain_id, relayer)
        );
    """)
    # The old relayer did not persist hashes before broadcast. An unused legacy
    # row is NOT proof that no ballot was accepted, even if it was later revoked.
    # Quarantine that election/voter pair instead of silently issuing a new vote.
    conn.execute("""INSERT OR IGNORE INTO vote_attempts
        (id,voter_id,election_id,credential_hash,status,created_at,failure)
        SELECT 'legacy-' || credential_hash,voter_id,election_id,credential_hash,
               'SUBMITTED',issued_at,'Legacy authorization requires ledger review'
        FROM voting_credentials WHERE issuance_nonce IS NULL AND consumed_at IS NULL""")


class VotingService:
    def __init__(self, db, settings, abi, contract_address=None):
        self.db, self.settings, self.abi = db, settings, abi
        self.contract_address = contract_address or (
            lambda: self.settings.BLOCKCHAIN_CONTRACT_ADDRESS
        )

    @property
    def election(self):
        return (self.contract_address() or "default").strip().lower()

    def credential(self, nonce):
        # A random nonce allows safe re-delivery without storing the bearer secret.
        return hmac.new(self.settings.resolved_secret_key.encode(),
                        ("voting-credential-v1:" + nonce).encode(), hashlib.sha256).hexdigest()

    def issue(self, voter_id):
        with self.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            voter = conn.execute("SELECT * FROM voters WHERE voter_id=?", (voter_id,)).fetchone()
            if not voter or voter["deleted"] or not voter["id_verified"] or voter["role"] != "user":
                raise HTTPException(403, "Voter is not eligible.")
            if voter["last_voted_election_id"] == self.election or conn.execute(
                "SELECT 1 FROM voting_credentials WHERE voter_id=? AND election_id=? AND consumed_at IS NOT NULL",
                (voter_id, self.election),
            ).fetchone() or conn.execute(
                "SELECT 1 FROM vote_attempts WHERE voter_id=? AND election_id=? AND status!='FAILED'",
                (voter_id, self.election),
            ).fetchone():
                return None
            current = conn.execute("""SELECT * FROM voting_credentials WHERE voter_id=?
                AND election_id=? AND consumed_at IS NULL AND revoked_at IS NULL
                AND expires_at>? ORDER BY issued_at DESC LIMIT 1""",
                (voter_id, self.election, now())).fetchone()
            if current and current["issuance_nonce"]:
                raw = self.credential(current["issuance_nonce"])
                if hashlib.sha256(bytes.fromhex(raw)).hexdigest() == current["credential_hash"]:
                    return raw
            conn.execute("""UPDATE voting_credentials SET revoked_at=? WHERE voter_id=?
                AND election_id=? AND consumed_at IS NULL AND revoked_at IS NULL""",
                (now(), voter_id, self.election))
            nonce = secrets.token_hex(32)
            raw = self.credential(nonce)
            digest = hashlib.sha256(bytes.fromhex(raw)).hexdigest()
            expires = (datetime.now(timezone.utc) + timedelta(
                minutes=self.settings.VOTING_CREDENTIAL_TTL_MINUTES)).isoformat()
            conn.execute("""INSERT INTO voting_credentials
                (credential_hash,voter_id,election_id,issued_at,expires_at,issuance_nonce)
                VALUES (?,?,?,?,?,?)""", (digest,voter_id,self.election,now(),expires,nonce))
            conn.commit()
        log.info("Voting authorization issued")
        return raw

    def connection(self):
        web3 = Web3(Web3.HTTPProvider(self.settings.BLOCKCHAIN_RPC_URL,
                                    request_kwargs={"timeout": 10}))
        if not web3.is_connected():
            raise HTTPException(503, "Blockchain node is unavailable.")
        contract_address = self.contract_address()
        if not contract_address:
            raise HTTPException(503, "Blockchain contract address is not configured.")
        address = Web3.to_checksum_address(contract_address)
        contract = web3.eth.contract(address=address, abi=self.abi)
        return web3, contract

    def reserve(self, voter_id, raw):
        try:
            credential = bytes.fromhex(raw)
            if len(credential) != 32:
                raise ValueError()
        except ValueError:
            raise HTTPException(401, "Invalid voting credential.")
        digest = hashlib.sha256(credential).hexdigest()
        with self.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM voting_credentials WHERE credential_hash=?", (digest,)).fetchone()
            if not row or row["voter_id"] != voter_id or row["election_id"] != self.election:
                raise HTTPException(403, "Invalid voting authorization.")
            previous = conn.execute("SELECT * FROM vote_attempts WHERE voter_id=? AND election_id=? AND status!='FAILED'",
                                    (voter_id,self.election)).fetchone()
            if previous:
                return dict(previous), False
            voter = conn.execute("SELECT * FROM voters WHERE voter_id=?", (voter_id,)).fetchone()
            if not voter or voter["deleted"] or not voter["id_verified"]:
                raise HTTPException(403, "Voter is not eligible.")
            if voter["last_voted_election_id"] == self.election or conn.execute(
                "SELECT 1 FROM voting_credentials WHERE voter_id=? AND election_id=? AND consumed_at IS NOT NULL",
                (voter_id,self.election)).fetchone():
                raise HTTPException(409, "This voter has already voted.")
            if row["revoked_at"] or row["expires_at"] <= now():
                raise HTTPException(401, "Voting authorization expired. Refresh your session.")
            attempt = dict(id=secrets.token_hex(16), voter_id=voter_id, election_id=self.election,
                           credential_hash=digest,status="PENDING",created_at=now())
            conn.execute("""INSERT INTO vote_attempts
                (id,voter_id,election_id,credential_hash,status,created_at) VALUES
                (:id,:voter_id,:election_id,:credential_hash,:status,:created_at)""",attempt)
            conn.commit()
        return attempt, True

    def prepare(self, attempt, candidate_id, raw):
        web3, contract = self.connection()
        account = web3.eth.account.from_key(self.settings.BLOCKCHAIN_RELAYER_PRIVATE_KEY)
        expected = self.settings.BLOCKCHAIN_RELAYER_ADDRESS or account.address
        if account.address.lower() != expected.lower() or contract.functions.relayer().call().lower() != account.address.lower():
            raise HTTPException(503, "Blockchain relayer configuration is invalid.")
        digest = Web3.keccak(bytes.fromhex(raw))
        call = contract.functions.vote(candidate_id, digest)
        gas = call.estimate_gas({"from": account.address})
        chain_id = web3.eth.chain_id
        observed_nonce = web3.eth.get_transaction_count(account.address, "pending")
        transaction = call.build_transaction({"from": account.address, "chainId": chain_id,
            "nonce": observed_nonce, "gas": int(gas * 1.2), "gasPrice": web3.eth.gas_price})
        # Only local signing and SQL while locked. Nonces and signed bytes commit
        # together; different processes cannot reserve the same nonce.
        with self.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            saved = conn.execute("SELECT next_nonce FROM relayer_nonces WHERE chain_id=? AND relayer=?",
                                 (chain_id,account.address.lower())).fetchone()
            nonce = max(observed_nonce, saved[0] if saved else 0)
            transaction["nonce"] = nonce
            signed = account.sign_transaction(transaction)
            signed_bytes = getattr(signed,"raw_transaction",None)
            if signed_bytes is None:
                signed_bytes = signed.rawTransaction
            tx_hash = Web3.to_hex(Web3.keccak(signed_bytes))
            updated = conn.execute("""UPDATE vote_attempts SET status='SUBMITTED',tx_hash=?,
                raw_transaction=?,chain_id=?,relayer=?,nonce=? WHERE id=? AND status='PENDING'""",
                (tx_hash,bytes(signed_bytes).hex(),chain_id,account.address.lower(),nonce,attempt["id"]))
            if updated.rowcount != 1:
                raise HTTPException(409, "Submission reservation expired. Check vote status.")
            conn.execute("""INSERT INTO relayer_nonces VALUES (?,?,?) ON CONFLICT(chain_id,relayer)
                DO UPDATE SET next_nonce=excluded.next_nonce""",(chain_id,account.address.lower(),nonce+1))
            conn.commit()
        log.info("Signed vote transaction persisted: %s", tx_hash)
        # A crash or error here is uncertain, NEVER FAILED.
        try:
            web3.eth.send_raw_transaction(signed_bytes)
        except Exception:
            log.warning("Broadcast uncertain; reconciliation will check %s", tx_hash)

    def cast(self, voter_id, candidate_id, raw):
        attempt, fresh = self.reserve(voter_id, raw)
        if fresh:
            try:
                self.prepare(attempt,candidate_id,raw)
            except Exception:
                with self.db() as conn:
                    # Only a never-signed reservation may be released.
                    conn.execute("UPDATE vote_attempts SET status='FAILED',failure='Preparation failed' WHERE id=? AND status='PENDING'",
                                 (attempt["id"],))
                    conn.commit()
                log.warning("Vote preparation failed; no new transaction broadcast")
        self.reconcile(attempt["id"])
        return {**self.status(voter_id), "replayed": not fresh}

    def status(self, voter_id):
        with self.db() as conn:
            row = conn.execute("""SELECT * FROM vote_attempts WHERE voter_id=? AND election_id=?
                ORDER BY created_at DESC LIMIT 1""",(voter_id,self.election)).fetchone()
        state = row["status"] if row else "NONE"
        return {"status":state,"success":state=="CONFIRMED", "credential_consumed":state=="CONFIRMED",
                "transaction_hash":row["tx_hash"] if row else None,
                "tx_hash":row["tx_hash"] if row else None,
                "detail": "Transaction could not be prepared or reverted. Refresh before retrying." if state=="FAILED"
                    else "Awaiting blockchain confirmation." if state in ("PENDING","SUBMITTED") else None}

    def reconcile(self, attempt_id=None):
        cutoff = (datetime.now(timezone.utc)-timedelta(seconds=120)).isoformat()
        with self.db() as conn:
            conn.execute("""UPDATE vote_attempts SET status='FAILED',failure='Preparation interrupted'
                WHERE status='PENDING' AND created_at<?""",(cutoff,))
            conn.commit()
            rows = conn.execute("""SELECT * FROM vote_attempts WHERE status='SUBMITTED'
                AND election_id=? AND (? IS NULL OR id=?)""",(self.election,attempt_id,attempt_id)).fetchall()
        if not rows:
            return
        try:
            web3, _ = self.connection()
            chain_id = web3.eth.chain_id
        except Exception:
            return
        for row in rows:
            if chain_id != row["chain_id"]:
                continue
            try:
                receipt = web3.eth.get_transaction_receipt(row["tx_hash"])
                if web3.eth.block_number - receipt["blockNumber"] + 1 < self.settings.BLOCKCHAIN_CONFIRMATIONS:
                    continue
                block = web3.eth.get_block(receipt["blockNumber"])
                if block["hash"] != receipt["blockHash"]:
                    continue
                confirmed = int(receipt["status"]) == 1
                with self.db() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute("""UPDATE vote_attempts SET status=?,raw_transaction=NULL,
                        block_number=?,block_hash=?,failure=? WHERE id=? AND status='SUBMITTED'""",
                        ("CONFIRMED" if confirmed else "FAILED", receipt["blockNumber"],
                         Web3.to_hex(receipt["blockHash"]),None if confirmed else "Transaction reverted",row["id"]))
                    if confirmed:
                        conn.execute("UPDATE voting_credentials SET consumed_at=?,tx_hash=? WHERE credential_hash=?",
                                     (now(),row["tx_hash"],row["credential_hash"]))
                        conn.execute("UPDATE voters SET voted=1,last_voted_election_id=? WHERE voter_id=?",
                                     (row["election_id"],row["voter_id"]))
                    conn.commit()
                log.info("Vote transaction %s: %s",row["tx_hash"],"confirmed" if confirmed else "reverted")
            except TransactionNotFound:
                # Identical bytes/hash/nonce only. An RPC outage, dropped tx or a
                # conflicting nonce never permits a replacement authorization.
                if row["raw_transaction"]:
                    try:
                        web3.eth.send_raw_transaction(bytes.fromhex(row["raw_transaction"]))
                    except Exception:
                        pass  # Retain SUBMITTED for later reconciliation.
            except Exception:
                log.warning("Receipt reconciliation deferred for %s", row["tx_hash"])
