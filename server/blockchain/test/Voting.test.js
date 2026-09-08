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
  });
});
