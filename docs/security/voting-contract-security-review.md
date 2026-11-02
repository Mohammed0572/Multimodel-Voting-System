# Voting contract review - 1 November 2026

Reviewed `server/blockchain/contracts/Voting.sol`, migrations, frontend artifact consumption and backend ABI. Owner and relayer are immutable and checked by modifiers. Candidates can only be added before starting. Starting requires a candidate; ending requires an active election. An ended election cannot restart. Voting requires the relayer, an active election, a valid candidate and a nonzero unused credential. Consumption precedes tally increment. There are no external calls in the vote path.

The contract was preserved; no ABI change or forced redeployment was needed. Solidity 0.8.24 compilation and 12 Truffle/Ganache tests were executed. Coverage includes authorization, candidate bounds/fields, lifecycle, multiple voters, tallies, event fields/timestamp, replay and simultaneous transactions using one credential. Python integration also deploys the compiled artifact and tests real signing, concurrent nonce allocation and crash recovery.

No Slither scan was run in this audit. Earlier documentation asserted scan results against different source line numbers and linked to an unavailable output file; those claims are not evidence for this revision.

Residual trust: a compromised relayer can invent credentials. Public calldata/events reveal choice and credential digest. Owner/relayer key loss has no recovery mechanism. Finality depends on the chain and confirmation policy; one inclusion is the local demo policy. Deep reorganizations need operator review.

Run from the repository root:

```bash
pnpm run compile:contracts
pnpm run test:blockchain
```

See [the full report](hardening-report-2026-11-01.md), [SQLite durability](https://sqlite.org/pragma.html#pragma_synchronous) and [Web3 receipt semantics](https://web3py.readthedocs.io/en/stable/web3.eth.html).
