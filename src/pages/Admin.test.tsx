import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Admin from "./Admin";

const mockWeb3State = vi.hoisted(() => ({
  account: null as string | null,
  contract: null as any,
  isLoading: false,
  error: null as string | null,
  electionId: "0xcontract",
  connectWallet: vi.fn(),
  deployElection: vi.fn(),
  refreshElection: vi.fn(),
  currentState: 0,
  candidateCount: 0,
  candidateVotes: 0,
}));

vi.mock("../context/Web3Context", () => ({
  useWeb3: () => mockWeb3State,
}));

vi.mock("../context/LanguageContext", () => ({
  useLanguage: () => ({
    t: (key: string) =>
      ({
        "admin.title": "System Administration",
        "admin.reg_candidate": "Register Candidate",
        "admin.cand_name": "Candidate Full Name",
        "admin.cand_party": "Political Party / Faction",
        "admin.add_btn": "Add to Official Record",
        "admin.schedule": "Election Schedule",
      })[key] || key,
  }),
}));

vi.mock("../context/AuthContext", () => ({
  API_BASE: "http://localhost:8000/api/v1",
}));

const renderAdmin = () =>
  render(
    <BrowserRouter>
      <Admin />
    </BrowserRouter>,
  );

describe("Admin election controls", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mockWeb3State.account = null;
    mockWeb3State.electionId = "0xcontract";
    mockWeb3State.currentState = 0;
    mockWeb3State.candidateCount = 0;
    mockWeb3State.candidateVotes = 0;
    mockWeb3State.connectWallet.mockResolvedValue("0xOwner");
    mockWeb3State.deployElection.mockResolvedValue(
      "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd",
    );
    mockWeb3State.refreshElection.mockResolvedValue(undefined);
    mockWeb3State.contract = {
      owner: vi.fn().mockResolvedValue("0xOwner"),
      relayer: vi.fn().mockResolvedValue("0xRelayer"),
      getElectionState: vi.fn().mockImplementation(async () => ({
        toNumber: () => mockWeb3State.currentState,
      })),
      countCandidates: vi.fn().mockImplementation(async () => ({
        toString: () => String(mockWeb3State.candidateCount),
      })),
      getCountCandidates: vi.fn().mockImplementation(async () => ({
        toString: () => String(mockWeb3State.candidateCount),
      })),
      getCandidate: vi.fn().mockImplementation(async (id: number) => [
        { toString: () => String(id) },
        "Alice",
        "Independent",
        { toString: () => String(mockWeb3State.candidateVotes) },
      ]),
      addCandidate: vi.fn().mockImplementation(async () => {
        mockWeb3State.candidateCount += 1;
      }),
      startElection: vi.fn(),
      endElection: vi.fn().mockImplementation(async () => {
        mockWeb3State.currentState = 2;
        mockWeb3State.candidateVotes = 3;
      }),
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
        const url = String(input);
        const data = url.endsWith("/admin/voters")
          ? { students: [] }
          : url.endsWith("/admin/election/activate")
            ? {
                name: "Next election",
                election_id: "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd",
                contract_address:
                  "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd",
              }
            : {
                name: "Demo election",
                election_id: "0xcontract",
                contract_address: "0xcontract",
              };
        return {
          ok: true,
          json: async () => data,
        } as Response;
      }),
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  it("requests MetaMask access when adding a candidate without a connected account", async () => {
    renderAdmin();

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Add to Official Record" }),
      ).toBeEnabled();
    });
    fireEvent.change(screen.getByLabelText("Candidate Full Name"), {
      target: { value: "Alice" },
    });
    fireEvent.change(screen.getByLabelText("Political Party / Faction"), {
      target: { value: "Independent" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Add to Official Record" }),
    );

    await waitFor(() => {
      expect(mockWeb3State.connectWallet).toHaveBeenCalledOnce();
      expect(mockWeb3State.contract.addCandidate).toHaveBeenCalledWith(
        "Alice",
        "Independent",
        { from: "0xOwner" },
      );
    });
  });

  it("refreshes the ended state and results after ending an election", async () => {
    mockWeb3State.account = "0xOwner";
    mockWeb3State.currentState = 1;
    mockWeb3State.candidateCount = 1;
    renderAdmin();

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "End Election" }),
      ).toBeEnabled();
    });
    fireEvent.click(screen.getByRole("button", { name: "End Election" }));

    await waitFor(() => {
      expect(mockWeb3State.contract.endElection).toHaveBeenCalledWith({
        from: "0xOwner",
      });
      expect(screen.getByText("Election ended successfully!")).toBeInTheDocument();
      expect(screen.getByText("Election winner:")).toBeInTheDocument();
      expect(screen.getByText("3")).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Create new election" }),
      ).toBeInTheDocument();
    });
  });

  it("creates and activates a new election without retaining prior results", async () => {
    mockWeb3State.account = "0xOwner";
    mockWeb3State.currentState = 2;
    mockWeb3State.candidateCount = 1;
    renderAdmin();

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Create new election" }),
      ).toBeEnabled();
    });
    fireEvent.change(screen.getByLabelText("New election name"), {
      target: { value: "Next election" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create new election" }));

    await waitFor(() => {
      expect(mockWeb3State.deployElection).toHaveBeenCalledWith(
        "0xRelayer",
        "0xOwner",
      );
      expect(mockWeb3State.refreshElection).toHaveBeenCalledOnce();
      expect(screen.getByText("New election created and active.")).toBeInTheDocument();
      expect(screen.queryByText("Alice")).not.toBeInTheDocument();
    });

    const activationRequest = vi.mocked(fetch).mock.calls.find(([input]) =>
      String(input).endsWith("/admin/election/activate"),
    );
    expect(activationRequest).toBeDefined();
    expect(JSON.parse(String(activationRequest?.[1]?.body))).toEqual({
      contract_address: "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd",
      owner_address: "0xOwner",
      name: "Next election",
    });
  });
});
