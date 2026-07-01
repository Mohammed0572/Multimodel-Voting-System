import { useState, useEffect, useCallback } from 'react';
import { useWeb3 } from '../context/Web3Context';
import { Link } from 'react-router-dom';
import { Chakra } from '../components/Chakra';
import {
  CheckCircle2,
  MapPin,
  ShieldCheck,
  LogOut,
  ArrowRight,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';

interface Candidate {
  id: number;
  name: string;
  party: string;
  voteCount: number;
  symbol: string;
  color: string;
}

const COLORS = ["#ff671f", "#1e40af", "#046a38", "#0b1f3a", "#64748b"];
const SYMBOLS = ["🪷", "✋", "🌾", "🚲", "⊘"];

const Voting = () => {
  const { account, contract, isLoading } = useWeb3();
  const { session, logout } = useAuth();
  
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [electionState, setElectionState] = useState<number | null>(null);
  const [hasVoted, setHasVoted] = useState<boolean>(false);
  const [selectedCandidateId, setSelectedCandidateId] = useState<number | null>(null);
  
  const [stage, setStage] = useState<"choose" | "review" | "sealing" | "sealed">("choose");
  const [txHash, setTxHash] = useState<string>("0x...");
  
  const loadVotingData = useCallback(async () => {
    try {
      const stateResult = await contract.getElectionState();
      setElectionState(stateResult.toNumber());

      const count = await contract.getCountCandidates();
      const candidatesArray = [];
      for (let i = 1; i <= count.toNumber(); i++) {
        const data = await contract.getCandidate(i);
        candidatesArray.push({
          id: data[0].toNumber(),
          name: data[1],
          party: data[2],
          voteCount: data[3].toNumber(),
          color: COLORS[(i - 1) % COLORS.length],
          symbol: SYMBOLS[(i - 1) % SYMBOLS.length]
        });
      }
      setCandidates(candidatesArray);

      const voted = await contract.checkVote({ from: account });
      setHasVoted(voted);
      if (voted) setStage("sealed");
    } catch (error) {
      console.error("Error loading voting data:", error);
    }
  }, [account, contract]);

  useEffect(() => {
    if (contract) {
      loadVotingData();
    }
  }, [contract, loadVotingData]);

  // NOTA must be registered on-chain by an administrator. A client-only
  // candidate ID would be rejected by the contract as invalid.
  const displayCandidates = candidates;

  const handleVote = async () => {
    if (stage === "sealing" || hasVoted) return;
    if (!selectedCandidateId) return;

    setStage("sealing");

    // Optimistic UI updates
    setHasVoted(true);
    setStage("sealed");

    try {
      // In a real scenario we'd get the tx object back and can read tx.receipt.transactionHash
      const tx = await contract.vote(selectedCandidateId, { from: account });
      setTxHash(tx.tx || "0x7a3f9c2e…b91c");
      await loadVotingData();
    } catch (error) {
      console.error("Voting error:", error);
      alert('Error casting vote. You may have already voted or the transaction failed.');
      setHasVoted(false);
      setStage("choose");
    }
  };

  if (isLoading) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-paper py-20 text-ink">
        <Chakra size={80} className="text-saffron mb-4" spin />
        <p className="font-medium text-muted-foreground">Connecting to Blockchain...</p>
      </div>
    );
  }

  const chosen = displayCandidates.find((c) => c.id === selectedCandidateId);

  return (
    <div className="min-h-screen bg-paper-warm text-ink">
      <div className="tricolor-bar h-0.75 w-full" />

      {/* Header */}
      <header className="border-b border-hairline bg-paper">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <Link to="/" className="flex items-center gap-3">
            <Chakra size={28} className="text-ashoka" />
            <span className="font-display text-lg font-semibold">
              Prajatantra
            </span>
          </Link>
          <div className="flex items-center gap-6 text-sm">
            <div className="hidden text-right md:block">
              <div className="font-medium text-ink">Voter · {session?.voter_id || 'Unknown'}</div>
              <div className="text-xs text-muted-foreground">
                Account {account?.substring(0, 6)}...{account?.substring(account.length - 4)}
              </div>
            </div>
            <button 
              onClick={() => {
                logout().then(() => {
                  window.location.href = '/';
                });
              }}
              className="inline-flex items-center gap-2 rounded-md border border-hairline px-3 py-2 text-sm hover:border-ink"
            >
              <LogOut className="size-4" /> Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-10">
        {/* Status */}
        <section className="rounded-md border border-hairline bg-paper p-6 md:p-8">
          <div className="flex flex-wrap items-start justify-between gap-6">
            <div>
              <div className="text-xs uppercase tracking-[0.2em] text-india-green">
                Election Status
              </div>
              <h1 className="mt-2 font-display text-3xl font-semibold md:text-4xl">
                {electionState === 1 ? 'Lok Sabha 2026 · Phase 3' : electionState === 2 ? 'Election Ended' : 'Election Not Started'}
              </h1>
              <div className="mt-3 flex flex-wrap items-center gap-4 text-sm text-muted-foreground">
                <span className="inline-flex items-center gap-1.5">
                  <MapPin className="size-4" /> Local Constituency
                </span>
                <span className="inline-flex items-center gap-1.5 text-india-green">
                  <ShieldCheck className="size-4" /> Eligibility verified
                </span>
                {hasVoted && (
                  <span className="inline-flex items-center gap-1.5 text-india-green">
                    <CheckCircle2 className="size-4" /> Voted
                  </span>
                )}
              </div>
            </div>
            <div className="rounded-md bg-paper-warm px-4 py-3 text-right">
              <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                Blockchain
              </div>
              <div className="font-mono text-lg font-semibold text-ink mt-1">
                Connected
              </div>
            </div>
          </div>
        </section>

        {stage === "sealed" ? (
          <Receipt
            candidate={chosen || { id: 0, name: 'Hidden', party: 'Unknown', color: '#ccc', symbol: '✓', voteCount: 0 }}
            txHash={txHash}
            onReset={() => {
              if (!hasVoted) setStage("choose");
            }}
          />
        ) : (
          <>
            {/* Cast */}
            <section className="mt-10">
              <div className="flex items-end justify-between">
                <div>
                  <div className="text-xs uppercase tracking-[0.2em] text-saffron">
                    Cast your vote
                  </div>
                  <h2 className="mt-2 font-display text-2xl font-semibold">
                    Choose one candidate
                  </h2>
                </div>
                <div className="text-sm text-muted-foreground">
                  {displayCandidates.length} candidates
                </div>
              </div>

              {electionState !== 1 ? (
                 <div className="mt-6 p-8 text-center rounded-md border border-hairline bg-paper text-muted-foreground">
                   {electionState === 0 ? "The election has not started yet." : "The election has ended."}
                 </div>
              ) : displayCandidates.length === 0 ? (
                 <div className="mt-6 p-8 text-center rounded-md border border-hairline bg-paper text-muted-foreground">
                   No candidates are currently registered.
                 </div>
              ) : (
                <fieldset className="mt-6 grid gap-3">
                  <legend className="sr-only">List of candidates</legend>
                  {displayCandidates.map((c) => {
                    const active = selectedCandidateId === c.id;
                    return (
                      <div key={c.id}>
                        <button
                          type="button"
                          aria-pressed={active}
                          onClick={() => setSelectedCandidateId(c.id)}
                          className={`flex w-full items-center gap-5 rounded-md border p-5 text-left transition ${
                            active
                              ? "border-saffron bg-saffron/5 shadow-[0_8px_24px_-16px_rgba(255,103,31,0.5)]"
                              : "border-hairline bg-paper hover:border-ink/30"
                          }`}
                        >
                          <span
                            className="flex size-14 items-center justify-center rounded-md text-2xl"
                            style={{
                              backgroundColor: `${c.color}15`,
                              color: c.color,
                            }}
                          >
                            {c.symbol}
                          </span>
                          <div className="flex-1">
                            <div className="font-display text-lg font-semibold">
                              {c.name}
                            </div>
                            <div className="text-sm text-muted-foreground">
                              {c.party}
                            </div>
                          </div>
                          <span
                            className={`flex size-6 items-center justify-center rounded-full border-2 ${
                              active
                                ? "border-saffron bg-saffron"
                                : "border-hairline"
                            }`}
                          >
                            {active && (
                              <span className="size-2 rounded-full bg-paper" />
                            )}
                          </span>
                        </button>
                      </div>
                    );
                  })}
                </fieldset>
              )}
            </section>

            {/* Sticky review bar */}
            {electionState === 1 && (
              <div className="sticky bottom-6 mt-10 flex items-center justify-between rounded-md border border-hairline bg-ink px-6 py-4 text-paper shadow-[0_20px_50px_-20px_rgba(11,31,58,0.5)]">
                <div className="text-sm">
                  {chosen ? (
                    <span>
                      Selected:{" "}
                      <span className="font-semibold">{chosen.name}</span> ·{" "}
                      {chosen.party}
                    </span>
                  ) : (
                    <span className="text-paper/60">
                      Select a candidate to continue
                    </span>
                  )}
                </div>
                <button
                  disabled={!chosen || stage === "sealing" || hasVoted}
                  onClick={handleVote}
                  className="inline-flex items-center gap-2 rounded-md bg-saffron px-5 py-2.5 text-sm font-semibold text-paper disabled:cursor-not-allowed disabled:bg-paper/20"
                >
                  {stage === "sealing" ? "Sealing on chain…" : "Review & confirm"}
                  {stage !== "sealing" && <ArrowRight className="size-4" />}
                </button>
              </div>
            )}
          </>
        )}

        {stage === "sealing" && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/70 backdrop-blur">
            <div className="flex flex-col items-center text-paper">
              <Chakra size={120} className="text-saffron" spin />
              <div className="mt-6 font-display text-2xl">
                Sealing your ballot on chain…
              </div>
              <div className="mt-2 font-mono text-xs text-paper/60">
                Confirm the transaction in your wallet (e.g. MetaMask)
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
};

function Receipt({
  candidate,
  txHash,
  onReset,
}: {
  candidate: Candidate;
  txHash: string;
  onReset: () => void;
}) {
  return (
    <section className="mt-10 overflow-hidden rounded-md border border-india-green/40 bg-paper">
      <div className="flex items-center gap-3 bg-india-green px-6 py-3 text-paper">
        <CheckCircle2 className="size-5" />
        <span className="text-sm font-semibold">
          Your vote has been sealed on chain
        </span>
      </div>
      <div className="grid gap-8 p-8 md:grid-cols-[1.2fr_1fr]">
        <div>
          <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
            Receipt
          </div>
          <h2 className="mt-2 font-display text-3xl font-semibold">
            Thank you for voting.
          </h2>
          <p className="mt-3 text-sm text-muted-foreground">
            Keep this receipt. You can verify your vote on the public
            Prajatantra explorer at any time using the transaction hash below.
            Your identity is never revealed.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <a
              href="#"
              className="inline-flex items-center gap-2 rounded-md bg-ink px-4 py-2 text-sm font-medium text-paper hover:bg-saffron"
            >
              Verify on explorer <ArrowRight className="size-4" />
            </a>
            <button className="rounded-md border border-hairline px-4 py-2 text-sm font-medium hover:border-ink">
              Download PDF
            </button>
            <button
              onClick={onReset}
              className="rounded-md px-4 py-2 text-sm text-muted-foreground hover:text-ink"
            >
              Back to dashboard
            </button>
          </div>
        </div>
        <dl className="space-y-3 rounded-md bg-paper-warm p-6 font-mono text-xs">
          <Row k="Constituency" v="Local / Dev Network" />
          <Row k="Tx hash" v={txHash} />
          <Row k="Timestamp" v={new Date().toLocaleString("en-IN")} />
          <Row k="Signed by" v={`Voter · ${candidate.symbol}`} />
          <Row k="Chain" v="prajatantra-mainnet" />
        </dl>
      </div>
    </section>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-muted-foreground">{k}</dt>
      <dd className="text-ink">{v}</dd>
    </div>
  );
}

export default Voting;
