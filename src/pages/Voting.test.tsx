import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import Web3 from "web3";
import Voting from "./Voting";
import { BrowserRouter } from "react-router-dom";

const mockWeb3State = vi.hoisted(() => ({
  account: "0x123",
  contract: {
    getElectionState: vi.fn().mockResolvedValue({ toNumber: () => 1 }), // Active
    getCountCandidates: vi.fn(),
    getCandidate: vi.fn(),
    checkVote: vi.fn(),
    vote: vi.fn(),
  },
  isLoading: false,
  web3: null,
  connectWallet: vi.fn().mockResolvedValue("0x123"),
}));

vi.mock("../context/Web3Context", () => ({
  useWeb3: () => mockWeb3State,
}));

vi.mock("../context/AuthContext", () => ({
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

// Mock Language Context
vi.mock("../context/LanguageContext", () => ({
  useLanguage: () => ({
    t: (key: string) => key,
  }),
}));

describe("Voting Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset to Active state before each test
    mockWeb3State.isLoading = false;
    mockWeb3State.contract = {
      getElectionState: vi.fn().mockResolvedValue({ toNumber: () => 1 }),
      getCountCandidates: vi.fn(),
      getCandidate: vi.fn(),
      checkVote: vi.fn(),
      vote: vi.fn(),
    };
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
    mockWeb3State.contract = {
      getElectionState: vi.fn().mockResolvedValue({ toNumber: () => 1 }),
      getCountCandidates: vi.fn().mockResolvedValue({ toNumber: () => 1 }),
      getCandidate: vi
        .fn()
        .mockResolvedValue([
          { toNumber: () => 1 },
          "Alice",
          "Party A",
          { toNumber: () => 0 },
        ]),
      checkVote: vi.fn().mockResolvedValue(false),
      vote: vi.fn(),
    };

    renderComponent();

    await waitFor(() => {
      expect(screen.getByText("Alice")).toBeInTheDocument();
    });
    expect(screen.getByText("Party A")).toBeInTheDocument();
  });

  it("shows success message if user has already voted", async () => {
    mockWeb3State.contract = {
      getElectionState: vi.fn().mockResolvedValue({ toNumber: () => 1 }),
      getCountCandidates: vi.fn().mockResolvedValue({ toNumber: () => 0 }),
      getCandidate: vi.fn(),
      checkVote: vi.fn().mockResolvedValue(true),
      vote: vi.fn(),
    };

    renderComponent();

    await waitFor(() => {
      expect(
        screen.getByText("Your vote has been sealed on chain"),
      ).toBeInTheDocument();
    });
  });

  it("shows voter registration details on the election page", async () => {
    mockWeb3State.contract = {
      getElectionState: vi.fn().mockResolvedValue({ toNumber: () => 1 }),
      getCountCandidates: vi.fn().mockResolvedValue({ toNumber: () => 0 }),
      getCandidate: vi.fn(),
      checkVote: vi.fn().mockResolvedValue(false),
      vote: vi.fn(),
    };

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

  it("allows voting workflow", async () => {
    const mockVote = vi.fn().mockResolvedValue(true);
    mockWeb3State.contract = {
      getElectionState: vi.fn().mockResolvedValue({ toNumber: () => 1 }),
      getCountCandidates: vi.fn().mockResolvedValue({ toNumber: () => 1 }),
      getCandidate: vi
        .fn()
        .mockResolvedValue([
          { toNumber: () => 1 },
          "Alice",
          "Party A",
          { toNumber: () => 0 },
        ]),
      checkVote: vi.fn().mockResolvedValue(false),
      vote: mockVote,
    };

    renderComponent();

    // Wait for candidate to load
    await waitFor(() => {
      expect(screen.getByText("Alice")).toBeInTheDocument();
    });

    // Select candidate
    fireEvent.click(screen.getByRole("button", { name: /Alice Party A/i }));

    // Review, then confirm the irreversible transaction
    const reviewButton = screen.getByRole("button", {
      name: /Review & confirm/i,
    });
    expect(reviewButton).not.toBeDisabled();
    fireEvent.click(reviewButton);

    const confirmButton = await screen.findByRole("button", {
      name: /Confirm and seal/i,
    });
    fireEvent.click(confirmButton);

    await waitFor(() => {
      expect(mockVote).toHaveBeenCalledWith(
        1,
        Web3.utils.sha3(
          new TextEncoder().encode("VTR-84291") as unknown as string,
        ),
        { from: "0x123" },
      );
    });
  });
});
