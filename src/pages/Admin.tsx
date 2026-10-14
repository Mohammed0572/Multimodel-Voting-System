import { useState, useEffect, useCallback, useMemo } from "react";
import { useWeb3 } from "../context/Web3Context";
import { useLanguage } from "../context/LanguageContext";
import { API_BASE } from "../context/AuthContext";

type Status = { message: string; type: string };

type Student = {
  usn: string;
  branch: "CB";
  className: "CSBS";
  batch: "2023" | "2024";
  number: number;
  role: string;
  studentName: string;
  idVerified: boolean;
  faceUpdatePending: boolean;
  hasVoted: boolean;
  verifiedBy: string | null;
  verifiedAt: string | null;
};

type CandidateResult = {
  id: number;
  name: string;
  party: string;
  votes: string;
};

type PendingAction = "candidate" | "start" | "end" | null;

const Admin = () => {
  const { t } = useLanguage();
  const { account, contract, isLoading, error, connectWallet } = useWeb3();
  const [candidateName, setCandidateName] = useState("");
  const [candidateParty, setCandidateParty] = useState("");
  const [electionName, setElectionName] = useState("");
  const [savedElectionName, setSavedElectionName] = useState("");
  const [isSavingElectionName, setIsSavingElectionName] = useState(false);
  const [contractOwner, setContractOwner] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>({ message: "", type: "" });
  const [electionState, setElectionState] = useState<number | null>(null);
  const [studentSearch, setStudentSearch] = useState("");
  const [students, setStudents] = useState<Student[]>([]);
  const [turnoutError, setTurnoutError] = useState<string | null>(null);
  const [backendElectionId, setBackendElectionId] = useState("");
  const [isLoadingStudents, setIsLoadingStudents] = useState(true);
  const [updatingStudentUsn, setUpdatingStudentUsn] = useState<string | null>(null);
  const [results, setResults] = useState<CandidateResult[]>([]);
  const [isLoadingResults, setIsLoadingResults] = useState(true);
  const [resultsError, setResultsError] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<PendingAction>(null);

  const loadState = useCallback(async () => {
    try {
      const stateResult = await contract.getElectionState();
      setElectionState(stateResult.toNumber());
    } catch (loadError) {
      console.error(loadError);
    }
  }, [contract]);

  const loadResults = useCallback(async () => {
    if (!contract) {
      setResults([]);
      setResultsError("The deployed voting contract is not connected.");
      setIsLoadingResults(false);
      return;
    }

    setIsLoadingResults(true);
    setResultsError(null);
    try {
      const countRaw = contract.countCandidates
        ? await contract.countCandidates()
        : await contract.getCountCandidates();
      const count = Number(countRaw.toString());
      if (!Number.isSafeInteger(count) || count < 0) {
        throw new Error("The contract returned an invalid candidate count.");
      }

      const candidateRows = await Promise.all(
        Array.from({ length: count }, async (_, index) => {
          const candidate = await contract.getCandidate(index + 1);
          return {
            id: Number(candidate[0].toString()),
            name: String(candidate[1]),
            party: String(candidate[2]),
            // Keep the on-chain integer as a decimal string to avoid rounding.
            votes: candidate[3].toString(),
          };
        }),
      );
      setResults(candidateRows);
    } catch (resultsLoadError) {
      console.error("Unable to load on-chain election results:", resultsLoadError);
      setResultsError(
        resultsLoadError instanceof Error
          ? resultsLoadError.message
          : "Unable to read election results from the blockchain.",
      );
    } finally {
      setIsLoadingResults(false);
    }
  }, [contract]);

  const updateStatus = useCallback((message: string, type: string) => {
    setStatus({ message, type });
    setTimeout(() => setStatus({ message: "", type: "" }), 5000);
  }, []);

  const loadStudents = useCallback(async (background = false) => {
    if (!background) setIsLoadingStudents(true);
    try {
      const response = await fetch(`${API_BASE}/admin/voters`, {
        credentials: "include",
        cache: "no-store",
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(
          response.status === 401 || response.status === 403
            ? "Admin session expired. Log in again to manage the voter registry."
            : data.detail || "Unable to load the CSBS voter registry.",
        );
      }
      const data = await response.json();
      const nextStudents = Array.isArray(data.students) ? data.students : [];
      setStudents(nextStudents);
      if (
        nextStudents.some((student: Student) => typeof student.hasVoted !== "boolean")
      ) {
        setTurnoutError(
          "The backend has not loaded voter participation data yet. Restart the backend, then refresh turnout.",
        );
      } else {
        if (typeof data.election_id === "string") {
          setBackendElectionId(data.election_id.toLowerCase());
        }
        setTurnoutError(null);
      }
    } catch (studentError) {
      console.error(studentError);
      setTurnoutError(
        studentError instanceof Error
          ? studentError.message
          : "Unable to refresh voter participation from the backend.",
      );
      if (!background) {
        updateStatus(
          studentError instanceof Error
            ? studentError.message
            : "Unable to load the CSBS registry from SQLite.",
          "error",
        );
      }
    } finally {
      if (!background) setIsLoadingStudents(false);
    }
  }, [updateStatus]);

  useEffect(() => {
    if (contract) loadState();
  }, [contract, loadState]);

  useEffect(() => {
    void loadResults();
  }, [loadResults]);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/election`, { credentials: "include" })
      .then(async (response) => {
        if (!response.ok) throw new Error("Unable to load the election name.");
        return response.json();
      })
      .then((data) => {
        if (!cancelled) {
          const name = String(data.name || "");
          setElectionName(name);
          setSavedElectionName(name);
          if (typeof data.election_id === "string") {
            setBackendElectionId(data.election_id.toLowerCase());
          }
        }
      })
      .catch((loadError) => console.error(loadError));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!contract) return;
    void contract.owner().then((owner: string) => setContractOwner(owner));
  }, [contract]);

  useEffect(() => {
    void loadStudents();
  }, [loadStudents]);

  useEffect(() => {
    if (electionState !== 1) return;
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") void loadStudents(true);
    };
    const intervalId = window.setInterval(() => {
      void loadStudents(true);
    }, 10_000);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    window.addEventListener("focus", refreshWhenVisible);
    return () => {
      window.clearInterval(intervalId);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
      window.removeEventListener("focus", refreshWhenVisible);
    };
  }, [electionState, loadStudents]);

  const handleEligibilityVerification = async (student: Student) => {
    setUpdatingStudentUsn(student.usn);
    try {
      const response = await fetch(
        `${API_BASE}/admin/voters/${student.usn}/verify`,
        {
          method: "PATCH",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ verified: !student.idVerified }),
        },
      );
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(
          response.status === 401 || response.status === 403
            ? "Admin session expired. Log in again to verify this ID card."
            : data.detail || "Unable to update ID-card verification.",
        );
      }
      setStudents((current) =>
        current.map((item) =>
          item.usn === student.usn
            ? { ...item, idVerified: !student.idVerified }
            : item,
        ),
      );
      updateStatus(
        `${student.usn} marked as ${student.idVerified ? "not verified" : "eligible after ID-card check"}.`,
        "success",
      );
    } catch (verificationError) {
      console.error(verificationError);
      updateStatus(
        verificationError instanceof Error
          ? verificationError.message
          : "Unable to save the ID-card verification.",
        "error",
      );
    } finally {
      setUpdatingStudentUsn(null);
    }
  };

  const handleApproveFaceUpdate = async (student: Student) => {
    setUpdatingStudentUsn(student.usn);
    try {
      const response = await fetch(
        `${API_BASE}/admin/voters/${encodeURIComponent(student.usn)}/approve-face-update`,
        { method: "POST", credentials: "include" },
      );
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || "Unable to approve the face update.");
      }
      setStudents((current) =>
        current.map((item) =>
          item.usn === student.usn ? { ...item, faceUpdatePending: false } : item,
        ),
      );
      updateStatus(`Replacement face profile approved for ${student.usn}.`, "success");
    } catch (approvalError) {
      updateStatus(
        approvalError instanceof Error ? approvalError.message : "Unable to approve the face update.",
        "error",
      );
    } finally {
      setUpdatingStudentUsn(null);
    }
  };

  const handleDeleteVoter = async (student: Student) => {
    if (
      !window.confirm(
        `Delete voter ${student.usn}? This removes their face registration and voting credentials.`,
      )
    ) {
      return;
    }

    try {
      const response = await fetch(
        `${API_BASE}/admin/voters/${encodeURIComponent(student.usn)}`,
        {
          method: "DELETE",
          credentials: "include",
        },
      );
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new Error(data?.detail || "Unable to delete voter.");
      }
      setStudents((current) =>
        current.filter((item) => item.usn !== student.usn),
      );
      updateStatus(`${student.usn} was deleted.`, "success");
    } catch (deleteError) {
      console.error(deleteError);
      updateStatus(
        deleteError instanceof Error
          ? deleteError.message
          : "Unable to delete voter.",
        "error",
      );
    }
  };

  const handleAddCandidate = async (event: React.FormEvent) => {
    event.preventDefault();
    if (pendingAction) return;
    if (!candidateName.trim() || !candidateParty.trim()) {
      updateStatus("Please fill all candidate fields.", "error");
      return;
    }
    if (!contract || !account) {
      updateStatus(
        "Connect the MetaMask account used to deploy the contract.",
        "error",
      );
      return;
    }

    setPendingAction("candidate");
    let previousCandidateCount: number | null = null;
    try {
      const owner = await contract.owner();
      if (owner.toLowerCase() !== account.toLowerCase()) {
        updateStatus(
          `Only the contract owner can add candidates. Switch MetaMask to ${owner}.`,
          "error",
        );
        return;
      }
      const count = contract.countCandidates
        ? await contract.countCandidates()
        : await contract.getCountCandidates();
      previousCandidateCount = Number(count.toString());
      updateStatus("Processing transaction on blockchain...", "info");
      await contract.addCandidate(candidateName, candidateParty, {
        from: account,
      });
      await loadResults();
      updateStatus("Candidate added successfully!", "success");
      setCandidateName("");
      setCandidateParty("");
    } catch (candidateError) {
      console.error(candidateError);
      if (previousCandidateCount !== null) {
        try {
          const count = contract.countCandidates
            ? await contract.countCandidates()
            : await contract.getCountCandidates();
          if (Number(count.toString()) > previousCandidateCount) {
            await loadResults();
            setCandidateName("");
            setCandidateParty("");
            updateStatus(
              "Candidate was added on-chain; the wallet response was delayed.",
              "success",
            );
            return;
          }
        } catch (recoveryError) {
          console.error("Could not confirm candidate state on-chain:", recoveryError);
        }
      }
      const errorMessage =
        candidateError instanceof Error
          ? candidateError.message
          : String(candidateError);
      updateStatus(
        errorMessage.includes("Not authorized")
          ? "Only the contract owner can add candidates. Switch MetaMask to the deploying account."
          : `Failed to add candidate: ${errorMessage}`,
        "error",
      );
    } finally {
      setPendingAction(null);
    }
  };

  const handleStartElection = async () => {
    if (pendingAction) return;
    if (!electionName.trim() || electionName.trim() !== savedElectionName) {
      updateStatus("Save the election name before starting the election.", "error");
      return;
    }
    if (!contract || !account) {
      updateStatus(
        "Connect the contract owner wallet before starting the election.",
        "error",
      );
      return;
    }

    setPendingAction("start");
    try {
      const [owner, currentState] = await Promise.all([
        contract.owner(),
        contract.getElectionState(),
      ]);
      if (owner.toLowerCase() !== account.toLowerCase()) {
        updateStatus(
          "Only the contract owner can start the election.",
          "error",
        );
        return;
      }
      if (Number(currentState.toString()) !== 0) {
        updateStatus("The election has already started or ended.", "error");
        return;
      }
      updateStatus("Processing transaction on blockchain...", "info");
      await contract.startElection({ from: account });
      updateStatus("Election started successfully!", "success");
      await loadState();
    } catch (startError) {
      console.error(startError);
      try {
        const currentState = Number(
          (await contract.getElectionState()).toString(),
        );
        if (currentState === 1) {
          await loadState();
          updateStatus(
            "Election started on-chain; the wallet response was delayed.",
            "success",
          );
          return;
        }
      } catch (recoveryError) {
        console.error("Could not confirm election state on-chain:", recoveryError);
      }
      const errorMessage =
        startError instanceof Error ? startError.message : String(startError);
      updateStatus(`Failed to start election: ${errorMessage}`, "error");
    } finally {
      setPendingAction(null);
    }
  };

  const handleEndElection = async () => {
    if (pendingAction) return;
    if (!contract || !account) {
      updateStatus(
        "Connect the contract owner wallet before ending the election.",
        "error",
      );
      return;
    }

    setPendingAction("end");
    try {
      updateStatus("Processing transaction on blockchain...", "info");
      await contract.endElection({ from: account });
      updateStatus("Election ended successfully!", "success");
      await Promise.all([loadState(), loadResults()]);
    } catch (endError) {
      console.error(endError);
      try {
        const currentState = Number(
          (await contract.getElectionState()).toString(),
        );
        if (currentState === 2) {
          await Promise.all([loadState(), loadResults()]);
          updateStatus(
            "Election ended on-chain; the wallet response was delayed.",
            "success",
          );
          return;
        }
      } catch (recoveryError) {
        console.error("Could not confirm election state on-chain:", recoveryError);
      }
      updateStatus(
        endError instanceof Error
          ? `Failed to end election: ${endError.message}`
          : "Failed to end election. Ensure you are the owner and it is currently active.",
        "error",
      );
    } finally {
      setPendingAction(null);
    }
  };

  const handleSaveElectionName = async () => {
    const name = electionName.trim();
    if (!name) {
      updateStatus("Enter a name for this election before saving.", "error");
      return;
    }
    setIsSavingElectionName(true);
    try {
      const response = await fetch(`${API_BASE}/admin/election`, {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || "Unable to save election name.");
      }
      setElectionName(name);
      setSavedElectionName(name);
      updateStatus("Election name saved and shown in the voting portal.", "success");
    } catch (saveError) {
      updateStatus(
        saveError instanceof Error ? saveError.message : "Unable to save election name.",
        "error",
      );
    } finally {
      setIsSavingElectionName(false);
    }
  };

  const filteredStudents = useMemo(() => {
    const query = studentSearch.trim().toLowerCase();
    if (!query) return students;
    return students.filter((student) =>
      student.usn.toLowerCase().includes(query),
    );
  }, [studentSearch, students]);

  const finalOutcome = useMemo(() => {
    if (electionState !== 2 || isLoadingResults || resultsError) return null;
    if (results.length === 0) {
      return { kind: "no-votes" as const, winners: [] as CandidateResult[] };
    }

    const highestVoteCount = results.reduce(
      (highest, candidate) =>
        BigInt(candidate.votes) > highest ? BigInt(candidate.votes) : highest,
      0n,
    );
    if (highestVoteCount === 0n) {
      return { kind: "no-votes" as const, winners: [] as CandidateResult[] };
    }

    const winners = results.filter(
      (candidate) => BigInt(candidate.votes) === highestVoteCount,
    );
    return {
      kind: winners.length === 1 ? ("winner" as const) : ("tie" as const),
      winners,
    };
  }, [electionState, isLoadingResults, results, resultsError]);

  if (isLoading) {
    return (
      <div className="flex justify-center py-20">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600" />
      </div>
    );
  }

  const electionLabel =
    electionState === 1
      ? "Active"
      : electionState === 2
        ? "Ended"
        : "Not Started";
  const connectedElectionId = String(
    contract?.address || contract?.options?.address || "",
  ).toLowerCase();
  const electionSessionMismatch = Boolean(
    backendElectionId &&
      connectedElectionId &&
      backendElectionId !== connectedElectionId,
  );

  return (
    <div className="gov-panel p-6 sm:p-8">
      <div className="admin-hero mb-8">
        <div>
          <p className="admin-eyebrow">CLASS ELECTION / ADMIN CONSOLE</p>
          <h1 className="text-3xl sm:text-4xl font-bold font-heading text-[#112e51]">
            {t("admin.title")}
          </h1>
          <p className="text-[#565c65] mt-2">
            CSBS voter registry, election controls, and candidate management in
            one place.
          </p>
        </div>
        <div className="admin-status-pill">
          <span className="admin-status-dot" /> {electionLabel}
        </div>
      </div>

      {status.message && (
        <div
          className={`mb-6 ${status.type === "error" ? "gov-alert-error" : status.type === "success" ? "gov-alert-success" : "gov-alert-info"} rounded-sm`}
        >
          <strong>Status:</strong> {status.message}
        </div>
      )}

      {error && (
        <div className="gov-alert-error mb-6 rounded-sm" role="status">
          <strong>Blockchain unavailable:</strong> {error} The voter registry
          and ID-card checks below remain available.
        </div>
      )}

      <section
        className="admin-roster-card mb-8"
        aria-labelledby="results-heading"
      >
        <div className="admin-section-heading">
          <div>
            <p className="admin-eyebrow">ON-CHAIN TALLY</p>
            <h2 id="results-heading">Candidate results</h2>
            <p className="mt-1 text-sm text-[#565c65]">
              Aggregate vote counts read directly from the deployed voting contract.
            </p>
          </div>
          <button
            type="button"
            className="gov-button"
            onClick={() => void loadResults()}
            disabled={isLoadingResults || !contract}
          >
            {isLoadingResults ? "Refreshing…" : "Refresh results"}
          </button>
        </div>
        {resultsError && (
          <p className="gov-alert-error m-4 rounded-sm" role="status">
            {resultsError}
          </p>
        )}
        {finalOutcome?.kind === "winner" && (
          <div
            className="m-4 rounded-sm border border-[#046a38]/30 bg-[#ecfdf3] px-4 py-3 text-[#046a38]"
            role="status"
          >
            <strong>Election winner:</strong> {finalOutcome.winners[0].name}
            {finalOutcome.winners[0].party
              ? ` (${finalOutcome.winners[0].party})`
              : ""}
            <span> with {finalOutcome.winners[0].votes} votes.</span>
          </div>
        )}
        {finalOutcome?.kind === "tie" && (
          <div
            className="m-4 rounded-sm border border-[#f2c078] bg-[#fff8eb] px-4 py-3 text-[#9a5a00]"
            role="status"
          >
            <strong>Election ended in a tie:</strong>{" "}
            {finalOutcome.winners
              .map((candidate) => `${candidate.name} (${candidate.votes} votes)`)
              .join(", ")}
          </div>
        )}
        {finalOutcome?.kind === "no-votes" && (
          <div
            className="m-4 rounded-sm border border-[#f2c078] bg-[#fff8eb] px-4 py-3 text-[#9a5a00]"
            role="status"
          >
            The election ended with no votes recorded. There is no winner.
          </div>
        )}
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Candidate</th>
                <th>Party</th>
                <th>Votes received</th>
              </tr>
            </thead>
            <tbody>
              {results.map((candidate) => (
                <tr key={candidate.id}>
                  <td className="font-semibold text-[#112e51]">
                    {candidate.name}
                  </td>
                  <td>{candidate.party || "Independent"}</td>
                  <td className="font-mono font-bold">{candidate.votes}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!isLoadingResults && !resultsError && results.length === 0 && (
            <p className="py-8 text-center text-slate-500">
              No candidates have been added to this election yet.
            </p>
          )}
        </div>
        <p className="px-4 pb-4 text-xs text-slate-500">
          Refresh this table manually during voting; it updates after the election ends. It shows totals only, not voter identities or individual ballots.
        </p>
      </section>

      <section
        className="admin-overview-grid"
        aria-label="CSBS election overview"
      >
        <div className="admin-stat-card admin-stat-primary">
          <span className="admin-stat-label">Eligible voters</span>
          <strong>{students.length}</strong>
          <span>CSBS students in SQLite</span>
        </div>
        <div className="admin-stat-card">
          <span className="admin-stat-label">USN branch</span>
          <strong>CB</strong>
          <span>Computer Science & Business Systems</span>
        </div>
        <div className="admin-stat-card">
          <span className="admin-stat-label">Batches</span>
          <strong>2023 + 2024</strong>
          <span>1KG23 and 1KG24 intake</span>
        </div>
        <div className="admin-stat-card">
          <span className="admin-stat-label">Registry range</span>
          <strong>001–059 + 400</strong>
          <span>Complete class register</span>
        </div>
      </section>

      <section
        className="admin-roster-card mt-8"
        aria-labelledby="roster-heading"
      >
        <div className="admin-section-heading">
          <div>
            <p className="admin-eyebrow">VOTER ELIGIBILITY</p>
            <h2 id="roster-heading">CSBS student distribution</h2>
          </div>
          <span className="admin-count-badge">
            {filteredStudents.length} shown
          </span>
        </div>
        <div className="admin-distribution">
          <div
            className="admin-donut"
            aria-label={`${students.length} CSBS students, all in the CB branch`}
          >
            <span>
              {students.length}
              <small>CSBS</small>
            </span>
          </div>
          <div className="admin-legend">
            <div>
              <span className="admin-legend-swatch" />
              <div>
                <strong>CB · CSBS</strong>
                <small>
                  {students.length} students · {students.length ? "100" : "0"}%
                  of loaded eligible voters
                </small>
              </div>
            </div>
            <p>
              Loaded live from the protected SQLite voter registry. Other
              branches are intentionally excluded by the API query.
            </p>
          </div>
        </div>
        <div className="admin-roster-toolbar">
          <div>
            <h3>Eligible student USNs</h3>
            <p>Loaded from the protected SQLite voter registry</p>
          </div>
          <label className="admin-search">
            <span aria-hidden="true">⌕</span>
            <input
              value={studentSearch}
              onChange={(event) => setStudentSearch(event.target.value)}
              placeholder="Search USN, e.g. 1KG23CB042"
              aria-label="Search eligible student USNs"
            />
          </label>
        </div>
        <div className="admin-table-wrap">
          {isLoadingStudents && (
            <p className="py-10 text-center text-slate-500">
              Loading CSBS students from SQLite…
            </p>
          )}
          {!isLoadingStudents && (
            <>
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>USN</th>
                    <th>Name</th>
                    <th>Class</th>
                    <th>Branch</th>
                    <th>Batch</th>
                    <th>ID-card check</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredStudents.map((student) => (
                    <tr key={student.usn}>
                      <td>{student.number}</td>
                      <td className="font-mono font-semibold text-[#112e51]">
                        {student.usn}
                      </td>
                      <td>{student.studentName || "Name not provided"}</td>
                      <td>{student.className}</td>
                      <td>
                        <span className="admin-code-chip">
                          {student.branch}
                        </span>
                      </td>
                      <td>{student.batch}</td>
                      <td>
                        {student.faceUpdatePending && (
                          <button
                            type="button"
                            disabled={updatingStudentUsn === student.usn}
                            className="admin-unverified mr-2 disabled:opacity-60"
                            onClick={() => handleApproveFaceUpdate(student)}
                            title="Approve only after checking the voter’s physical ID card"
                          >
                            {updatingStudentUsn === student.usn ? "Saving…" : "Approve face update"}
                          </button>
                        )}
                        <button
                          type="button"
                          disabled={updatingStudentUsn === student.usn}
                          className={
                            `${student.idVerified
                              ? "admin-eligible"
                              : "admin-unverified"} disabled:cursor-wait disabled:opacity-60`
                          }
                          onClick={() => handleEligibilityVerification(student)}
                          title="Toggle physical ID-card verification"
                          aria-busy={updatingStudentUsn === student.usn}
                        >
                          {updatingStudentUsn === student.usn
                            ? "Saving…"
                            : student.idVerified
                              ? "ID verified"
                              : "Verify ID card"}
                        </button>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="admin-unverified"
                          onClick={() => handleDeleteVoter(student)}
                          title={`Delete ${student.usn}`}
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {filteredStudents.length === 0 && (
                <p className="py-10 text-center text-slate-500">
                  No eligible CSBS USN matches that search.
                </p>
              )}
            </>
          )}
        </div>
      </section>

      <section
        className="admin-roster-card mb-8"
        aria-labelledby="turnout-heading"
      >
        <div className="admin-section-heading">
          <div>
            <p className="admin-eyebrow">CURRENT ELECTION SESSION</p>
            <h2 id="turnout-heading">Voter participation</h2>
            <p className="mt-1 text-sm text-[#565c65]">
              {electionName || "Current election"} · {electionLabel}
              {electionState === 1 ? " · refreshes automatically every 10 seconds" : ""}
            </p>
          </div>
          <button
            type="button"
            className="gov-button"
            onClick={() => void loadStudents()}
            disabled={isLoadingStudents}
          >
            {isLoadingStudents ? "Refreshing…" : "Refresh turnout"}
          </button>
        </div>
        {turnoutError ? (
          <p className="gov-alert-error m-4 rounded-sm" role="alert">
            {turnoutError}
          </p>
        ) : electionSessionMismatch ? (
          <p className="gov-alert-error m-4 rounded-sm" role="alert">
            The frontend and backend are connected to different election sessions. Stop make demo with Ctrl+C, then run make demo again before relying on voter participation.
          </p>
        ) : electionState === 0 || electionState === null ? (
          <p className="px-4 py-8 text-center text-slate-500">
            Start the election to view voter participation for this session.
          </p>
        ) : (
          <>
            <p className="px-4 pb-3 text-sm font-semibold text-[#112e51]">
              {students.filter((student) => student.hasVoted).length} of {students.filter((student) => student.idVerified).length} eligible voters have voted.
            </p>
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>USN</th>
                    <th>Name</th>
                    <th>ID-card check</th>
                    <th>Voting status</th>
                  </tr>
                </thead>
                <tbody>
                  {students.map((student) => (
                    <tr key={student.usn}>
                      <td className="font-mono font-semibold text-[#112e51]">
                        {student.usn}
                      </td>
                      <td>{student.studentName || "Name not provided"}</td>
                      <td>{student.idVerified ? "Approved" : "Pending"}</td>
                      <td>
                        <span className={student.hasVoted ? "admin-eligible" : "admin-unverified"}>
                          {student.hasVoted
                            ? "Voted"
                            : student.idVerified
                              ? "Not voted"
                              : "Not eligible yet"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {students.length === 0 && (
                <p className="py-8 text-center text-slate-500">
                  No voters are loaded in the registry.
                </p>
              )}
            </div>
          </>
        )}
      </section>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8 w-full max-w-5xl px-0 mt-8 mx-auto">
        <div className="bg-white shadow-xl shadow-black/5 p-6 sm:p-8 rounded-2xl border border-gray-100">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2 bg-[#005ea2] text-white rounded-full">＋</div>
            <h2 className="text-xl font-bold font-heading text-[#112e51]">
              {t("admin.reg_candidate")}
            </h2>
          </div>
          <form onSubmit={handleAddCandidate} className="space-y-4">
            <p className="text-xs text-slate-500 break-all">
              Connected wallet: {account || "Not connected"}
              <br />
              Contract owner: {contractOwner || "Loading..."}
            </p>
            {!account && (
              <button
                type="button"
                className="btn-primary"
                onClick={() => void connectWallet()}
              >
                Connect MetaMask
              </button>
            )}
            <div>
              <label className="gov-input-label" htmlFor="candidateName">
                {t("admin.cand_name")}
              </label>
              <input
                id="candidateName"
                type="text"
                value={candidateName}
                onChange={(event) => setCandidateName(event.target.value)}
                placeholder="e.g. John Doe"
                className="gov-input"
              />
            </div>
            <div>
              <label className="gov-input-label" htmlFor="candidateParty">
                {t("admin.cand_party")}
              </label>
              <input
                id="candidateParty"
                type="text"
                value={candidateParty}
                onChange={(event) => setCandidateParty(event.target.value)}
                placeholder="e.g. Independent"
                className="gov-input"
              />
            </div>
            <button
              type="submit"
              className="gov-button mt-2"
              disabled={pendingAction !== null}
            >
              {pendingAction === "candidate" ? "Adding candidate…" : t("admin.add_btn")}
            </button>
          </form>
        </div>
        <div className="bg-white shadow-xl shadow-black/5 p-6 sm:p-8 rounded-2xl border border-gray-100">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2 bg-[#005ea2] text-white rounded-full">◷</div>
            <h2 className="text-xl font-bold font-heading text-[#112e51]">
              {t("admin.schedule") || "Election Controls"}
            </h2>
          </div>
          <p className="font-bold mb-4">
            Current state:{" "}
            <span className="text-[#046a38]">{electionLabel}</span>
          </p>
          <div className="mb-5 max-w-xl">
            <label className="gov-input-label" htmlFor="electionName">
              Election name
            </label>
            <div className="flex flex-wrap gap-3">
              <input
                id="electionName"
                type="text"
                maxLength={120}
                value={electionName}
                onChange={(event) => setElectionName(event.target.value)}
                placeholder="e.g. CSBS Student Council Election 2026"
                className="gov-input min-w-64 flex-1"
                disabled={electionState !== 0 || isSavingElectionName}
              />
              <button
                type="button"
                className="gov-button"
                onClick={handleSaveElectionName}
                disabled={electionState !== 0 || isSavingElectionName}
              >
                {isSavingElectionName ? "Saving…" : "Save election name"}
              </button>
            </div>
            <p className="mt-1 text-sm text-[#565c65]">
              Set the name before starting. Voters will see it on the voting page.
            </p>
          </div>
          <div className="flex flex-wrap gap-4">
            <button
              type="button"
              className="btn-primary"
              onClick={handleStartElection}
              disabled={
                electionState !== 0 ||
                pendingAction !== null ||
                !electionName.trim() ||
                electionName.trim() !== savedElectionName
              }
            >
              {pendingAction === "start" ? "Starting election…" : "Start Election"}
            </button>
            <button
              type="button"
              className="btn-primary bg-danger hover:bg-danger-dark border-transparent text-white"
              onClick={handleEndElection}
              disabled={electionState !== 1 || pendingAction !== null}
            >
              {pendingAction === "end" ? "Ending election…" : "End Election"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Admin;
