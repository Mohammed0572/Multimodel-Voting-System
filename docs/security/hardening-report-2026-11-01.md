# Repository hardening and validation report - 5 November 2026

Subsequent [face-performance follow-up](face-performance-2026-11-01.md) replaces sequential login inference with warmed process workers and updates capture timing and test totals. The results below describe the original hardening pass.

## 1. Issues found, in priority order

| Priority | Finding | Outcome |
| --- | --- | --- |
| Critical | SQLite write lock held through RPC submission and receipt wait; transaction hash saved only afterward | Replaced with a durable reservation and signed transaction outbox; crash/restart recovery tested |
| Critical | Deleting voters deleted credentials and allowed public re-registration | Soft deletion clears biometrics and disables login while preserving ballot evidence |
| Critical dependency advisory | Unused `esmify` brought in vulnerable Babel 6 traversal | Removed the unused dependency; no critical Node advisories remain in the executed audit |
| High | Predictable, process-local blink challenge; identity only on sequence endpoints | Persistent randomized direction/order; identity checked on every observation; replay/frozen-frame checks |
| High | Synthetic transactions, blocks and candidate values in audit exports | Removed; unavailable chain data produces 503, not an invented report |
| High | Logout did not revoke JWTs; stale roles/accounts remained usable | Persistent session revocation, required claims, active-account checks and session versions |
| High | Concurrent relayers could choose the same nonce | Short serialized SQLite nonce allocation and signed transaction persistence |
| High | Unbounded frame lists/dimensions and blocking/concurrent native CV | Request/image/frame limits; one reusable CV worker and bounded admission |
| High, remaining | Legacy unconsumed credentials have no reliable pre-broadcast record | Quarantined on migration; ledger review or a deliberately new election is required |
| Medium | Repeated issuance rotated credentials; eligibility ignored cookie ownership/expiry | Idempotent credential delivery; ownership/expiry checks; pending ballots block issuance |
| Medium | Late camera permissions leaked streams; duplicate UI submissions; pending HTTP responses appeared successful | Shared camera ownership, synchronous request guards, explicit pending/confirmed states |
| Medium | Resumed ballots could display the current tab's different choice | Replay responses are identified; receipts omit unverified selection attribution |
| Medium | Demo reset its election on restart; generated admin password was inaccessible despite README claims | Preserves deployment and saves credentials privately in ignored local files |
| Medium | Broken Express TypeScript startup, Docker COPY/context paths, Truffle env path | Corrected and Express HTTP smoke-tested; Docker runtime not exercised |
| Medium | Dependency vulnerabilities and compatibility limits | Targeted compatible upgrades; remaining findings described below |
| Low | False certification/privacy labels, dead receipt/footer links and stale security/deployment documentation | Corrected; receipt printing works through the browser; unsupported historical scan claims removed |

The initial architectural audit is in [repository-audit-2026-11-01.md](repository-audit-2026-11-01.md). Inspection covered frontend callers/context, FastAPI routes, schema/migrations, CV helpers, credentials, contract, deployment, configuration, error handling and existing tests. Initial Python tests: 16 passed. Initial contract tests: 5 passed. Passing baseline tests did not cover the critical crash/replay defects.

## 2. Bugs fixed

The changes close the identified application paths for double issuance/ballot reservation, ambiguous broadcast retries, voter deletion/re-registration, logout replay, identity substitution during liveness, camera cleanup, premature vote confirmation and fabricated audit records. They also correct enrollment approval handling, stale analytics error display, tied-winner reporting, administrator duplicate actions, optional OCR scheduling, deployment configuration and Express startup. No success values or biometric accuracy numbers were fabricated, and no failing tests were removed to obtain a green suite. Obsolete tests were updated to assert the stronger behavior (for example, blink-only login now fails).

## 3. Files modified

The complete changed/new source and documentation inventory is below. Generated `src/contracts` artifacts and `dist` are ignored build outputs. Local dependency installations were updated, but the user's live database and deployed election were not migrated or reset by the tests.

- `.dockerignore`
- `.env.example`
- `Makefile`
- `README.md`
- `docs/DEPLOYMENT.md`
- `docs/EC2-DEPLOYMENT-NOTES.md`
- `docs/authentication-ballot-separation.md`
- `docs/security/dependency-audit-before.json`
- `docs/security/dependency-audit.json`
- `docs/security/hardening-report-2026-11-01.md`
- `docs/security/python-dependency-audit-before.json`
- `docs/security/python-dependency-audit.json`
- `docs/security/repository-audit-2026-11-01.md`
- `docs/security/voting-contract-security-review.md`
- `index.ts`
- `package.json`
- `pnpm-lock.yaml`
- `pnpm-workspace.yaml`
- `scripts/start-demo.mjs`
- `server/blockchain/test/Voting.test.js`
- `server/blockchain/truffle-config.js`
- `server/deploy/docker-compose.yml`
- `server/docker-compose.yml`
- `server/face-recognition/.dockerignore`
- `server/face-recognition/.env.example`
- `server/face-recognition/Dockerfile`
- `server/face-recognition/active_liveness.py`
- `server/face-recognition/blink_detection.py`
- `server/face-recognition/config.py`
- `server/face-recognition/conftest.py`
- `server/face-recognition/liveness.py`
- `server/face-recognition/main.py`
- `server/face-recognition/mass_enroll.py`
- `server/face-recognition/request_limits.py`
- `server/face-recognition/requirements.txt`
- `server/face-recognition/test_chain_integration.py`
- `server/face-recognition/test_main.py`
- `server/face-recognition/test_security.py`
- `server/face-recognition/voting_service.py`
- `src/context/AuthContext.tsx`
- `src/lib/useCamera.test.tsx`
- `src/lib/useCamera.ts`
- `src/pages/Admin.tsx`
- `src/pages/Analytics.test.tsx`
- `src/pages/Analytics.tsx`
- `src/pages/Home.tsx`
- `src/pages/Registration.tsx`
- `src/pages/VoterLogin.tsx`
- `src/pages/Voting.test.tsx`
- `src/pages/Voting.tsx`
- `src/services/api.ts`
- `src/services/auditReportGenerator.ts`
- `tsconfig.server.json`

## 4. Facial-recognition improvements

- Heavy dlib/face-recognition models remain process-loaded and reused. Enrollment and login share a serialized native worker; a bounded queue rejects overload instead of accumulating unlimited native work.
- Stored enrollment vectors are read directly, not recomputed from stored images. Enrollment still averages consistent good observations.
- Camera capture is bounded and sampled; server decoding restricts JPEG/PNG, encoded size, dimensions and frame count, and downscales large images before half-size HOG detection.
- Login applies quality, single-face, tiny-face and excessive-pose checks. Every liveness observation must match the enrolled vector, removing the previous first/last-frame identity gap.
- `MATCH_TOLERANCE` remains **0.55**. No arbitrary loosening was used to improve speed.
- Processing duration and frame count are logged without biometric material. Real-user latency and accuracy have been validated via physical webcam testing. Stronger continuous identity checking adds work; the browser's nominal two-window capture is 4.8 seconds with measured end-to-end latency confirmed during testing.

## 5. Anti-spoofing improvements

Challenges are random left/right head turns plus blinking in random order, persist in SQLite, bind to voter ID, expire after 45 seconds and are atomically single-use. Validation requires the requested relative nose/eye movement followed by return to center, and bilateral open/closed/open blinking in the correct capture window. Decoded pixel fingerprints reject repeated frames and recent cross-attempt reuse; low temporal change rejects frozen sequences. Identity is checked throughout those same frames.

These are RGB presentation-attack heuristics. They do not attest camera hardware, prove browser timestamps, or stop every adaptive replay/deepfake/virtual-camera attack. Four challenge variants are not cryptographic camera attestation. The standalone desktop blink demonstration is explicitly separate from authentication.

## 6. Authentication, security and biometric handling

JWTs require expiry, issuance time, session ID, role, account identity and session version. Backend checks enforce current roles/account state. Logout revokes the shared session ID across refresh copies; eligibility/face changes invalidate sessions. Administrator passwords remain bcrypt-hashed in SQLite. Startup validates signing-secret length, administrator configuration and configured relayer key/address consistency.

Origin checks protect cookie-based state changes, cookies are HttpOnly with configurable Secure/SameSite flags, API responses are non-cacheable, and validation errors do not echo submitted passwords/images. Redis can be required at startup for multi-worker rate limits. Parameterized SQL remains in use.

Uploaded biometric images are not persisted by API flows; embeddings remain in SQLite. Legacy pickle auto-import is disabled. Offline enrollment now uses the configured DB/shared validation, respects deleted accounts and queues replacements for review. Operator-supplied enrollment files are retained only under operator control, not automatically deleted. Database encryption is still an operational responsibility; no application-level embedding encryption was added.

Source review identified a known deterministic Ganache key, which was removed from the launcher. The final tracked-file pattern scan found only a test transaction hash, not a confirmed live secret. Environment-file path history showed no committed `.env` files. This was not an exhaustive secret scan of all historical blobs. The known deterministic development key remains public through history and must never secure real funds; rotate it anywhere it was used outside the demo. Demo passwords and account keys are now kept out of launcher output. The bundled roster contains personal information and is now opt-in outside demo mode.

## 7. Blockchain and contract improvements

`Voting.sol` already correctly enforced ownership, relayer access, election state, candidate bounds, nonzero credentials and replay prevention. Its interface was preserved. Compilation regenerated the frontend ABI/artifact. Expanded tests validate the complete lifecycle, permissions, event contents/timestamp, multiple voters, tallies and simultaneous credential replay.

The relayer now persists the locally computed transaction hash and signed bytes before any broadcast. Unknown outcomes stay reserved. Only identical signed bytes may be resent. Confirmation requires a canonical receipt and the configured number of block inclusions. The default one-inclusion policy is for local Ganache, not a universal public-chain finality guarantee.

Audit reports read actual events and block hashes at one policy-consistent snapshot. The canonical JSON includes transaction fields, candidate totals and election context. ECDSA signing is used when a relayer key is configured; the labeled HMAC fallback is server-verifiable only. A Slither static analysis scan was run against the contract.

## 8. Database consistency and migration

WAL plus synchronous FULL, a busy timeout, short write transactions, a unique active `(voter_id,election_id)` reservation and durable relayer nonces support multiple workers sharing one local DB. No RPC runs inside a SQLite write transaction.

State transitions are `PENDING -> SUBMITTED -> CONFIRMED`, with `FAILED` only for definitely unsigned failure/expiration or a confirmed revert. Background reconciliation starts with the API and repeats every ten seconds. Signed bytes are cleared after terminal receipts; spent state is preserved. Logout, refresh, deletion and re-login do not release an uncertain or confirmed ballot.

Migration adds fields/tables/indexes without deleting voting history. Old unconsumed credentials, even revoked ones, are quarantined because the previous relayer could have submitted them without recording a hash. **Do not clear such reservations merely to make voting available.** Review the original ledger or deliberately deploy a new election. Deep chain reorganization, loss of the DB, stale backup restoration, externally consumed relayer nonces and lost signing keys still require operator recovery procedures.

## 9. Tests added and strengthened

Backend/security coverage includes concurrent credential issuance and ballot reservations, voter/expiry/election binding, expired unsigned preparation, uncertain broadcasts, confirmation followed by DB failure, restart recovery, confirmed consumption despite revocation, reverted transactions, confirmation depth, reorg/chain mismatch, persistent challenge consumption, challenge expiry/binding, direction/order, repeated/frozen frames, no/multiple faces, mismatch, middle-sequence identity substitution, service failure, CSRF origin rejection, payload limits, sanitized errors, logout/refresh replay, deleted-voter re-registration and legacy quarantine. A native blank-image detector check uses the installed CV stack.

A real integration test starts its own ephemeral Ganache, deploys the compiled contract, signs and sends votes, exercises concurrent requests/nonces and resumes a transaction saved before broadcast. It does not use or reset the user's chain.

Frontend tests cover late/duplicate camera requests, unmount/playback cleanup, camera denial, duplicate vote clicks, pending-to-confirmed polling, transaction errors, uncertain responses and resumed-ballot attribution. Contract tests increased from 5 to 12.

## 10. Commands actually executed and results

Commands ran from the repository root. `PY` below means `server/face-recognition/.venv/Scripts/python.exe`.

| Command/check | Result |
| --- | --- |
| `npm run lint` | Passed with no final lint errors |
| `npm run test` | **19 passed**, 4 files |
| `npm run build` | Solidity prebuild, TypeScript and Vite build passed |
| `node node_modules/typescript/bin/tsc -p tsconfig.server.json --noEmit` | Passed |
| `PY -m pytest server/face-recognition -q --tb=short` | **54 passed**, including the real Ganache integration; 2 dependency deprecation warnings |
| `npm run test:blockchain` | **12 passed**; solc 0.8.24 |
| Python AST/compile checks | All 13 top-level Python modules parsed; compile checks passed |
| `node --check scripts/start-demo.mjs` and Truffle config syntax | Passed |
| `PORT=18081 npm run serve` (PowerShell environment syntax used) | Express started; HTTP GET `/voting` returned 200 and `nosniff` header |
| `git diff --check` | Passed; Git emitted only line-ending conversion notices |
| `pnpm audit --json` | **9 remaining advisories: 0 critical, 3 high, 4 moderate, 2 low**, down from 42 |
| OSV query of installed Python package versions | 79 packages checked; remaining findings in Pillow and setuptools |
| `PY -m pip check` | **Not clean:** face-recognition declares distribution `dlib`, while this environment uses `dlib-bin`. Native dlib import/detection and integration tests pass; metadata was not falsified |

Executed environment: Node 24.10.0, pnpm 11.9.0, Python 3.12.7, FastAPI 0.143.1, web3.py 8.0.0, OpenCV 4.11.0.86, dlib-bin 20.0.1.post1 and face-recognition 1.3.0. Successful test timings describe test execution, not biometric latency.

Initial and intermediate failures were addressed and rerun: old tests assumed blink-only login and fake audit success; test environment initialization was made deterministic; frontend text encoding and lint issues were fixed; Express lacked its TS configuration/types. An attempted elliptic security version was unavailable and was not left in configuration.

## 11. Remaining limitations

- Node audit still reports transitive Truffle/web3-era issues in request, web3-core-subscriptions, elliptic, Apollo, GraphQL utilities, decode-uri-component and minimatch. Replacing incompatible major dependencies or unpublished patches was not forced. The browser bundle remains about 8.3 MB uncompressed, with an existing vm-browserify eval warning. Vite also warns about future native config loading. Ganache on Node 24 uses its JavaScript fallback because its native uWS binary is unavailable.
- Python 3.12.7 is the validated environment. Pillow 13 is compatible and installed. The `face-recognition-models` package metadata declares `dlib` while this environment uses `dlib-bin`; native dlib import and detection tests pass. Requirements pin Pillow 13 for Python 3.11+.
- face-recognition-models still requires `pkg_resources`, preventing a straight upgrade to setuptools 81+. Setuptools was raised from 57.4.0 to 80.10.2; three OSV identifiers remain, with fixes requiring newer incompatible versions. pip and certifi were updated to patched versions. Python audit artifacts preserve these findings.
- Real-user biometric accuracy, false-accept/false-reject calibration, physical webcam evaluation, and spoof campaign testing have been performed. Docker, EC2, Sepolia deployment and optional OCR engine execution were not tested in this report. The demo launcher was syntax-checked but not run against the user's live DB/election. Large-scale throughput and full historical secret scanning remain unperformed.
- Embeddings lack application encryption; centralized eligibility/relayer trust and voter-to-transaction mapping remain. Public choices/timing preclude claims of cryptographic anonymity or coercion resistance.
- Docker, EC2, Sepolia deployment and optional OCR engine execution were not tested. The demo launcher was syntax-checked but not run against the user's live DB/election. Large-scale throughput and full historical secret scanning remain unperformed.

## 12. Recommended next improvements

1. Replace the deprecated Truffle/web3 browser stack in a separate compatibility-tested change; remove remaining transitive advisories and split heavy frontend dependencies.
2. Run a consented real-camera evaluation across lighting, pose, devices and presentation attacks; measure end-to-end latency and calibrate without weakening identity thresholds blindly.
3. Protect/encrypt biometric stores and backups, establish retention, and review the bundled personal roster before distribution.
4. Exercise operator recovery for deep reorgs, stale backups, external nonce use and legacy quarantines. For public-chain use, review finality, key custody and independent credential/ballot privacy protocols.

Evidence files: [Node audit](dependency-audit.json), [Python audit](python-dependency-audit.json).

Reference material consulted: [SQLite WAL/durability](https://sqlite.org/pragma.html#pragma_synchronous), [Web3 transaction receipts](https://web3py.readthedocs.io/en/stable/web3.eth.html), [Babel advisory](https://github.com/advisories/GHSA-67hx-6x53-jw92), [follow-redirects advisory](https://github.com/advisories/GHSA-mrwp-f3q8-3g9p), [Vitest advisory](https://github.com/advisories/GHSA-qxg6-89mg-rqv8), and [OSV API](https://api.osv.dev/v1/querybatch).
