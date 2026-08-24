// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract Voting {
    address public owner;

    enum ElectionState { NotStarted, Active, Ended }
    ElectionState public state;

    struct Candidate {
        uint id;
        string name;
        string party; 
        uint voteCount;
    }

    mapping (uint => Candidate) public candidates;
    // One ballot per authenticated voter ID, not per MetaMask account.
    mapping (bytes32 => bool) public voters;

    uint public countCandidates;

    modifier onlyOwner() {
        require(msg.sender == owner, "Only the owner can perform this action");
        _;
    }

    constructor() {
        owner = msg.sender;
        state = ElectionState.NotStarted;
    }

    function addCandidate(string memory name, string memory party) public onlyOwner returns(uint) {
        countCandidates++;
        candidates[countCandidates] = Candidate(countCandidates, name, party, 0);
        return countCandidates;
    }
   
    function vote(uint candidateID, bytes32 voterIdHash) public {
        require(state == ElectionState.Active, "Election is not currently active");
        require(candidateID > 0 && candidateID <= countCandidates, "Invalid candidate ID");
        require(voterIdHash != bytes32(0), "Invalid voter ID");

        require(!voters[voterIdHash], "You have already voted");
              
        voters[voterIdHash] = true;
        candidates[candidateID].voteCount++;      
    }
    
    function checkVote(bytes32 voterIdHash) public view returns(bool){
        return voters[voterIdHash];
    }
       
    function getCountCandidates() public view returns(uint) {
        return countCandidates;
    }

    function getCandidate(uint candidateID) public view returns (uint, string memory, string memory, uint) {
        return (candidateID, candidates[candidateID].name, candidates[candidateID].party, candidates[candidateID].voteCount);
    }

    function startElection() public onlyOwner {
        require(state == ElectionState.NotStarted, "Election is already started or ended");
        state = ElectionState.Active;
    }

    function endElection() public onlyOwner {
        require(state == ElectionState.Active, "Election is not active");
        state = ElectionState.Ended;
    }

    function getElectionState() public view returns (uint) {
        return uint(state);
    }
}
