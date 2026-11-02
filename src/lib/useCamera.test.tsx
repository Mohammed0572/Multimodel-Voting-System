import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useCamera } from "./useCamera";

describe("camera ownership", () => {
  beforeEach(() => vi.restoreAllMocks());

  const setup = (getUserMedia: ReturnType<typeof vi.fn>) => {
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia } });
    const hook = renderHook(() => useCamera());
    hook.result.current.videoRef.current = document.createElement("video");
    vi.spyOn(hook.result.current.videoRef.current, "play").mockResolvedValue();
    return hook;
  };

  it("stops a stream whose permission promise resolves after unmount", async () => {
    const stop = vi.fn();
    let grant!: (stream: MediaStream) => void;
    const media = vi.fn(() => new Promise<MediaStream>(resolve => { grant = resolve; }));
    const hook = setup(media);
    const start = hook.result.current.startCamera();
    hook.unmount();
    grant({ getTracks: () => [{ stop }] } as unknown as MediaStream);
    expect(await start).toBe(false);
    expect(stop).toHaveBeenCalledOnce();
  });

  it("allows only one pending camera request and cleans up active tracks", async () => {
    const stop = vi.fn();
    const media = vi.fn().mockResolvedValue({ getTracks: () => [{ stop }] });
    const hook = setup(media);
    await act(async () => {
      await Promise.all([hook.result.current.startCamera(), hook.result.current.startCamera()]);
    });
    expect(media).toHaveBeenCalledOnce();
    hook.unmount();
    expect(stop).toHaveBeenCalledOnce();
  });

  it("explains permission denial", async () => {
    const hook = setup(vi.fn().mockRejectedValue(new DOMException("denied", "NotAllowedError")));
    await expect(hook.result.current.startCamera()).rejects.toThrow("permission was denied");
  });

  it("stops tracks when video playback fails", async () => {
    const stop = vi.fn();
    const hook = setup(vi.fn().mockResolvedValue({ getTracks: () => [{ stop }] }));
    vi.mocked(hook.result.current.videoRef.current!.play).mockRejectedValue(new Error("play failed"));
    await expect(hook.result.current.startCamera()).rejects.toThrow("play failed");
    expect(stop).toHaveBeenCalledOnce();
  });
});
