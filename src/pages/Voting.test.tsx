import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import Voting from "./Voting";
import { BrowserRouter } from "react-router-dom";
import * as api from "../services/api";

const mockWeb3State = vi.hoisted(() => ({
  account: "0x123",
  contract: {
    getElectionState: vi.fn().mockResolvedValue({ toNumber: () => 1 }), // Active
    getCountCandidates: vi.fn().mockResolvedValue({ toNumber: () => 1 }),
    countCandidates: vi.fn().mockResolvedValue({ toNumber: () => 1 }),
    getCandidate: vi.fn(),
  },
  isLoading: false,
  web3: null,
  connectWallet: vi.fn().mockResolvedValue("0x123"),
  electionId: "0xelection1",
  electionName: "Election One",
}));

vi.mock("../context/Web3Context", () => ({
  useWeb3: () => mockWeb3State,
}));

vi.mock("../context/AuthContext", () => ({
  API_BASE: "http://localhost:8000/api/v1",
  useAuth: () => ({
    session: {
      voter_id: "VTR-84291",
      role: "user",
      name: "RAVI KUMAR",
      usn: "1KG23CB052",
      branch: "Computer Science & Business Systems",
      validity: "2027",
      dob: "06-04-2005",
    },
    logout: vi.fn().mockResolvedValue(undefined),
  }),
}));

vi.mock("../context/LanguageContext", () => ({
  useLanguage: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock("../services/api", () => ({
  getVoteStatus: vi.fn(),
  castVote: vi.fn().mockResolvedValue({
    status: "CONFIRMED",
    success: true,
    transaction_hash: "0xabcdef1234567890",
  }),
}));

describe("Voting Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.castVote).mockResolvedValue({ success:true, status:"CONFIRMED", transaction_hash:"0xabcdef1234567890" });
    vi.mocked(api.getVoteStatus).mockResolvedValue({ success:false,status:"SUBMITTED",transaction_hash:"0xpending" });
    mockWeb3State.isLoading = false;
    mockWeb3State.electionId = "0xelection1";
    mockWeb3State.electionName = "Election One";
    mockWeb3State.contract = {
      getElectionState: vi.fn().mockResolvedValue({ toNumber: () => 1 }),
      getCountCandidates: vi.fn().mockResolvedValue({ toNumber: () => 1 }),
      countCandidates: vi.fn().mockResolvedValue({ toNumber: () => 1 }),
      getCandidate: vi.fn().mockResolvedValue([
        { toNumber: () => 1 },
        "Alice",
        "Party A",
        { toNumber: () => 0 },
      ]),
    };

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        voter_id: "VTR-84291",
        student_name: "RAVI KUMAR",
        branch: "Computer Science & Business Systems",
        class_name: "CSBS",
        batch: "2023",
        eligible: true,
        voted: false,
        credential_ready: true,
        tx_hash: null,
      }),
    } as Response);
  });

  const renderComponent = () => {
    return render(
      <BrowserRouter>
        <Voting />
      </BrowserRouter>,
    );
  };

  it("renders loading state initially", () => {
    mockWeb3State.isLoading = true;
    mockWeb3State.contract = null as any;
    renderComponent();
    expect(screen.getByText("Connecting to Blockchain...")).toBeInTheDocument();
  });

  it("loads candidates from contract", async () => {
    renderComponent();

    await waitFor(() => {
      expect(screen.getByText("Alice")).toBeInTheDocument();
    });
    expect(screen.getByText("Party A")).toBeInTheDocument();
  });

  it("switches the voter dashboard to the newly active election", async () => {
    const view = renderComponent();
    await waitFor(() => {
      expect(screen.getByText("Alice")).toBeInTheDocument();
      expect(screen.getByText("Election One")).toBeInTheDocument();
    });

    mockWeb3State.electionId = "0xelection2";
    mockWeb3State.electionName = "Election Two";
    mockWeb3State.contract = {
      getElectionState: vi.fn().mockResolvedValue({ toNumber: () => 1 }),
      getCountCandidates: vi.fn().mockResolvedValue({ toNumber: () => 1 }),
      countCandidates: vi.fn().mockResolvedValue({ toNumber: () => 1 }),
      getCandidate: vi.fn().mockResolvedValue([
        { toNumber: () => 1 },
        "Bob",
        "New party",
        { toNumber: () => 0 },
      ]),
    };
    view.rerender(
      <BrowserRouter>
        <Voting />
      </BrowserRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("Election Two")).toBeInTheDocument();
      expect(screen.getByText("Bob")).toBeInTheDocument();
      expect(screen.queryByText("Alice")).not.toBeInTheDocument();
    });
  });

  it("shows success message if user has already voted", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        voter_id: "VTR-84291",
        student_name: "RAVI KUMAR",
        branch: "Computer Science & Business Systems",
        class_name: "CSBS",
        batch: "2023",
        eligible: true,
        voted: true,
        credential_ready: false,
        tx_hash: "0xdeadbeef12345678",
      }),
    } as Response);

    renderComponent();

    await waitFor(() => {
      expect(
        screen.getByText("Your vote has been sealed on chain"),
      ).toBeInTheDocument();
    });
  });

  it("shows voter registration details on the election page", async () => {
    renderComponent();

    await waitFor(() => {
      expect(screen.getByText("RAVI KUMAR")).toBeInTheDocument();
    });
    expect(screen.getByText("1KG23CB052")).toBeInTheDocument();
    expect(
      screen.getByText("Computer Science & Business Systems"),
    ).toBeInTheDocument();
    expect(screen.getByText("06-04-2005")).toBeInTheDocument();
  });

  it("allows voting workflow via backend relayer API", async () => {
    renderComponent();

    // Wait for candidate to load
    await waitFor(() => {
      expect(screen.getByText("Alice")).toBeInTheDocument();
    });

    // Select candidate
    fireEvent.click(screen.getByRole("button", { name: /Alice Party A/i }));

    // Review
    const reviewButton = screen.getByRole("button", {
      name: /Review & confirm/i,
    });
    expect(reviewButton).not.toBeDisabled();
    fireEvent.click(reviewButton);

    // Confirm
    const confirmButton = await screen.findByRole("button", {
      name: /Confirm and seal/i,
    });
    fireEvent.click(confirmButton);

    await waitFor(() => {
      expect(api.castVote).toHaveBeenCalledWith(1);
    });
  });
  const confirm = async () => {
    await screen.findByText("Alice");
    fireEvent.click(screen.getByRole("button", { name: /Alice Party A/i }));
    fireEvent.click(screen.getByRole("button", { name: /Review & confirm/i }));
    return screen.findByRole("button", { name: /Confirm and seal/i });
  };

  it("sends one request for rapid duplicate clicks", async () => {
    vi.mocked(api.castVote).mockImplementation(() => new Promise(() => {}));
    renderComponent();
    const button = await confirm();
    fireEvent.click(button);
    fireEvent.click(button);
    expect(api.castVote).toHaveBeenCalledTimes(1);
  });

  it("keeps submitted transactions pending until confirmed", async () => {
    vi.mocked(api.castVote).mockResolvedValue({ success:false,status:"SUBMITTED",transaction_hash:"0xpending" });
    vi.mocked(api.getVoteStatus).mockResolvedValue({ success:true,status:"CONFIRMED",transaction_hash:"0xconfirmed" });
    renderComponent();
    fireEvent.click(await confirm());
    await screen.findByText(/Sealing your ballot on chain/);
    expect(screen.queryByText("Your vote has been sealed on chain")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Your vote has been sealed on chain")).toBeInTheDocument(), { timeout:5000 });
  });

  it("shows a rejected transaction without claiming success", async () => {
    vi.mocked(api.castVote).mockRejectedValue(new Error("Election is not active"));
    vi.mocked(api.getVoteStatus).mockResolvedValue({ success:false,status:"FAILED",transaction_hash:null });
    renderComponent();
    fireEvent.click(await confirm());
    await screen.findByText("Election is not active");
    expect(screen.queryByText("Your vote has been sealed on chain")).not.toBeInTheDocument();
  });

  it("keeps an uncertain network failure pending", async () => {
    vi.mocked(api.castVote).mockRejectedValue(new Error("Network unavailable"));
    vi.mocked(api.getVoteStatus).mockRejectedValue(new Error("RPC unavailable"));
    renderComponent();
    fireEvent.click(await confirm());
    await screen.findByText(/Sealing your ballot on chain/);
    expect(screen.queryByText("Your vote has been sealed on chain")).not.toBeInTheDocument();
  });

  it("does not attribute a resumed ballot to this tab's selection", async () => {
    vi.mocked(api.castVote).mockResolvedValue({ success:true,status:"CONFIRMED",transaction_hash:"0xconfirmed",replayed:true });
    renderComponent();
    fireEvent.click(await confirm());
    await screen.findByText("Your vote has been sealed on chain");
    expect(screen.queryByText("Selection")).not.toBeInTheDocument();
  });

});
