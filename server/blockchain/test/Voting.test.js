const Voting = artifacts.require("Voting");

contract("Voting", (accounts) => {
  const owner = accounts[0];
  const relayer = accounts[1];
  const other = accounts[2];

  let voting;

  beforeEach(async () => {
    voting = await Voting.new(relayer, { from: owner });
  });

  it("sets owner and relayer", async () => {
    assert.equal(await voting.owner(), owner);
    assert.equal(await voting.relayer(), relayer);
  });

  it("allows only owner to add candidates", async () => {
    await voting.addCandidate("Alice", "Independent", {
      from: owner,
    });

    try {
      await voting.addCandidate("Bob", "Party", {
        from: other,
      });
      assert.fail("Expected owner check to fail");
    } catch (error) {
      assert(error.message.includes("Only owner"));
    }
  });

  it("allows only the relayer to vote", async () => {
    await voting.addCandidate("Alice", "Independent", {
      from: owner,
    });

    await voting.startElection({ from: owner });

    const credential = web3.utils.padLeft("0x1234", 64);

    try {
      await voting.vote(1, credential, { from: other });
      assert.fail("Expected relayer check to fail");
    } catch (error) {
      assert(error.message.includes("Only relayer"));
    }

    await voting.vote(1, credential, { from: relayer });
  });

  it("rejects credential replay", async () => {
    await voting.addCandidate("Alice", "Independent", {
      from: owner,
    });

    await voting.startElection({ from: owner });

    const credential = web3.utils.padLeft("0xabcd", 64);

    await voting.vote(1, credential, { from: relayer });

    try {
      await voting.vote(1, credential, { from: relayer });
      assert.fail("Expected replay to fail");
    } catch (error) {
      assert(error.message.includes("already been used"));
    }
  });

  it("emits VoteCast", async () => {
    await voting.addCandidate("Alice", "Independent", {
      from: owner,
    });

    await voting.startElection({ from: owner });

    const credential = web3.utils.padLeft("0xbeef", 64);

    const result = await voting.vote(1, credential, {
      from: relayer,
    });

    assert.equal(result.logs[0].event, "VoteCast");
    assert.equal(result.logs[0].args.candidateId.toString(), "1");
    assert.equal(result.logs[0].args.credential, credential);
    const block = await web3.eth.getBlock(result.receipt.blockNumber);
    assert.equal(result.logs[0].args.timestamp.toString(), block.timestamp.toString());
  });

  async function reverts(promise, message) {
    try { await promise; } catch (error) {
      assert(error.message.includes(message), error.message);
      return;
    }
    assert.fail(`Expected revert: ${message}`);
  }

  it("rejects a zero relayer", async () => {
    await reverts(Voting.new("0x" + "0".repeat(40)), "cannot be zero");
  });

  it("requires candidates and owner permission to start", async () => {
    await reverts(voting.startElection({ from: other }), "Only owner");
    await reverts(voting.startElection({ from: owner }), "at least one");
    await reverts(voting.endElection({ from: owner }), "not active");
  });

  it("validates candidate fields and emits candidate event", async () => {
    await reverts(voting.addCandidate("", "Party", { from: owner }), "name is required");
    await reverts(voting.addCandidate("A".repeat(101), "Party", { from: owner }), "name is too long");
    await reverts(voting.addCandidate("A", "P".repeat(101), { from: owner }), "Party name is too long");
    const tx = await voting.addCandidate("Alice", "Independent", { from: owner });
    assert.equal(tx.logs[0].event, "CandidateAdded");
    assert.equal(tx.logs[0].args.name, "Alice");
  });

  it("enforces the complete election lifecycle", async () => {
    const credential = web3.utils.randomHex(32);
    await voting.addCandidate("Alice", "Independent", { from: owner });
    await reverts(voting.vote(1, credential, { from: relayer }), "not active");
    assert.equal((await voting.getElectionState()).toString(), "0");
    const start = await voting.startElection({ from: owner });
    assert.equal(start.logs[0].event, "ElectionStarted");
    assert.equal((await voting.getElectionState()).toString(), "1");
    await reverts(voting.startElection({ from: owner }), "already started");
    await reverts(voting.addCandidate("Bob", "Party", { from: owner }), "already started");
    await reverts(voting.endElection({ from: other }), "Only owner");
    const end = await voting.endElection({ from: owner });
    assert.equal(end.logs[0].event, "ElectionEnded");
    assert.equal((await voting.getElectionState()).toString(), "2");
    await reverts(voting.vote(1, credential, { from: relayer }), "not active");
    await reverts(voting.startElection({ from: owner }), "already started");
    await reverts(voting.endElection({ from: owner }), "not active");
  });

  it("rejects invalid candidate IDs and empty credentials without consuming them", async () => {
    await voting.addCandidate("Alice", "Independent", { from: owner });
    await voting.startElection({ from: owner });
    const credential = web3.utils.randomHex(32);
    for (const id of [0, 2]) {
      await reverts(voting.vote(id, credential, { from: relayer }), "Invalid candidate");
      await reverts(voting.getCandidate(id), "Invalid candidate");
    }
    await reverts(voting.vote(1, "0x" + "0".repeat(64), { from: relayer }), "Credential is required");
    assert.equal(await voting.checkCredential(credential), false);
    assert.equal((await voting.getCandidate(1))[3].toString(), "0");
  });

  it("counts multiple voters and rejects replay against another candidate", async () => {
    await voting.addCandidate("Alice", "A", { from: owner });
    await voting.addCandidate("Bob", "B", { from: owner });
    await voting.startElection({ from: owner });
    const credentials = [web3.utils.randomHex(32), web3.utils.randomHex(32), web3.utils.randomHex(32)];
    await voting.vote(1, credentials[0], { from: relayer });
    await voting.vote(1, credentials[1], { from: relayer });
    await voting.vote(2, credentials[2], { from: relayer });
    await reverts(voting.vote(2, credentials[0], { from: relayer }), "already been used");
    assert.equal((await voting.getCandidate(1))[3].toString(), "2");
    assert.equal((await voting.getCandidate(2))[3].toString(), "1");
    for (const credential of credentials) assert.equal(await voting.checkCredential(credential), true);
  });

  it("accepts at most one concurrent transaction using a credential", async () => {
    await voting.addCandidate("Alice", "A", { from: owner });
    await voting.startElection({ from: owner });
    const credential = web3.utils.randomHex(32);
    const results = await Promise.allSettled([
      voting.vote(1, credential, { from: relayer }),
      voting.vote(1, credential, { from: relayer }),
    ]);
    assert.equal(results.filter(result => result.status === "fulfilled").length, 1);
    assert.equal((await voting.getCandidate(1))[3].toString(), "1");
  });
});
