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
  verifiedBy: string | null;
  verifiedAt: string | null;
};

const Admin = () => {
  const { t } = useLanguage();
  const { account, contract, isLoading, error, connectWallet } = useWeb3();
  const [candidateName, setCandidateName] = useState("");
  const [candidateParty, setCandidateParty] = useState("");
  const [contractOwner, setContractOwner] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>({ message: "", type: "" });
  const [electionState, setElectionState] = useState<number | null>(null);
  const [studentSearch, setStudentSearch] = useState("");
  const [students, setStudents] = useState<Student[]>([]);
  const [isLoadingStudents, setIsLoadingStudents] = useState(true);

  const loadState = useCallback(async () => {
    try {
      const stateResult = await contract.getElectionState();
      setElectionState(stateResult.toNumber());
    } catch (loadError) {
      console.error(loadError);
    }
  }, [contract]);

  useEffect(() => {
    if (contract) loadState();
  }, [contract, loadState]);

  useEffect(() => {
    if (!contract) return;
    void contract.owner().then((owner: string) => setContractOwner(owner));
  }, [contract]);

  useEffect(() => {
    const loadStudents = async () => {
      try {
        const response = await fetch(`${API_BASE}/admin/voters`, {
          credentials: "include",
        });
        if (!response.ok)
          throw new Error("Unable to load the CSBS voter registry.");
        const data = await response.json();
        setStudents(data.students ?? []);
      } catch (studentError) {
        console.error(studentError);
        updateStatus("Unable to load the CSBS registry from SQLite.", "error");
      } finally {
        setIsLoadingStudents(false);
      }
    };
    void loadStudents();
  }, []);

  const updateStatus = (message: string, type: string) => {
    setStatus({ message, type });
    setTimeout(() => setStatus({ message: "", type: "" }), 5000);
  };

  const handleEligibilityVerification = async (student: Student) => {
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
      if (!response.ok)
        throw new Error("Unable to update ID-card verification.");
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
        "Unable to save the ID-card verification to SQLite.",
        "error",
      );
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

    try {
      const owner = await contract.owner();
      if (owner.toLowerCase() !== account.toLowerCase()) {
        updateStatus(
          `Only the contract owner can add candidates. Switch MetaMask to ${owner}.`,
          "error",
        );
        return;
      }
      updateStatus("Processing transaction on blockchain...", "info");
      await contract.addCandidate(candidateName, candidateParty, {
        from: account,
      });
      updateStatus("Candidate added successfully!", "success");
      setCandidateName("");
      setCandidateParty("");
    } catch (candidateError) {
      console.error(candidateError);
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
    }
  };

  const handleStartElection = async () => {
    if (!contract || !account) {
      updateStatus(
        "Connect the contract owner wallet before starting the election.",
        "error",
      );
      return;
    }

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
      loadState();
    } catch (startError) {
      console.error(startError);
      const errorMessage =
        startError instanceof Error ? startError.message : String(startError);
      updateStatus(`Failed to start election: ${errorMessage}`, "error");
    }
  };

  const handleEndElection = async () => {
    try {
      updateStatus("Processing transaction on blockchain...", "info");
      await contract.endElection({ from: account });
      updateStatus("Election ended successfully!", "success");
      loadState();
    } catch (endError) {
      console.error(endError);
      updateStatus(
        "Failed to end election. Ensure you are the owner and it is currently active.",
        "error",
      );
    }
  };

  const filteredStudents = useMemo(() => {
    const query = studentSearch.trim().toLowerCase();
    if (!query) return students;
    return students.filter((student) =>
      student.usn.toLowerCase().includes(query),
    );
  }, [studentSearch, students]);

  if (isLoading) {
    return (
      <div className="flex justify-center py-20">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-paper py-20 text-ink px-6 text-center">
        <h2 className="text-2xl font-bold text-red-600 mb-4">
          Blockchain Connection Failed
        </h2>
        <p className="text-muted-foreground mb-4 max-w-md">{error}</p>
        <p className="text-sm">
          Please ensure MetaMask is connected, unlock the account, and refresh
          the page.
        </p>
      </div>
    );
  }

  const electionLabel =
    electionState === 1
      ? "Active"
      : electionState === 2
        ? "Ended"
        : "Not Started";

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
                        <button
                          type="button"
                          className={
                            student.idVerified
                              ? "admin-eligible"
                              : "admin-unverified"
                          }
                          onClick={() => handleEligibilityVerification(student)}
                          title="Toggle physical ID-card verification"
                        >
                          {student.idVerified
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
            <button type="submit" className="gov-button mt-2">
              {t("admin.add_btn")}
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
          <div className="flex flex-wrap gap-4">
            <button
              type="button"
              className="btn-primary"
              onClick={handleStartElection}
              disabled={electionState !== 0}
            >
              Start Election
            </button>
            <button
              type="button"
              className="btn-primary bg-danger hover:bg-danger-dark border-transparent text-white"
              onClick={handleEndElection}
              disabled={electionState !== 1}
            >
              End Election
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Admin;
