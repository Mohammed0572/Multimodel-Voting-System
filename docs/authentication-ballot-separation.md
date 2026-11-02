# Authentication and ballot separation

The API verifies an approved voter using a persistent single-use eye-close/open challenge and identity checks on the same submitted observations. The browser receives HttpOnly session and voting cookies.

A credential derives from a cryptographically random 32-byte nonce using a domain-separated server HMAC. SQLite retains the nonce and SHA-256 digest so concurrent sessions retrieve the same unused authorization. The contract receives only `keccak256(rawCredential)` and the candidate ID, never an ID, password, image or embedding.

`PENDING` reserves one voter/election pair. `SUBMITTED` means the signed transaction, hash and nonce are durable before broadcast. `CONFIRMED` means a canonical successful receipt has the configured confirmations and the credential is permanently consumed. A timeout is not a failure. Recovery may resend identical signed bytes, but cannot create another ballot while the outcome is uncertain. Only an unsigned expired reservation or a confirmed revert releases it. No SQLite write transaction waits on RPC.

The contract independently enforces state, candidate validity, relayer authorization and credential uniqueness. It trusts the issuer to establish eligibility and cannot enforce unique human identities.

This is **not cryptographic ballot secrecy**. The service sees identity and choice during submission, its database maps voters to transaction hashes, and public calldata/events reveal choice and credential digest. Timing can also reveal participation. Restrict the registry, signed outbox and backups. Do not log identity together with a choice.

See [README](../README.md) for configuration and migration/quarantine behavior, and the [validation report](security/hardening-report-2026-11-01.md) for tests and limitations. No Solidity interface change was made in this hardening; compatible deployments can be reused.
