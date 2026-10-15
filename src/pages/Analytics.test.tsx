import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import Analytics from "./Analytics";
import { BrowserRouter } from "react-router-dom";

const mockAnalyticsData = {
  election_id: "0x1234567890123456789012345678901234567890",
  election_name: "CSBS Student Council Election 2026",
  state: "Active",
  state_code: 1,
  blockchain_connected: true,
  contract_address: "0x1234567890123456789012345678901234567890",
  chain_id: 1337,
  latest_block_number: 42,
  turnout: {
    total_registered: 60,
    total_verified: 55,
    total_votes_cast: 45,
    turnout_percentage: 81.82,
  },
  candidates: [
    {
      id: 1,
      name: "Aarav Sharma",
      party: "National Tech Alliance",
      votes: 28,
      percentage: 62.22,
    },
    {
      id: 2,
      name: "Priya Nair",
      party: "Future Leaders Forum",
      votes: 17,
      percentage: 37.78,
    },
  ],
  leading_candidate: {
    id: 1,
    name: "Aarav Sharma",
    party: "National Tech Alliance",
    votes: 28,
    percentage: 62.22,
  },
  winner: null,
  updated_at: "2026-10-15T12:00:00Z",
};

describe("Analytics Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/election/analytics")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockAnalyticsData),
        });
      }
      return Promise.reject(new Error("Not found"));
    });
  });

  it("renders live election status, turnout KPIs, and candidate bars", async () => {
    render(
      <BrowserRouter>
        <Analytics />
      </BrowserRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("CSBS Student Council Election 2026")).toBeInTheDocument();
      expect(screen.getByText("VOTING LIVE IN PROGRESS")).toBeInTheDocument();
      expect(screen.getByText("81.82%")).toBeInTheDocument();
      expect(screen.getByText("Aarav Sharma")).toBeInTheDocument();
      expect(screen.getByText("Priya Nair")).toBeInTheDocument();
      expect(screen.getByText("28 votes")).toBeInTheDocument();
    });
  });

  it("renders winner highlight when election state is Ended", async () => {
    const endedData = {
      ...mockAnalyticsData,
      state: "Ended",
      state_code: 2,
      winner: mockAnalyticsData.candidates[0],
    };

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(endedData),
    });

    render(
      <BrowserRouter>
        <Analytics />
      </BrowserRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("ELECTION CONCLUDED · FINAL CERTIFIED")).toBeInTheDocument();
      expect(screen.getByText("Official Certified Election Winner")).toBeInTheDocument();
    });
  });
});
