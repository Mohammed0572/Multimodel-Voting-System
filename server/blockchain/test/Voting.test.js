const Voting = artifacts.require("Voting");

contract("Voting", (accounts) => {
  let votingInstance;

  before(async () => {
    votingInstance = await Voting.deployed();
  });

  it("should initialize with zero candidates", async () => {
    const count = await votingInstance.getCountCandidates();
    assert.equal(count.toNumber(), 0, "Initial candidate count should be 0");
  });

  it("should start and end an election", async () => {
    const instance = await Voting.new();
    await instance.startElection();
    assert.equal((await instance.getElectionState()).toNumber(), 1);
    await instance.endElection();
    assert.equal((await instance.getElectionState()).toNumber(), 2);
  });

  it("should add a candidate", async () => {
    await votingInstance.addCandidate("Alice", "Party A");
    const count = await votingInstance.getCountCandidates();
    assert.equal(count.toNumber(), 1, "Candidate count should be 1");

    const candidate = await votingInstance.getCandidate(1);
    assert.equal(candidate[0].toNumber(), 1, "Candidate ID mismatch");
    assert.equal(candidate[1], "Alice", "Candidate name mismatch");
    assert.equal(candidate[2], "Party A", "Candidate party mismatch");
    assert.equal(candidate[3].toNumber(), 0, "Candidate vote count mismatch");
  });

  it("should allow a user to vote", async () => {
    const newVotingInstance = await Voting.new();
    await newVotingInstance.addCandidate("Bob", "Party B");
    await newVotingInstance.startElection();

    const credential = web3.utils.keccak256("opaque-random-credential-bob");
    await newVotingInstance.vote(1, credential, { from: accounts[1] });
    
    const candidate = await newVotingInstance.getCandidate(1);
    assert.equal(candidate[3].toNumber(), 1, "Vote count should be 1");

    const isConsumed = await newVotingInstance.checkCredential(credential);
    assert.equal(isConsumed, true, "Credential should be marked as consumed");
  });

  it("should allow different voter IDs to vote from the same wallet", async () => {
    const newVotingInstance = await Voting.new();
    await newVotingInstance.addCandidate("Alice", "Party A");
    await newVotingInstance.addCandidate("Bob", "Party B");
    await newVotingInstance.startElection();

    const sharedWallet = accounts[2];
    const firstCredential = web3.utils.keccak256("opaque-random-credential-001");
    const secondCredential = web3.utils.keccak256("opaque-random-credential-002");

    await newVotingInstance.vote(1, firstCredential, { from: sharedWallet });
    await newVotingInstance.vote(2, secondCredential, { from: sharedWallet });

    const firstCandidate = await newVotingInstance.getCandidate(1);
    const secondCandidate = await newVotingInstance.getCandidate(2);
    assert.equal(firstCandidate[3].toNumber(), 1, "First voter should count for Alice");
    assert.equal(secondCandidate[3].toNumber(), 1, "Second voter should count for Bob");
    assert.equal(await newVotingInstance.checkCredential(firstCredential), true);
    assert.equal(await newVotingInstance.checkCredential(secondCredential), true);
  });

  it("should prevent double voting for the same voter ID", async () => {
    const newVotingInstance = await Voting.new();
    await newVotingInstance.addCandidate("Charlie", "Party C");
    await newVotingInstance.startElection();

    const credential = web3.utils.keccak256("opaque-random-credential-003");
    await newVotingInstance.vote(1, credential, { from: accounts[2] });

    try {
      await newVotingInstance.vote(1, credential, { from: accounts[2] });
      assert.fail("The transaction should have reverted");
    } catch (error) {
      assert(error.message.indexOf("revert") >= 0, "Error must contain revert");
      assert(error.message.indexOf("Voting credential has already been used") >= 0, "Error should explain that the credential was already used");
    }
  });

  it("should reject an empty voter ID hash", async () => {
    const newVotingInstance = await Voting.new();
    await newVotingInstance.addCandidate("Empty", "Party E");
    await newVotingInstance.startElection();

    try {
      await newVotingInstance.vote(1, "0x" + "00".repeat(32), { from: accounts[3] });
      assert.fail("The transaction should have reverted");
    } catch (error) {
      assert(error.message.indexOf("revert") >= 0, "Error must contain revert");
      assert(error.message.indexOf("Invalid voting credential") >= 0, "Error should explain that the credential is invalid");
    }
  });

  it("should prevent voting for invalid candidates", async () => {
    const newVotingInstance = await Voting.new();
    await newVotingInstance.addCandidate("Dave", "Party D");
    await newVotingInstance.startElection();

    try {
      await newVotingInstance.vote(99, web3.utils.keccak256("VTR-004"), { from: accounts[3] });
      assert.fail("The transaction should have reverted");
    } catch (error) {
      assert(error.message.indexOf("revert") >= 0, "Error must contain revert");
    }
  });

  it("should prevent non-owner from starting an election", async () => {
    const newVotingInstance = await Voting.new({ from: accounts[0] });

    try {
      await newVotingInstance.startElection({ from: accounts[1] });
      assert.fail("The transaction should have reverted");
    } catch (error) {
      assert(error.message.indexOf("revert") >= 0, "Error must contain revert");
      assert(error.message.indexOf("Not authorized") >= 0, "Error message should include 'Not authorized'");
    }
  });

  it("should prevent non-owner from adding a candidate", async () => {
    const newVotingInstance = await Voting.new({ from: accounts[0] });
    try {
      await newVotingInstance.addCandidate("Eve", "Party E", { from: accounts[1] });
      assert.fail("The transaction should have reverted");
    } catch (error) {
      assert(error.message.indexOf("revert") >= 0, "Error must contain revert");
      assert(error.message.indexOf("Not authorized") >= 0, "Error message should include 'Not authorized'");
    }
  });
});
