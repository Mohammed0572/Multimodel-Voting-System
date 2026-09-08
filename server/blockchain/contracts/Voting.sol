// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract Voting {
    enum ElectionState {
        NotStarted,
        Active,
        Ended
    }

    struct Candidate {
        uint256 id;
        string name;
        string party;
        uint256 voteCount;
    }

    address public immutable owner;
    address public immutable relayer;
    ElectionState public state;
    uint256 public countCandidates;

    mapping(uint256 => Candidate) public candidates;
    mapping(bytes32 => bool) public credentialUsed;

    event CandidateAdded(
        uint256 indexed candidateId,
        string name,
        string party
    );

    event ElectionStarted();
    event ElectionEnded();

    event VoteCast(
        uint256 indexed candidateId,
        bytes32 indexed credential,
        uint256 timestamp
    );

    modifier onlyOwner() {
        require(msg.sender == owner, "Only owner can perform this action");
        _;
    }

    modifier onlyRelayer() {
        require(msg.sender == relayer, "Only relayer can submit votes");
        _;
    }

    constructor(address relayerAddress) {
        require(
            relayerAddress != address(0),
            "Relayer address cannot be zero"
        );

        owner = msg.sender;
        relayer = relayerAddress;
        state = ElectionState.NotStarted;
    }

    function addCandidate(
        string calldata name,
        string calldata party
    ) external onlyOwner {
        require(
            state == ElectionState.NotStarted,
            "Election has already started"
        );
        require(bytes(name).length > 0, "Candidate name is required");
        require(bytes(name).length <= 100, "Candidate name is too long");
        require(bytes(party).length <= 100, "Party name is too long");

        countCandidates++;

        candidates[countCandidates] = Candidate({
            id: countCandidates,
            name: name,
            party: party,
            voteCount: 0
        });

        emit CandidateAdded(countCandidates, name, party);
    }

    function startElection() external onlyOwner {
        require(
            state == ElectionState.NotStarted,
            "Election has already started or ended"
        );
        require(countCandidates > 0, "Add at least one candidate");

        state = ElectionState.Active;

        emit ElectionStarted();
    }

    function endElection() external onlyOwner {
        require(state == ElectionState.Active, "Election is not active");

        state = ElectionState.Ended;

        emit ElectionEnded();
    }

    function vote(
        uint256 candidateId,
        bytes32 credential
    ) external onlyRelayer {
        require(state == ElectionState.Active, "Election is not active");
        require(
            candidateId > 0 && candidateId <= countCandidates,
            "Invalid candidate"
        );
        require(credential != bytes32(0), "Credential is required");
        require(
            !credentialUsed[credential],
            "Voting credential has already been used"
        );

        credentialUsed[credential] = true;
        candidates[candidateId].voteCount++;

        emit VoteCast(candidateId, credential, block.timestamp);
    }

    function checkCredential(
        bytes32 credential
    ) external view returns (bool) {
        return credentialUsed[credential];
    }

    function getCountCandidates() external view returns (uint256) {
        return countCandidates;
    }

    function getCandidate(
        uint256 candidateId
    )
        external
        view
        returns (
            uint256 id,
            string memory name,
            string memory party,
            uint256 voteCount
        )
    {
        require(
            candidateId > 0 && candidateId <= countCandidates,
            "Invalid candidate"
        );

        Candidate memory candidate = candidates[candidateId];

        return (
            candidate.id,
            candidate.name,
            candidate.party,
            candidate.voteCount
        );
    }

    function getElectionState() external view returns (ElectionState) {
        return state;
    }
}
