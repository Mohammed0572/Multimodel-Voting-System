import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import VoterLogin from "./VoterLogin";

const mocks = vi.hoisted(() => ({ setAuth: vi.fn(), capture: vi.fn(), stop: vi.fn() }));
vi.mock("../context/LanguageContext", () => ({ useLanguage: () => ({ t: (key: string) => key }) }));
vi.mock("../context/AuthContext", () => ({ API_BASE: "/api/v1", useAuth: () => ({ setAuth: mocks.setAuth }) }));
vi.mock("../lib/livenessCapture", async importOriginal => ({
  ...await importOriginal<typeof import("../lib/livenessCapture")>(), captureLiveness: mocks.capture,
}));
vi.mock("../lib/useCamera", async () => {
  const { useRef } = await import("react");
  return { useCamera: () => ({
    videoRef: useRef(null), mountedRef: useRef(true), abortRef: useRef(new AbortController()),
    startCamera: async () => true, stopCamera: mocks.stop,
  }) };
});

describe("voter login waiting and preflight", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    mocks.capture.mockResolvedValue(Array.from({ length: 16 }, (_, i) => `frame-${i}`));
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      drawImage: vi.fn(), getImageData: () => ({ data: new Uint8ClampedArray(32 * 24 * 4).fill(120) }),
    } as unknown as CanvasRenderingContext2D);
    vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  async function ready() {
    render(<MemoryRouter><VoterLogin /></MemoryRouter>);
    Object.defineProperties(screen.getByLabelText("Live camera preview"), {
      readyState: { value: 2 }, videoWidth: { value: 640 }, videoHeight: { value: 480 },
    });
    fireEvent.change(screen.getByLabelText("voter.id_label"), { target: { value: "VOTER1" } });
    await act(async () => { fireEvent.click(screen.getByText("voter.enable_cam")); });
  }

  it("shows preflight rejection without making the voter capture frames", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, json: async () => ({ detail: "Administrator approval is required before login." }) }));
    await ready();
    await act(async () => { fireEvent.click(screen.getByText("voter.verify_btn")); });
    expect(screen.getByRole("alert")).toHaveTextContent("Administrator approval");
    expect(mocks.capture).not.toHaveBeenCalled();
    expect(mocks.setAuth).not.toHaveBeenCalled();
    expect(screen.getByText("voter.verify_btn")).toBeEnabled();
  });

  it("explains an old running backend before wasting a capture", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ challenge_id: "old", challenge: "blink_once" }) }));
    await ready();
    await act(async () => { fireEvent.click(screen.getByText("voter.verify_btn")); });
    expect(screen.getByRole("alert")).toHaveTextContent("Restart the demo");
    expect(mocks.capture).not.toHaveBeenCalled();
    expect(mocks.setAuth).not.toHaveBeenCalled();
  });

  it("aborts an unresponsive verification and unlocks retry without logging in", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ challenge_id: "test", challenge: "blink_once", face_engine_version: 3 }) });
    fetchMock.mockImplementationOnce((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal!.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
    }));
    vi.stubGlobal("fetch", fetchMock);
    await ready();
    await act(async () => { fireEvent.click(screen.getByText("voter.verify_btn")); });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(screen.getByRole("alert")).toHaveTextContent("Verification took too long");
    expect(mocks.setAuth).not.toHaveBeenCalled();
    expect(screen.getByText("voter.verify_btn")).toBeEnabled();
  });
});
