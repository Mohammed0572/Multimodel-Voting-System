// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

contract Voting {
    address public immutable owner;

    struct Candidate {
        uint id;
        string name;
        string party;
        uint voteCount;
    }

    mapping (uint => Candidate) public candidates;
    // Opaque voting credentials are issued off-chain after authentication.
    // No voter ID or voter-ID hash is written to this contract.
    mapping (bytes32 => bool) public credentialUsed;

    enum ElectionState {
        NotStarted,
        Active,
        Ended
    }

    ElectionState public state;
    uint public countCandidates;

    constructor() {
        owner = msg.sender;
        state = ElectionState.NotStarted;
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "Not authorized");
        _;
    }

    function addCandidate(string memory name, string memory party) public onlyOwner returns(uint) {
               countCandidates ++;
               candidates[countCandidates] = Candidate(countCandidates, name, party, 0);
               return countCandidates;
    }
   
    function vote(uint candidateID, bytes32 credential) public {

       require(state == ElectionState.Active, "Election is not active.");
   
       require(candidateID > 0 && candidateID <= countCandidates, "Invalid candidate.");

       require(credential != bytes32(0), "Invalid voting credential.");
       require(!credentialUsed[credential], "Voting credential has already been used.");
              
       credentialUsed[credential] = true;
       
       candidates[candidateID].voteCount ++;
    }
    
    function checkCredential(bytes32 credential) public view returns(bool){
        return credentialUsed[credential];
    }
       
    function getCountCandidates() public view returns(uint) {
        return countCandidates;
    }

    function getCandidate(uint candidateID) public view returns (uint,string memory, string memory,uint) {
        return (candidateID,candidates[candidateID].name,candidates[candidateID].party,candidates[candidateID].voteCount);
    }

    function startElection() public onlyOwner {
        require(state == ElectionState.NotStarted, "Election has already started.");
        state = ElectionState.Active;
    }

    function endElection() public onlyOwner {
        require(state == ElectionState.Active, "Election is not active.");
        state = ElectionState.Ended;
    }

    function getElectionState() public view returns (ElectionState) {
        return state;
    }
}
