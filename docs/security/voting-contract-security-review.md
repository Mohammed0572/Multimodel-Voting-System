# Voting Smart-Contract Security Review

## Scope and methodology

The review covers `server/blockchain/contracts/Voting.sol`, including the election lifecycle, candidate administration, opaque credential consumption, and vote counting. The methodology follows the Paper 3 lesson that automated analysis is necessary but insufficient: first establish the threat model, then run automated detectors, then manually inspect authorization, external calls, privacy, state transitions, arithmetic, replay, and deployment assumptions.

The automated tool was **Slither 0.11.6**. The compiler used for the final scan was `solc 0.8.36`, which satisfies the contract pragma `^0.8.24`. The raw output is preserved in [slither-voting-output.txt](./slither-voting-output.txt).

## Threat model

The public blockchain observer can inspect contract storage, calldata, event logs, transaction sender addresses, vote counts, and timing. The observer must not be able to derive a voter identity from contract data alone. The server-side authentication service and its SQLite credential mapping are trusted components for this prototype and are outside the chain-only anonymity claim. An attacker may attempt unauthorized administration, voting before or after the election, invalid candidates, zero credentials, credential replay, and arithmetic abuse.

## Automated scan findings

The first Slither scan produced two findings:

| Detector | Severity | Location | Triage and action |
|---|---:|---|---|
| `solc-version` | Informational/optimization | `Voting.sol:2`, pragma `^0.8.20` in the initial scan | Fixed by upgrading the compiler target to `^0.8.24`, which avoids the listed compiler-version warnings under the installed `0.8.36` compiler. |
| `immutable-states` | Informational/optimization | `Voting.sol:5`, `Voting.owner` in the initial scan | Fixed by declaring `owner` as `immutable`; it is assigned only in the constructor. |

The final scan reported **0 optimization issues, 0 informational issues, 0 low issues, 0 medium issues, 0 high issues, and 0 detector results across 102 detectors**. The process exit code was 0. The complete post-fix output, including the initial scan history overwritten by the final reproducible scan, is stored in `slither-voting-output.txt`; the initial findings are transcribed above for audit traceability.

## Manual review

### Access control

`owner` is assigned in the constructor at line 29 and is immutable at line 5. The `onlyOwner` modifier at lines 33–36 requires `msg.sender == owner`. `addCandidate` at line 38, `startElection` at line 70, and `endElection` at line 75 all use this modifier. Unauthorized callers therefore cannot add candidates or change election state through these functions. There is no owner transfer function, which reduces the administrative surface but means ownership cannot be rotated without redeployment.

### Re-entrancy and external calls

The contract contains no external calls, token transfers, callbacks, delegatecalls, or payable functions. The re-entrancy threat is therefore not applicable to the current implementation. `vote` performs only local storage reads and writes.

### Sensitive data and privacy

The contract stores candidate names, parties, vote counts, election state, and opaque `bytes32` credential digests. It does not store voter IDs, voter-ID hashes, names, biometric data, or the server-side credential-to-voter mapping. The `vote` function receives a random credential digest and writes it to `credentialUsed` at lines 50–55. A chain-only observer cannot reverse a cryptographically random 256-bit credential into a USN. The server-side SQLite mapping remains sensitive and must not be published or logged.

The vote choice is necessarily visible indirectly through public candidate vote counts and transaction timing. This design therefore separates identity from ballot credential, but it is not a fully anonymous end-to-end voting protocol.

### Election-state enforcement

`vote` requires `state == ElectionState.Active` at line 46. The constructor starts in `NotStarted`; `startElection` transitions only from `NotStarted` to `Active`, and `endElection` transitions only from `Active` to `Ended`. Votes are rejected before start and after ending.

### Candidate validation

`vote` requires `candidateID > 0 && candidateID <= countCandidates` at line 48. This prevents votes for nonexistent candidate records. Candidate count is incremented only by the owner in `addCandidate`.

### Integer safety

The contract uses Solidity `^0.8.24`. Solidity 0.8.x checked arithmetic reverts on integer overflow and underflow. The only increment operations are candidate count at line 39 and vote count at line 55. Neither can silently wrap under the selected compiler semantics.

### One-time credential enforcement

A zero credential is rejected at line 50. A credential already marked in `credentialUsed` is rejected at line 51, and the credential is marked before the vote count is incremented at line 53. A reverted transaction rolls back both writes. The server additionally stores a hash of the credential, binds it to the authenticated session, expires it, atomically consumes it, and prevents a new credential after a completed ballot. The contract remains the independent on-chain replay barrier.

### Credential privacy limitation

The credential itself is visible in transaction calldata as its opaque digest. This is intentional: the chain needs a nullifier-like replay key. Privacy comes from the credential being random and not mathematically derived from the voter ID. Anyone with access to both the private server database and chain data could correlate a credential, so this review does not claim protection against a compromised authentication server.

## Fixes and residual risks

The real automated findings were optimization/compiler-hygiene findings, not exploitable authorization or fund-loss vulnerabilities. They were fixed by using `owner immutable` and updating the Solidity compiler target. The privacy issue identified by Paper 3 was addressed architecturally by removing voter-ID hashes from the contract and using opaque one-time credentials.

Residual risks include centralized trust in the credential issuer and relayer, the visibility of vote totals and transaction metadata, the absence of contract-level role separation beyond a single owner, and the requirement to redeploy the changed contract. The relayer private key must be server-only and must never be placed in a `VITE_` environment variable.

## Reproduction commands

```bash
# Automated scan, after installing Slither
slither server/blockchain/contracts/Voting.sol

# Compile and redeploy the changed contract
cd server/blockchain
npx truffle compile
npx truffle migrate --reset

# Contract tests (with Ganache running)
npx truffle test
```

The final scan was run against the exact post-fix contract source. Full integration testing still requires a running RPC node, a deployed post-fix contract, a funded relayer, and the configured face-auth service.
