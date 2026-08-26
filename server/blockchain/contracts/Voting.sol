// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract Voting {
    address public owner;

    struct Candidate {
        uint id;
        string name;
        string party;
        uint voteCount;
    }

    mapping (uint => Candidate) public candidates;
    // One ballot per authenticated voter ID, not per MetaMask account. This allows
    // local/demo environments to use one administrator wallet for multiple voters.
    mapping (bytes32 => bool) public voters;

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
   
    function vote(uint candidateID, bytes32 voterIdHash) public {

       require(state == ElectionState.Active, "Election is not active.");
   
       require(candidateID > 0 && candidateID <= countCandidates, "Invalid candidate.");

       require(voterIdHash != bytes32(0), "Invalid voter ID.");
       require(!voters[voterIdHash], "Voter has already voted.");
              
       voters[voterIdHash] = true;
       
       candidates[candidateID].voteCount ++;
    }
    
    function checkVote(bytes32 voterIdHash) public view returns(bool){
        return voters[voterIdHash];
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
