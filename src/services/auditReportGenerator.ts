import jsPDF from "jspdf";
import autoTable from "jspdf-autotable";

export interface AuditCandidate {
  id: number;
  name: string;
  party: string;
  votes: number;
  percentage?: number;
}

export interface AuditTransactionLog {
  index: number;
  tx_hash: string;
  block_number: number;
  block_hash: string;
  candidate_id: number;
  credential_hash: string;
  timestamp: string;
}

export interface AuditReportData {
  election_id: string;
  election_name: string;
  state: string;
  state_code: number;
  contract_address: string;
  chain_id: number;
  relayer_address: string;
  signer_address: string;
  audit_digest: string;
  signature: string;
  signature_algorithm: string;
  generated_at: string;
  turnout_stats: {
    total_registered: number;
    total_verified: number;
    total_votes_cast: number;
    turnout_percentage: number;
  };
  candidate_results: AuditCandidate[];
  winner: AuditCandidate | null;
  transaction_logs: AuditTransactionLog[];
}

export function generateAuditPdf(data: AuditReportData) {
  const doc = new jsPDF({
    orientation: "portrait",
    unit: "mm",
    format: "a4",
  });

  const primaryColor: [number, number, number] = [11, 31, 58]; // #0b1f3a
  const saffronColor: [number, number, number] = [255, 103, 31]; // #ff671f
  const greenColor: [number, number, number] = [4, 106, 56]; // #046a38
  const ashokaBlue: [number, number, number] = [30, 64, 175]; // #1e40af
  const lightBg: [number, number, number] = [250, 247, 242]; // #faf7f2

  // Tricolor Header Bar
  doc.setFillColor(...saffronColor);
  doc.rect(0, 0, 70, 3, "F");
  doc.setFillColor(255, 255, 255);
  doc.rect(70, 0, 70, 3, "F");
  doc.setFillColor(...greenColor);
  doc.rect(140, 0, 70, 3, "F");

  // Title Header
  doc.setFont("helvetica", "bold");
  doc.setFontSize(16);
  doc.setTextColor(...primaryColor);
  doc.text("ELECTION COMMISSION OF INDIA", 105, 14, { align: "center" });

  doc.setFont("helvetica", "normal");
  doc.setFontSize(10);
  doc.setTextColor(100, 116, 139);
  doc.text("OFFICIAL CRYPTOGRAPHIC AUDIT REPORT & VOTE RECORD", 105, 20, {
    align: "center",
  });

  // Divider Line
  doc.setDrawColor(229, 231, 235);
  doc.setLineWidth(0.5);
  doc.line(14, 24, 196, 24);

  // Election Meta Card
  doc.setFillColor(...lightBg);
  doc.roundedRect(14, 27, 182, 32, 2, 2, "F");

  doc.setFont("helvetica", "bold");
  doc.setFontSize(12);
  doc.setTextColor(...primaryColor);
  doc.text(data.election_name || "General Election", 18, 34);

  doc.setFont("helvetica", "normal");
  doc.setFontSize(8.5);
  doc.setTextColor(71, 85, 105);

  const statusLabel =
    data.state === "Ended"
      ? "CERTIFIED CONCLUDED (FINAL)"
      : data.state === "Active"
        ? "IN PROGRESS (ACTIVE BALLOTING)"
        : "SCHEDULED / NOT STARTED";

  doc.text(`Election Status:`, 18, 41);
  doc.setFont("helvetica", "bold");
  doc.setTextColor(
    data.state === "Ended" ? 4 : 255,
    data.state === "Ended" ? 106 : 103,
    data.state === "Ended" ? 56 : 31,
  );
  doc.text(statusLabel, 50, 41);

  doc.setFont("helvetica", "normal");
  doc.setTextColor(71, 85, 105);
  doc.text(`Contract Address: ${data.contract_address || "N/A"}`, 18, 47);
  doc.text(
    `Network Chain ID: ${data.chain_id}  |  Relayer: ${data.relayer_address ? data.relayer_address.slice(0, 14) + "…" + data.relayer_address.slice(-6) : "N/A"}`,
    18,
    53,
  );
  doc.text(
    `Report Generated: ${new Date(data.generated_at).toUTCString()}`,
    110,
    53,
  );

  // Turnout Summary Section
  doc.setFont("helvetica", "bold");
  doc.setFontSize(11);
  doc.setTextColor(...primaryColor);
  doc.text("1. Participation & Turnout Metrics", 14, 66);

  const turnout = data.turnout_stats;
  autoTable(doc, {
    startY: 70,
    theme: "grid",
    head: [
      [
        "Enrolled Voters",
        "Verified Eligible",
        "Total Ballots Cast",
        "Turnout Percentage",
      ],
    ],
    body: [
      [
        turnout.total_registered.toString(),
        turnout.total_verified.toString(),
        turnout.total_votes_cast.toString(),
        `${turnout.turnout_percentage}%`,
      ],
    ],
    headStyles: {
      fillColor: primaryColor,
      textColor: [255, 255, 255],
      fontStyle: "bold",
      fontSize: 9,
    },
    bodyStyles: {
      fontSize: 9,
      textColor: [15, 23, 42],
    },
    styles: { halign: "center" },
  });

  // Candidate Results Section
  const afterTurnoutY = (doc as any).lastAutoTable.finalY + 10;
  doc.setFont("helvetica", "bold");
  doc.setFontSize(11);
  doc.setTextColor(...primaryColor);
  doc.text("2. Official Candidate Tallies", 14, afterTurnoutY);

  if (data.winner && data.state === "Ended") {
    doc.setFillColor(254, 243, 199); // amber 100
    doc.roundedRect(14, afterTurnoutY + 4, 182, 10, 1.5, 1.5, "F");
    doc.setFont("helvetica", "bold");
    doc.setFontSize(9);
    doc.setTextColor(180, 83, 9); // amber 700
    doc.text(
      `🏆 CERTIFIED WINNER: ${data.winner.name} (${data.winner.party}) with ${data.winner.votes} votes`,
      18,
      afterTurnoutY + 10.5,
    );
  }

  const candidateTableStartY =
    data.winner && data.state === "Ended"
      ? afterTurnoutY + 17
      : afterTurnoutY + 5;

  const candidateRows = (data.candidate_results || []).map((cand) => [
    cand.id.toString(),
    cand.name,
    cand.party,
    cand.votes.toString(),
    cand.percentage !== undefined ? `${cand.percentage}%` : "N/A",
  ]);

  autoTable(doc, {
    startY: candidateTableStartY,
    theme: "striped",
    head: [["ID", "Candidate Name", "Party Affiliation", "Votes", "Vote Share"]],
    body: candidateRows.length
      ? candidateRows
      : [["-", "No candidates registered", "-", "0", "0%"]],
    headStyles: {
      fillColor: ashokaBlue,
      textColor: [255, 255, 255],
      fontStyle: "bold",
      fontSize: 9,
    },
    bodyStyles: { fontSize: 8.5 },
    columnStyles: {
      0: { halign: "center", cellWidth: 15 },
      1: { fontStyle: "bold" },
      3: { halign: "center" },
      4: { halign: "center", fontStyle: "bold" },
    },
  });

  // Cryptographic Signature Box (Page 1 footer or before logs)
  const afterCandY = (doc as any).lastAutoTable.finalY + 8;
  doc.setFillColor(...lightBg);
  doc.roundedRect(14, afterCandY, 182, 34, 2, 2, "F");

  doc.setFont("helvetica", "bold");
  doc.setFontSize(9.5);
  doc.setTextColor(...primaryColor);
  doc.text("3. Cryptographic Proof of Integrity", 18, afterCandY + 6);

  doc.setFont("helvetica", "normal");
  doc.setFontSize(7.5);
  doc.setTextColor(51, 65, 85);

  doc.text(`Signing Authority: ${data.signer_address || "N/A"}`, 18, afterCandY + 12);
  doc.text(`Signature Scheme: ${data.signature_algorithm}`, 18, afterCandY + 17);

  doc.setFont("courier", "bold");
  doc.setFontSize(7);
  doc.text(
    `SHA-256 Audit Digest: ${data.audit_digest.slice(0, 48)}...`,
    18,
    afterCandY + 22,
  );
  doc.text(
    `Digital Signature:    ${data.signature.slice(0, 52)}...`,
    18,
    afterCandY + 27,
  );

  doc.setFont("helvetica", "italic");
  doc.setFontSize(7);
  doc.setTextColor(100, 116, 139);
  doc.text(
    "Tamper-evident record certified by the Election Authority relayer & smart contract ledger.",
    18,
    afterCandY + 32,
  );

  // Page 2: Detailed Transaction Log
  doc.addPage();

  // Header on Page 2
  doc.setFont("helvetica", "bold");
  doc.setFontSize(12);
  doc.setTextColor(...primaryColor);
  doc.text("4. Immutable On-Chain Transaction Logs", 14, 15);

  doc.setFont("helvetica", "normal");
  doc.setFontSize(8);
  doc.setTextColor(100, 116, 139);
  doc.text(
    `Record of all ${data.transaction_logs.length} vote event(s) recorded in block receipts`,
    14,
    20,
  );

  const txRows = (data.transaction_logs || []).map((tx) => [
    tx.index.toString(),
    tx.block_number.toString(),
    tx.tx_hash.length > 20
      ? `${tx.tx_hash.slice(0, 10)}…${tx.tx_hash.slice(-8)}`
      : tx.tx_hash,
    tx.block_hash.length > 20
      ? `${tx.block_hash.slice(0, 10)}…${tx.block_hash.slice(-8)}`
      : tx.block_hash,
    tx.credential_hash.length > 20
      ? `${tx.credential_hash.slice(0, 10)}…${tx.credential_hash.slice(-8)}`
      : tx.credential_hash,
    new Date(tx.timestamp).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }),
  ]);

  autoTable(doc, {
    startY: 24,
    theme: "grid",
    head: [
      [
        "#",
        "Block",
        "Transaction Hash",
        "Block Hash",
        "Credential Digest",
        "Time",
      ],
    ],
    body: txRows.length
      ? txRows
      : [["-", "-", "No vote transactions recorded", "-", "-", "-"]],
    headStyles: {
      fillColor: primaryColor,
      textColor: [255, 255, 255],
      fontStyle: "bold",
      fontSize: 8,
    },
    bodyStyles: {
      fontSize: 7.5,
      font: "courier",
    },
    columnStyles: {
      0: { halign: "center", cellWidth: 10 },
      1: { halign: "center", cellWidth: 16 },
      5: { halign: "center", font: "helvetica" },
    },
  });

  const fileName = `Election-Audit-${(data.election_name || "report").replace(/\s+/g, "_")}-${new Date().toISOString().slice(0, 10)}.pdf`;
  doc.save(fileName);
}

export function downloadAuditJson(data: AuditReportData) {
  const jsonString = JSON.stringify(data, null, 2);
  const blob = new Blob([jsonString], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `Election-Audit-${(data.election_name || "audit").replace(/\s+/g, "_")}-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
