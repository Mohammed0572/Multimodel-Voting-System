# Local SQLite Database Setup & Queries

This directory contains standalone SQL scripts to initialize, seed, and query the local SQLite database for the **Multimodal Blockchain Voting System**.

---

## Files in this Directory

| File | Description |
|---|---|
| [`schema.sql`](./schema.sql) | Complete DDL to create all 11 tables and performance indexes (`voters`, `voting_credentials`, `admins`, `vote_attempts`, `liveness_challenges`, etc.). |
| [`queries.sql`](./queries.sql) | Curated queries for voter eligibility, turnout analytics, credential verification, and transaction audit trails. |
| [`seed.sql`](./seed.sql) | Sample demo records (default admin, sample CSBS student voters, and election metadata). |

---

## Quick Start

### 1. Default Database Location
The FastAPI backend reads and writes to:
```text
server/face-recognition/face_voter_db.sqlite
```

### 2. Create and Initialize Database

#### Using SQLite CLI:
```bash
# Create and apply schema
sqlite3 server/face-recognition/face_voter_db.sqlite < database/schema.sql

# (Optional) Insert demo seed data
sqlite3 server/face-recognition/face_voter_db.sqlite < database/seed.sql
```

#### Using Python:
```python
import sqlite3

conn = sqlite3.connect("server/face-recognition/face_voter_db.sqlite")
with open("database/schema.sql") as f:
    conn.executescript(f.read())
conn.close()
print("Database schema initialized successfully.")
```

#### Using GUI Tools:
Open `server/face-recognition/face_voter_db.sqlite` in **DB Browser for SQLite** or the VS Code **SQLite Viewer** extension, open `schema.sql`, and click **Execute SQL**.

---

## Running Queries

Open `database/queries.sql` to run useful operational queries, such as:
* **Voter Eligibility & Verification:** Check which voters have registered face encodings and approved ID cards.
* **Election Turnout:** Calculate real-time ballots cast vs. eligible voter percentage.
* **Audit Trail:** View one-time credential hashes, consumption timestamps, and blockchain transaction hashes (`tx_hash`).
* **Relayer Outbox:** Track pending, confirmed, or failed ballot relay submissions.

---

## Table Summary

* `voters`: Student registry, ID verification status, and biometric 128-d face encodings.
* `admins`: Administrator accounts and session version control.
* `voting_credentials`: Single-use cryptographic voting tokens issued upon successful liveness verification.
* `vote_attempts`: Transaction outbox logging blockchain submission status (`PENDING`, `SUBMITTED`, `CONFIRMED`, `FAILED`).
* `election_metadata`: Display names and update timestamps mapped to smart contract addresses.
* `active_election`: Singleton table holding the active smart contract address.
* `liveness_challenges` & `liveness_frames`: Temporal challenge states (e.g. blink check) and anti-replay frame hashes.
* `revoked_sessions`: Revoked JWT identifiers (`jti`) for logged-out sessions.
