import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { captureLiveness, type LiveAction } from "./livenessCapture";

describe("short live capture", () => {
  beforeEach(() => vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "performance"] }));
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

  function camera(frozen = false) {
    const video = document.createElement("video");
    Object.defineProperties(video, {
      videoWidth: { value: 1280 }, videoHeight: { value: 720 }, readyState: { value: 2 },
      currentTime: { get: () => frozen ? 0 : performance.now() / 1000 },
    });
    const canvas = document.createElement("canvas");
    const draw = vi.fn();
    vi.spyOn(canvas, "getContext").mockReturnValue({ drawImage: draw } as unknown as CanvasRenderingContext2D);
    vi.spyOn(canvas, "toDataURL").mockImplementation(() => `frame-${draw.mock.calls.length}`);
    return { video, canvas, draw };
  }

  it.each<LiveAction>(["blink_once"])("captures both ordered prompts for %s in 2.4 seconds", async action => {
    const { video, canvas } = camera();
    const prompts: string[] = [];
    const result = captureLiveness(video, canvas, action, new AbortController().signal, value => prompts.push(value));
    await vi.advanceTimersByTimeAsync(2400);
    const frames = await result;
    expect(frames).toHaveLength(16);
    expect(new Set(frames).size).toBe(16);
    expect(canvas.width).toBe(640);
    expect(canvas.height).toBe(360);
    const blink = prompts.indexOf("Close eyes");
    expect(prompts.some(value => value.startsWith("Turn"))).toBe(false);
    expect(prompts.indexOf("Open eyes")).toBeGreaterThan(blink);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("stops capture immediately on navigation and clears its timer", async () => {
    const { video, canvas, draw } = camera();
    const controller = new AbortController();
    const result = captureLiveness(video, canvas, "blink_once", controller.signal, () => {});
    const rejection = expect(result).rejects.toThrow("Capture cancelled");
    controller.abort();
    await rejection;
    expect(draw).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each<LiveAction>(["blink_once"])("captures 10 observations in quick mode for %s", async action => {
    const { video, canvas } = camera();
    const prompts: string[] = [];
    const result = captureLiveness(video, canvas, action, new AbortController().signal, text => prompts.push(text), "quick");
    await vi.advanceTimersByTimeAsync(1200);
    expect(await result).toHaveLength(10);
    expect(prompts).toEqual(["Keep still, eyes open", "Close eyes", "Open eyes"]);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("rejects a frozen camera before uploading repeated frames", async () => {
    const { video, canvas } = camera(true);
    const result = captureLiveness(video, canvas, "blink_once", new AbortController().signal, () => {});
    const rejection = expect(result).rejects.toThrow("Camera stopped updating");
    await vi.advanceTimersByTimeAsync(150);
    await rejection;
  });
});
