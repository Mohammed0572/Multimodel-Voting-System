# Repository audit — 1 November 2026

Inspected React pages, API callers, authentication context, camera lifecycles,
FastAPI routes, SQLite migrations, CV helpers, Solidity, deployment scripts,
configuration, audit export, and existing tests before editing.

## Prioritized findings

| Priority | Finding | Consequence |
| --- | --- | --- |
| Critical | RPC submission/receipt wait inside SQLite write transaction; hash saved only after receipt | Accepted ballots can be lost locally; fresh credentials can permit a second ballot after a crash |
| Critical | Public registration can recreate deleted voter IDs after credentials are deleted | Removes evidence of earlier voting |
| High | Predictable blink-only, process-local challenges; identity only on endpoints of sequence | Replay and person substitution; workers disagree on challenge state |
| High | Audit generates transaction hashes, block numbers/hashes and candidate IDs when RPC is unavailable | Fabricated ledger evidence |
| High | JWT logout only clears cookies; roles/accounts are not rechecked | Copied sessions survive logout and account changes |
| High | Unbounded frame lists and decoded dimensions; enrollment CV runs on event loop | Resource exhaustion and native CV concurrency risk |
| High | Concurrent relayer requests independently obtain the same pending nonce | Lost/replaced transactions |
| Medium | Issuance rotates credentials on each refresh; eligibility ignores expiry and ownership | Multi-tab failures and stale credentials |
| Medium | Camera promises can resolve after unmount; vote UI treats any successful HTTP response as confirmation | Resource leaks and premature success |
| Medium | Docker backend references OCR requirements before copying them; Truffle reads the wrong .env path | Broken deployment |
| Medium | Demo resets contract each start and includes a deterministic relayer key in source | Restart creates a new election; unsafe reuse outside local demo |
| Medium | No startup JWT strength validation; broad dependency constraints and deprecated Truffle dependencies | Deployment and maintenance risk |
| Low | Stale blink/head-movement documentation; incomplete contract/concurrency tests | Misleading guarantees and undetected regressions |

Contract inspection: owner/relayer authorization, valid candidate IDs, election
transitions, zero credentials and credential replay are already enforced. The
relayer remains trusted to issue eligible credentials; the contract cannot infer
real-world eligibility. No Solidity interface change is needed for the fixes.

Baseline: Python suite 16 passed; contract suite 5 passed. Frontend checks were
started as well; final results and changes are recorded in the final report.

Recovery design: durable PENDING reservation → SUBMITTED signed transaction/hash
persisted before broadcast → CONFIRMED after canonical receipt and configured
confirmations. Unknown transactions retain the reservation. Recovery may
rebroadcast identical signed bytes, never manufacture a fresh ballot. SQLite
uses WAL and synchronous FULL; no RPC executes while a database write lock is held.

References: [SQLite durability](https://sqlite.org/pragma.html#pragma_synchronous),
[Web3 transaction/receipt semantics](https://web3py.readthedocs.io/en/stable/web3.eth.html).
