
pragma solidity ^0.5.15;

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
    mapping (address => bool) public voters;

    uint public countCandidates;

    modifier onlyOwner() {
        require(msg.sender == owner, "Only the owner can perform this action");
        _;
    }

    constructor() public {
        owner = msg.sender;
        state = ElectionState.NotStarted;
    }

    function addCandidate(string memory name, string memory party) public onlyOwner returns(uint) {
        countCandidates++;
        candidates[countCandidates] = Candidate(countCandidates, name, party, 0);
        return countCandidates;
    }
   
    function vote(uint candidateID) public {
        require(state == ElectionState.Active, "Election is not currently active");
        require(candidateID > 0 && candidateID <= countCandidates, "Invalid candidate ID");

        // Has not voted before
        require(!voters[msg.sender], "You have already voted");
              
        voters[msg.sender] = true;
        candidates[candidateID].voteCount++;      
    }
    
    function checkVote() public view returns(bool){
        return voters[msg.sender];
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
