-- ============================================================================
-- Multimodal Blockchain Voting System - Sample Seed Data
-- ============================================================================
-- Populates demo records for testing voter verification, admin authentication,
-- and election analytics in a local SQLite database.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Default Administrator Account
-- Username: admin_user
-- Password hash placeholder (FastAPI generates and syncs this on startup)
-- ----------------------------------------------------------------------------
INSERT OR IGNORE INTO admins (admin_id, password_hash, created_at, is_active, session_version)
VALUES (
    'admin_user',
    '$2b$12$e86g5M1h7xNfK0zHjI2z..examplehashedpasswordplaceholderformanualseed',
    datetime('now'),
    1,
    0
);

-- ----------------------------------------------------------------------------
-- 2. Active Election Contract Address
-- ----------------------------------------------------------------------------
INSERT OR REPLACE INTO active_election (id, contract_address)
VALUES (
    1,
    '0xa94b7f0465e98609391c623d0560c5720a3f2d33'
);

INSERT OR REPLACE INTO election_metadata (election_id, name, updated_at)
VALUES (
    '0xa94b7f0465e98609391c623d0560c5720a3f2d33',
    'CSBS Student Council Election 2026',
    datetime('now')
);

-- ----------------------------------------------------------------------------
-- 3. Demo CSBS Student Voters
-- ----------------------------------------------------------------------------
INSERT OR IGNORE INTO voters (
    voter_id, role, face_encoding, name, usn, branch, class_name, batch,
    student_name, id_verified, verified_by, verified_at, deleted, voted
) VALUES 
(
    '1KG23CB001', 'user', '', 'AARAV SHARMA', '1KG23CB001', 'CB', 'CSBS', '2023',
    'AARAV SHARMA', 1, 'admin_user', datetime('now'), 0, 0
),
(
    '1KG23CB002', 'user', '', 'ANANYA IYER', '1KG23CB002', 'CB', 'CSBS', '2023',
    'ANANYA IYER', 1, 'admin_user', datetime('now'), 0, 0
),
(
    '1KG23CB003', 'user', '', 'ROHAN KULKARNI', '1KG23CB003', 'CB', 'CSBS', '2023',
    'ROHAN KULKARNI', 0, NULL, NULL, 0, 0
),
(
    '1KG23CB004', 'user', '', 'PRIYA MENON', '1KG23CB004', 'CB', 'CSBS', '2023',
    'PRIYA MENON', 1, 'admin_user', datetime('now'), 0, 0
),
(
    '1KG23CB005', 'user', '', 'VIKRAM PATIL', '1KG23CB005', 'CB', 'CSBS', '2023',
    'VIKRAM PATIL', 0, NULL, NULL, 0, 0
);
