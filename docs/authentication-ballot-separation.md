# Authentication–Ballot Separation

## Design basis

The system now separates the proof that a person is an eligible voter from the ballot that the person casts. This addresses the privacy weakness identified in **Paper 5 (BP-Vot)**: placing an authenticated voter-ID hash beside a ballot still creates a stable identity-linked handle on the public ledger.

## Protocol

After face and liveness verification, the authentication service checks the SQLite voter registry and the administrator’s ID-card approval. For an approved voter who has not already cast a ballot, the service generates 32 cryptographically random bytes. It stores only the SHA-256 digest of this credential with the voter ID in the private SQLite database and places the raw credential in an HttpOnly, Secure/SameSite cookie. The raw credential is never returned in JSON, local storage, URL parameters, or frontend JavaScript.

When the voter confirms a candidate, the browser sends only the candidate identifier to the authenticated `/api/v1/voter/cast` endpoint. The server reads the HttpOnly credential cookie, verifies its private digest, atomically marks the credential consumed, and relays the transaction. The contract receives `keccak256(rawCredential)` as an opaque `bytes32` value and records that value in `credentialUsed`. It never receives the USN or a hash derived from the USN.

## Security properties

A credential is random, short-lived, bound to the authenticated server session, and single-use. The SQLite record prevents the service from issuing a second credential after a consumed credential exists for the same voter. The smart contract independently rejects reuse of the same credential value. The browser cannot read the credential, and a ballot request without the cookie is rejected.

A chain-only observer sees the opaque credential digest, candidate identifier, relayer address, and transaction metadata. The observer does not see the voter ID or the server-side mapping from credential digest to voter ID. Consequently, chain data alone cannot identify the voter. The server database remains a sensitive trust boundary: an operator who obtains both the database and chain data could correlate credentials, so the database must be protected and excluded from public artifacts and logs.

## Verification checklist

1. Authenticate a voter whose ID card is approved and inspect the response body: no credential is present.
2. Inspect browser storage: the credential is an HttpOnly cookie and is not available to page JavaScript.
3. Inspect the `voter/cast` request body: it contains only `candidate_id`.
4. Inspect the transaction input and contract storage: no USN or USN hash is present; only the opaque credential value is used.
5. Repeat the same cast request: the service rejects the consumed credential, and the contract rejects a repeated credential.
6. Authenticate the same voter again after a successful ballot: no new credential is issued, and the session reports that the voter has already voted.

## Deployment requirement

The new contract must be compiled and redeployed before this flow is used. The face-auth service must be configured with `BLOCKCHAIN_RPC_URL`, `BLOCKCHAIN_CONTRACT_ADDRESS`, and a server-only `BLOCKCHAIN_RELAYER_PRIVATE_KEY`. The relayer account must have native-token funds for gas. The private key must never use a `VITE_` variable or be sent to the frontend.

This is a privacy separation layer, not a fully anonymous voting protocol. The relayer and private authentication database remain trusted components, and transaction timing, network metadata, and administrative logs may still reveal operational information outside the chain-only threat model.

## Changed contract surface

The contract now exposes `vote(uint candidateID, bytes32 credential)` and `checkCredential(bytes32 credential)`. The previous voter-ID-hash method and `checkVote` surface were removed.

## Test status

The JavaScript contract tests were updated to use opaque credentials and to assert one-time consumption. The backend has syntax validation coverage for the new routes and credential helpers. Full end-to-end validation requires a running RPC node, a redeployed contract, a funded relayer key, an enrolled face encoding, and an administrator-approved student record.

> Do not treat a successful compilation as proof of anonymity. The critical acceptance test is the chain-data inspection described above, using a credential that cannot be derived from the voter ID and whose server-side mapping is unavailable to the chain observer.
