-- ============================================================================
-- Multimodal Blockchain Voting System - Useful SQLite Queries
-- ============================================================================
-- A curated collection of queries for managing voters, checking eligibility,
-- monitoring election turnout, and auditing cryptographic credentials.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. VOTER REGISTRATION & STATUS QUERIES
-- ----------------------------------------------------------------------------

-- List all active voters with verification and biometric registration status
SELECT 
    voter_id,
    student_name,
    branch,
    class_name,
    batch,
    id_verified,
    CASE WHEN face_encoding != '' THEN 1 ELSE 0 END AS has_face_registered,
    CASE WHEN pending_face_encoding IS NOT NULL THEN 1 ELSE 0 END AS face_update_pending,
    verified_by,
    verified_at
FROM voters
WHERE deleted = 0
ORDER BY voter_id;

-- Summary counts of voters by registration and verification state
SELECT 
    COUNT(*) AS total_registered,
    SUM(CASE WHEN id_verified = 1 THEN 1 ELSE 0 END) AS total_id_verified,
    SUM(CASE WHEN face_encoding != '' THEN 1 ELSE 0 END) AS total_with_face_data,
    SUM(CASE WHEN id_verified = 1 AND face_encoding != '' THEN 1 ELSE 0 END) AS fully_eligible_voters,
    SUM(CASE WHEN deleted = 1 THEN 1 ELSE 0 END) AS soft_deleted_voters
FROM voters;

-- Find a voter by USN / Voter ID
SELECT * FROM voters WHERE voter_id = '1KG23CB001' AND deleted = 0;

-- Approve / Verify a voter's physical ID card (Admin Action)
-- UPDATE voters 
-- SET id_verified = 1, verified_by = 'admin_user', verified_at = datetime('now') 
-- WHERE voter_id = '1KG23CB001';

-- Check voters with pending face re-registration requests
SELECT 
    voter_id, 
    student_name, 
    face_updated_at 
FROM voters 
WHERE pending_face_encoding IS NOT NULL AND deleted = 0;

-- ----------------------------------------------------------------------------
-- 2. ELECTION TURNOUT & PARTICIPATION QUERIES
-- ----------------------------------------------------------------------------

-- Turnout analytics for a specific election (replace :election_id)
-- Checks both issued consumed credentials and contract last_voted_election_id
SELECT 
    COUNT(*) AS total_enrolled,
    SUM(CASE WHEN v.id_verified = 1 THEN 1 ELSE 0 END) AS eligible_voters,
    SUM(
        CASE WHEN (
            EXISTS (
                SELECT 1 FROM voting_credentials vc
                WHERE vc.voter_id = v.voter_id
                  AND vc.election_id = '0xa94b7f0465e98609391c623d0560c5720a3f2d33'
                  AND vc.consumed_at IS NOT NULL
                  AND vc.revoked_at IS NULL
            ) OR v.last_voted_election_id = '0xa94b7f0465e98609391c623d0560c5720a3f2d33'
        ) THEN 1 ELSE 0 END
    ) AS ballots_cast,
    ROUND(
        (SUM(
            CASE WHEN (
                EXISTS (
                    SELECT 1 FROM voting_credentials vc
                    WHERE vc.voter_id = v.voter_id
                      AND vc.election_id = '0xa94b7f0465e98609391c623d0560c5720a3f2d33'
                      AND vc.consumed_at IS NOT NULL
                      AND vc.revoked_at IS NULL
                ) OR v.last_voted_election_id = '0xa94b7f0465e98609391c623d0560c5720a3f2d33'
            ) THEN 1.0 ELSE 0.0 END
        ) / MAX(SUM(CASE WHEN v.id_verified = 1 THEN 1 ELSE 0 END), 1)) * 100, 2
    ) AS turnout_percentage
FROM voters v
WHERE v.deleted = 0;

-- List all voters who have cast their vote in a given election
SELECT 
    v.voter_id,
    v.student_name,
    vc.consumed_at AS vote_timestamp,
    vc.tx_hash AS blockchain_tx_hash
FROM voters v
JOIN voting_credentials vc ON v.voter_id = vc.voter_id
WHERE vc.election_id = '0xa94b7f0465e98609391c623d0560c5720a3f2d33'
  AND vc.consumed_at IS NOT NULL
  AND vc.revoked_at IS NULL
ORDER BY vc.consumed_at DESC;

-- List eligible voters who have NOT voted yet
SELECT 
    v.voter_id,
    v.student_name,
    v.branch,
    v.batch
FROM voters v
WHERE v.deleted = 0
  AND v.id_verified = 1
  AND NOT EXISTS (
      SELECT 1 FROM voting_credentials vc
      WHERE vc.voter_id = v.voter_id
        AND vc.election_id = '0xa94b7f0465e98609391c623d0560c5720a3f2d33'
        AND vc.consumed_at IS NOT NULL
        AND vc.revoked_at IS NULL
  )
  AND (v.last_voted_election_id IS NULL OR v.last_voted_election_id != '0xa94b7f0465e98609391c623d0560c5720a3f2d33')
ORDER BY v.voter_id;

-- ----------------------------------------------------------------------------
-- 3. CREDENTIALS & BLOCKCHAIN TRANSACTION OUTBOX AUDIT
-- ----------------------------------------------------------------------------

-- Audit log of voting credentials for an election
SELECT 
    credential_hash,
    voter_id,
    issued_at,
    expires_at,
    consumed_at,
    revoked_at,
    tx_hash
FROM voting_credentials
WHERE election_id = '0xa94b7f0465e98609391c623d0560c5720a3f2d33'
ORDER BY issued_at DESC;

-- Check vote relay attempts (Outbox status)
SELECT 
    id,
    voter_id,
    election_id,
    status,
    created_at,
    tx_hash,
    block_number,
    failure
FROM vote_attempts
ORDER BY created_at DESC
LIMIT 50;

-- Identify any failed vote transactions requiring relayer retry or review
SELECT * 
FROM vote_attempts 
WHERE status = 'FAILED'
ORDER BY created_at DESC;

-- ----------------------------------------------------------------------------
-- 4. ELECTION & SYSTEM CONFIGURATION
-- ----------------------------------------------------------------------------

-- Get currently configured active election contract address
SELECT contract_address FROM active_election WHERE id = 1;

-- List all election cycles with names and update timestamps
SELECT * FROM election_metadata ORDER BY updated_at DESC;

-- Active administrators
SELECT admin_id, created_at, is_active, session_version FROM admins WHERE is_active = 1;

-- ----------------------------------------------------------------------------
-- 5. MAINTENANCE & CLEANUP
-- ----------------------------------------------------------------------------

-- Check count of expired liveness challenges
SELECT COUNT(*) AS expired_challenges 
FROM liveness_challenges 
WHERE expires_at < unixepoch();

-- Clean up expired liveness challenges (Older than 1 hour)
-- DELETE FROM liveness_challenges WHERE expires_at < (unixepoch() - 3600);

-- Clean up expired session blacklists
-- DELETE FROM revoked_sessions WHERE expires_at < unixepoch();
