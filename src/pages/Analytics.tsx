import { useState, useEffect, useCallback, useId } from "react";
import { Link } from "react-router-dom";
import {
  RefreshCw,
  Award,
  Vote,
  Users,
  CheckCircle2,
  ShieldCheck,
  ExternalLink,
  Copy,
  Check,
  TrendingUp,
  Clock,
  Radio,
} from "lucide-react";
import { Chakra } from "../components/Chakra";
import { API_BASE } from "../services/apiBase";

interface Candidate {
  id: number;
  name: string;
  party: string;
  votes: number;
  percentage: number;
}

interface AnalyticsData {
  election_id: string;
  election_name: string;
  state: "NotStarted" | "Active" | "Ended" | string;
  state_code: number;
  blockchain_connected: boolean;
  contract_address: string;
  chain_id: number;
  latest_block_number: number;
  turnout: {
    total_registered: number;
    total_verified: number;
    total_votes_cast: number;
    turnout_percentage: number;
  };
  candidates: Candidate[];
  leading_candidate: Candidate | null;
  winner: Candidate | null;
  updated_at: string;
}

export default function Analytics() {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState<boolean>(true);
  const [lastUpdatedSecondsAgo, setLastUpdatedSecondsAgo] = useState<number>(0);
  const [copiedContract, setCopiedContract] = useState<boolean>(false);
  const [activeTab, setActiveTab] = useState<"chart" | "table">("chart");
  const autoRefreshId = useId();

  const fetchAnalytics = useCallback(async (isBackground = false) => {
    if (!isBackground) setIsLoading(true);
    try {
      const response = await fetch(`${API_BASE}/election/analytics`);
      if (!response.ok) {
        throw new Error("Unable to fetch live election analytics.");
      }
      const json: AnalyticsData = await response.json();
      setData(json);
      setError(null);
      setLastUpdatedSecondsAgo(0);
    } catch (err: any) {
      console.error(err);
      if (!isBackground) {
        setError(err.message || "Failed to connect to election analytics service.");
      }
    } finally {
      if (!isBackground) setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchAnalytics();
  }, [fetchAnalytics]);

  // Auto-refresh interval (every 4 seconds)
  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(() => {
      void fetchAnalytics(true);
    }, 4000);
    return () => clearInterval(interval);
  }, [autoRefresh, fetchAnalytics]);

  // Second counter for "Last updated Xs ago"
  useEffect(() => {
    const timer = setInterval(() => {
      setLastUpdatedSecondsAgo((prev) => prev + 1);
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const handleCopyContract = () => {
    if (!data?.contract_address) return;
    navigator.clipboard.writeText(data.contract_address);
    setCopiedContract(true);
    setTimeout(() => setCopiedContract(false), 2000);
  };

  const getStatusBadge = () => {
    if (!data) return null;
    if (data.state === "Active") {
      return (
        <span className="inline-flex items-center gap-2 rounded-full bg-emerald-50 px-3.5 py-1 text-xs font-semibold text-emerald-800 border border-emerald-200">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
          </span>
          VOTING LIVE IN PROGRESS
        </span>
      );
    }
    if (data.state === "Ended") {
      return (
        <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-3.5 py-1 text-xs font-semibold text-amber-800 border border-amber-200">
          <Award className="size-3.5 text-amber-600" />
          ELECTION CONCLUDED · FINAL CERTIFIED
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3.5 py-1 text-xs font-semibold text-slate-700 border border-slate-200">
        <Clock className="size-3.5 text-slate-500" />
        SCHEDULED · NOT STARTED
      </span>
    );
  };

  return (
    <div className="min-h-screen bg-paper-warm text-ink pb-20">
      {/* Top Banner */}
      <div className="border-b border-hairline bg-paper">
        <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div className="flex items-start gap-4">
              <Chakra size={44} className="text-ashoka shrink-0 mt-1" />
              <div>
                <div className="flex flex-wrap items-center gap-2.5">
                  <h1 className="font-display text-2xl font-bold tracking-tight text-ink sm:text-3xl">
                    {data?.election_name || "General Election Analytics"}
                  </h1>
                  {getStatusBadge()}
                </div>
                <p className="mt-1 text-sm text-muted-foreground">
                  Official Public Results & Immutable Blockchain Turnout Dashboard
                </p>
                {data?.contract_address && (
                  <div className="mt-2 flex items-center gap-2 text-xs font-mono text-muted-foreground">
                    <span>Contract:</span>
                    <span className="rounded bg-slate-100 px-2 py-0.5 text-slate-700 font-medium">
                      {data.contract_address}
                    </span>
                    <button
                      onClick={handleCopyContract}
                      className="inline-flex items-center gap-1 text-slate-500 hover:text-ink transition-colors cursor-pointer"
                      title="Copy Address"
                    >
                      {copiedContract ? (
                        <Check className="size-3.5 text-emerald-600" />
                      ) : (
                        <Copy className="size-3.5" />
                      )}
                    </button>
                  </div>
                )}
              </div>
            </div>

            {/* Live refresh controls */}
            <div className="flex flex-wrap items-center gap-3 self-start md:self-auto">
              <div className="flex items-center gap-2 rounded-lg border border-hairline bg-paper px-3 py-1.5 text-xs text-muted-foreground shadow-xs">
                <Radio className={`size-3.5 ${autoRefresh ? "text-emerald-500 animate-pulse" : "text-slate-400"}`} />
                <label htmlFor={autoRefreshId} className="cursor-pointer select-none">Auto-refresh (4s)</label>
                <input
                  id={autoRefreshId}
                  type="checkbox"
                  checked={autoRefresh}
                  onChange={(e) => setAutoRefresh(e.target.checked)}
                  className="rounded border-slate-300 text-saffron focus:ring-saffron cursor-pointer"
                />
              </div>

              <button
                onClick={() => void fetchAnalytics()}
                disabled={isLoading}
                className="inline-flex items-center gap-1.5 rounded-lg border border-hairline bg-paper px-3 py-1.5 text-xs font-medium text-ink shadow-xs hover:bg-slate-50 disabled:opacity-50 cursor-pointer"
              >
                <RefreshCw className={`size-3.5 ${isLoading ? "animate-spin text-saffron" : ""}`} />
                <span>Refresh</span>
              </button>

              <span className="text-[11px] text-muted-foreground whitespace-nowrap">
                Updated {lastUpdatedSecondsAgo}s ago
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-7xl px-4 pt-8 sm:px-6 lg:px-8 space-y-8">
        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 flex items-center justify-between">
            <span>{error}</span>
            <button
              onClick={() => void fetchAnalytics()}
              className="text-xs font-bold underline hover:text-red-900 cursor-pointer"
            >
              Retry
            </button>
          </div>
        )}

        {/* Winner Highlight Banner (when Ended) */}
        {data?.state === "Ended" && data.winner && (
          <div className="overflow-hidden rounded-2xl border-2 border-amber-300 bg-linear-to-r from-amber-50 via-amber-100/60 to-yellow-50 p-6 shadow-sm">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div className="flex items-center gap-4">
                <div className="flex size-14 items-center justify-center rounded-2xl bg-amber-500 text-white shadow-md">
                  <Award className="size-8" />
                </div>
                <div>
                  <div className="text-xs font-bold tracking-wider uppercase text-amber-800">
                    Official Certified Election Winner
                  </div>
                  <h2 className="font-display text-2xl sm:text-3xl font-bold text-ink">
                    {data.winner.name}
                  </h2>
                  <div className="mt-1 flex items-center gap-2 text-sm text-amber-900 font-medium">
                    <span className="rounded bg-amber-200/80 px-2 py-0.5 text-xs font-bold text-amber-900">
                      {data.winner.party}
                    </span>
                    <span>·</span>
                    <span>{data.winner.votes} votes ({data.winner.percentage}%)</span>
                  </div>
                </div>
              </div>

              <div className="text-right sm:border-l sm:border-amber-200 sm:pl-6">
                <div className="text-xs text-amber-800 font-medium">Blockchain Certification</div>
                <div className="mt-1 flex items-center gap-1.5 text-xs font-bold text-emerald-800">
                  <ShieldCheck className="size-4 text-emerald-600" />
                  Smart Contract Finalized
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Participation & Turnout KPI Cards */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {/* Card 1: Total Votes Cast */}
          <div className="rounded-2xl border border-hairline bg-paper p-5 shadow-xs">
            <div className="flex items-center justify-between text-muted-foreground">
              <span className="text-xs font-semibold uppercase tracking-wider">Ballots Cast</span>
              <Vote className="size-4 text-saffron" />
            </div>
            <div className="mt-3 flex items-baseline gap-2">
              <span className="font-display text-3xl font-bold text-ink">
                {data ? data.turnout.total_votes_cast : "-"}
              </span>
              <span className="text-xs text-emerald-700 font-medium flex items-center gap-0.5">
                <CheckCircle2 className="size-3 text-emerald-600" /> Verified On-Chain
              </span>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              Cryptographically validated one-time credentials
            </p>
          </div>

          {/* Card 2: Turnout Percentage Dial */}
          <div className="rounded-2xl border border-hairline bg-paper p-5 shadow-xs">
            <div className="flex items-center justify-between text-muted-foreground">
              <span className="text-xs font-semibold uppercase tracking-wider">Voter Turnout</span>
              <TrendingUp className="size-4 text-ashoka" />
            </div>
            <div className="mt-3 flex items-center justify-between">
              <div>
                <span className="font-display text-3xl font-bold text-ink">
                  {data ? `${data.turnout.turnout_percentage}%` : "-"}
                </span>
                <p className="mt-1 text-xs text-muted-foreground">
                  {data ? `${data.turnout.total_votes_cast} of ${data.turnout.total_verified} verified` : ""}
                </p>
              </div>

              {/* Progress Ring */}
              <div className="relative size-12 shrink-0">
                <svg className="size-full -rotate-90" viewBox="0 0 36 36">
                  <path
                    className="text-slate-100"
                    strokeWidth="3.5"
                    stroke="currentColor"
                    fill="none"
                    d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                  />
                  <path
                    className="text-saffron transition-all duration-500 ease-out"
                    strokeDasharray={`${data?.turnout.turnout_percentage || 0}, 100`}
                    strokeWidth="3.5"
                    strokeLinecap="round"
                    stroke="currentColor"
                    fill="none"
                    d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                  />
                </svg>
              </div>
            </div>
          </div>

          {/* Card 3: Eligible Voters */}
          <div className="rounded-2xl border border-hairline bg-paper p-5 shadow-xs">
            <div className="flex items-center justify-between text-muted-foreground">
              <span className="text-xs font-semibold uppercase tracking-wider">Voter Registry</span>
              <Users className="size-4 text-india-green" />
            </div>
            <div className="mt-3 flex items-baseline gap-2">
              <span className="font-display text-3xl font-bold text-ink">
                {data ? data.turnout.total_verified : "-"}
              </span>
              <span className="text-xs text-muted-foreground">
                of {data?.turnout.total_registered || 0} registered
              </span>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              Biometrically enrolled and approved by admin
            </p>
          </div>

          {/* Card 4: Blockchain Ledger Height */}
          <div className="rounded-2xl border border-hairline bg-paper p-5 shadow-xs">
            <div className="flex items-center justify-between text-muted-foreground">
              <span className="text-xs font-semibold uppercase tracking-wider">Ledger Height</span>
              <ShieldCheck className="size-4 text-ashoka" />
            </div>
            <div className="mt-3 flex items-baseline gap-2 font-mono">
              <span className="font-display text-3xl font-bold text-ink">
                {data?.latest_block_number ? `#${data.latest_block_number}` : "-"}
              </span>
              <span className="text-xs text-muted-foreground font-sans">
                Chain {data?.chain_id || 1337}
              </span>
            </div>
            <p className="mt-2 text-xs text-muted-foreground flex items-center gap-1">
              <span className="size-2 rounded-full bg-emerald-500 inline-block"></span>
              {data?.blockchain_connected ? "Live Node Synced" : "Standby Mode"}
            </p>
          </div>
        </div>

        {/* Candidate Results & Vote Share Section */}
        <div className="rounded-2xl border border-hairline bg-paper p-6 shadow-xs">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-hairline pb-4">
            <div>
              <h3 className="font-display text-lg font-bold text-ink">
                Candidate Vote Share
              </h3>
              <p className="text-xs text-muted-foreground">
                Real-time tally breakdown and percentage distributions
              </p>
            </div>

            <div className="flex items-center rounded-lg bg-slate-100 p-1 text-xs">
              <button
                onClick={() => setActiveTab("chart")}
                className={`rounded-md px-3 py-1 font-medium transition-colors cursor-pointer ${
                  activeTab === "chart"
                    ? "bg-paper text-ink shadow-xs"
                    : "text-muted-foreground hover:text-ink"
                }`}
              >
                Visual Chart
              </button>
              <button
                onClick={() => setActiveTab("table")}
                className={`rounded-md px-3 py-1 font-medium transition-colors cursor-pointer ${
                  activeTab === "table"
                    ? "bg-paper text-ink shadow-xs"
                    : "text-muted-foreground hover:text-ink"
                }`}
              >
                Detailed Table
              </button>
            </div>
          </div>

          <div className="mt-6">
            {(!data?.candidates || data.candidates.length === 0) ? (
              <div className="py-12 text-center text-sm text-muted-foreground">
                No candidates have been registered for this election yet.
              </div>
            ) : activeTab === "chart" ? (
              <div className="space-y-6">
                {data.candidates.map((candidate, idx) => {
                  const isLeader = data.leading_candidate?.id === candidate.id && candidate.votes > 0;
                  const isWinner = data.winner?.id === candidate.id;

                  // Distinct bar accents
                  const barColors = [
                    "from-orange-500 to-amber-500",
                    "from-blue-600 to-indigo-600",
                    "from-emerald-600 to-teal-600",
                    "from-purple-600 to-pink-600",
                    "from-cyan-600 to-blue-600",
                  ];
                  const barColor = barColors[idx % barColors.length];

                  return (
                    <div key={candidate.id} className="group">
                      <div className="flex items-center justify-between text-sm mb-1.5">
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-ink">{candidate.name}</span>
                          <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-700 font-medium">
                            {candidate.party}
                          </span>
                          {isWinner && (
                            <span className="inline-flex items-center gap-1 rounded bg-amber-100 px-2 py-0.5 text-xs font-bold text-amber-800">
                              🏆 Winner
                            </span>
                          )}
                          {!isWinner && isLeader && data.state === "Active" && (
                            <span className="inline-flex items-center gap-1 rounded bg-emerald-100 px-2 py-0.5 text-xs font-bold text-emerald-800">
                              Leading
                            </span>
                          )}
                        </div>

                        <div className="flex items-baseline gap-2">
                          <span className="font-mono text-sm font-bold text-ink">
                            {candidate.votes} votes
                          </span>
                          <span className="font-mono text-xs text-muted-foreground">
                            ({candidate.percentage}%)
                          </span>
                        </div>
                      </div>

                      {/* Bar Track */}
                      <div className="relative h-4 w-full overflow-hidden rounded-full bg-slate-100">
                        <div
                          className={`h-full rounded-full bg-linear-to-r ${barColor} transition-all duration-700 ease-out`}
                          style={{ width: `${Math.max(candidate.percentage, 1.5)}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-hairline text-xs font-semibold uppercase text-muted-foreground">
                      <th className="py-3 px-4">#</th>
                      <th className="py-3 px-4">Candidate Name</th>
                      <th className="py-3 px-4">Party Affiliation</th>
                      <th className="py-3 px-4 text-right">Votes</th>
                      <th className="py-3 px-4 text-right">Share</th>
                      <th className="py-3 px-4 text-center">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-hairline">
                    {data.candidates.map((cand) => (
                      <tr key={cand.id} className="hover:bg-slate-50/50">
                        <td className="py-3 px-4 font-mono text-xs text-muted-foreground">
                          {cand.id}
                        </td>
                        <td className="py-3 px-4 font-bold text-ink">{cand.name}</td>
                        <td className="py-3 px-4">
                          <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
                            {cand.party}
                          </span>
                        </td>
                        <td className="py-3 px-4 text-right font-mono font-bold text-ink">
                          {cand.votes}
                        </td>
                        <td className="py-3 px-4 text-right font-mono font-bold text-saffron">
                          {cand.percentage}%
                        </td>
                        <td className="py-3 px-4 text-center">
                          {data.winner?.id === cand.id ? (
                            <span className="inline-flex items-center gap-1 text-xs font-bold text-amber-700">
                              🏆 Winner
                            </span>
                          ) : data.leading_candidate?.id === cand.id && cand.votes > 0 ? (
                            <span className="text-xs font-semibold text-emerald-700">
                              Leading
                            </span>
                          ) : (
                            <span className="text-xs text-muted-foreground">-</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {/* Audit & Verification Callout */}
        <div className="rounded-2xl border border-hairline bg-paper p-6 shadow-xs flex flex-col md:flex-row items-center justify-between gap-6">
          <div className="flex items-start gap-4">
            <div className="flex size-12 items-center justify-center rounded-xl bg-ashoka/10 text-ashoka shrink-0">
              <ShieldCheck className="size-6" />
            </div>
            <div>
              <h4 className="font-display text-base font-bold text-ink">
                Cryptographic Audit & Observer Verification
              </h4>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl leading-relaxed">
                Every vote cast in this election is cryptographically hashed with a one-time credential and committed
                to the smart contract ledger. Election administrators can export signed cryptographic audit reports (PDF & JSON)
                containing all block hashes and transaction logs.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3 shrink-0">
            <Link
              to="/admin"
              className="inline-flex items-center gap-2 rounded-xl bg-ink px-4 py-2.5 text-xs font-semibold text-paper shadow-xs hover:bg-saffron transition-colors cursor-pointer"
            >
              <span>Admin Audit Console</span>
              <ExternalLink className="size-3.5" />
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
