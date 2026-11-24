-- ============================================================================
-- Multimodal Blockchain Voting System - SQLite Database Schema
-- ============================================================================
-- This schema defines all local SQLite tables used by the FastAPI
-- face-authentication backend, voter registry, credentials, and voting service.
-- ============================================================================

PRAGMA foreign_keys = ON;

-- ----------------------------------------------------------------------------
-- 1. Voters Table
-- Holds registered voters, biometrics (face encodings), student info & status.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS voters (
    voter_id                TEXT PRIMARY KEY NOT NULL,
    role                    TEXT NOT NULL DEFAULT 'user',
    face_encoding           TEXT NOT NULL DEFAULT '',
    name                    TEXT,
    usn                     TEXT,
    branch                  TEXT NOT NULL DEFAULT '',
    class_name              TEXT NOT NULL DEFAULT '',
    batch                   TEXT NOT NULL DEFAULT '',
    validity                TEXT,
    dob                     TEXT,
    student_name            TEXT NOT NULL DEFAULT '',
    id_verified             INTEGER NOT NULL DEFAULT 0,
    verified_by             TEXT,
    verified_at             TEXT,
    deleted                 INTEGER NOT NULL DEFAULT 0,
    voted                   INTEGER NOT NULL DEFAULT 0,
    last_voted_election_id  TEXT,
    pending_face_encoding   TEXT,
    face_updated_at         TEXT,
    session_version         INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_voters_role ON voters(role);

-- ----------------------------------------------------------------------------
-- 2. Deleted Voters
-- Audit tombstone table tracking removed voter accounts.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS deleted_voters (
    voter_id    TEXT PRIMARY KEY NOT NULL,
    deleted_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ----------------------------------------------------------------------------
-- 3. Administrators Table
-- Stores admin accounts, hashed credentials, and session invalidation version.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admins (
    admin_id        TEXT PRIMARY KEY NOT NULL,
    password_hash   TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    is_active       INTEGER NOT NULL DEFAULT 1,
    session_version INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_admins_active ON admins(is_active);

-- ----------------------------------------------------------------------------
-- 4. Election Metadata
-- Stores election cycle display names and timestamps per contract address.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS election_metadata (
    election_id TEXT PRIMARY KEY NOT NULL,
    name        TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL
);

-- ----------------------------------------------------------------------------
-- 5. Active Election
-- Points to the currently active smart contract deployment address.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS active_election (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    contract_address    TEXT NOT NULL
);

-- ----------------------------------------------------------------------------
-- 6. Voting Credentials
-- One-time, short-lived cryptographic credentials issued upon face authentication.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS voting_credentials (
    credential_hash TEXT PRIMARY KEY NOT NULL,
    voter_id        TEXT NOT NULL,
    election_id     TEXT NOT NULL DEFAULT '',
    issued_at       TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    consumed_at     TEXT,
    revoked_at      TEXT,
    tx_hash         TEXT,
    issuance_nonce  TEXT
);

CREATE INDEX IF NOT EXISTS idx_credential_voter_election
    ON voting_credentials(voter_id, election_id);

-- ----------------------------------------------------------------------------
-- 7. Vote Attempts (Outbox & Transaction Audit)
-- Records durable ballot reservations, relayer transactions, and block hashes.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS vote_attempts (
    id              TEXT PRIMARY KEY,
    voter_id        TEXT NOT NULL,
    election_id     TEXT NOT NULL,
    credential_hash TEXT NOT NULL,
    status          TEXT NOT NULL CHECK(status IN ('PENDING', 'SUBMITTED', 'CONFIRMED', 'FAILED')),
    created_at      TEXT NOT NULL,
    tx_hash         TEXT,
    raw_transaction TEXT,
    chain_id        INTEGER,
    relayer         TEXT,
    nonce           INTEGER,
    block_number    INTEGER,
    block_hash      TEXT,
    failure         TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_ballot_per_voter
    ON vote_attempts(voter_id, election_id) WHERE status != 'FAILED';

-- ----------------------------------------------------------------------------
-- 8. Relayer Nonces
-- Tracks sequential nonces for the relayer wallet submitting transactions.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS relayer_nonces (
    chain_id    INTEGER,
    relayer     TEXT,
    next_nonce  INTEGER NOT NULL,
    PRIMARY KEY(chain_id, relayer)
);

-- ----------------------------------------------------------------------------
-- 9. Liveness Challenges
-- One-time interactive liveness challenge sessions (e.g. blink check).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS liveness_challenges (
    id          TEXT PRIMARY KEY,
    voter_id    TEXT NOT NULL,
    action      TEXT NOT NULL,
    created_at  REAL NOT NULL,
    expires_at  REAL NOT NULL,
    used        INTEGER NOT NULL DEFAULT 0,
    min_seconds REAL NOT NULL DEFAULT 3,
    frame_count INTEGER NOT NULL DEFAULT 0
);

-- ----------------------------------------------------------------------------
-- 10. Liveness Frames
-- Frame fingerprints to reject video replay attacks during biometric check.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS liveness_frames (
    fingerprint TEXT PRIMARY KEY,
    expires_at  REAL NOT NULL
);

-- ----------------------------------------------------------------------------
-- 11. Revoked Sessions
-- Blacklist of revoked JWT token identifiers (jti) until token expiration.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS revoked_sessions (
    jti         TEXT PRIMARY KEY,
    expires_at  REAL NOT NULL
);
