export type LiveAction = "blink_once";

export function isLiveAction(value: unknown): value is LiveAction {
  return value === "blink_once";
}

function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => {
      window.clearTimeout(timer);
      signal.removeEventListener("abort", abort);
      reject(new DOMException("Capture cancelled.", "AbortError"));
    };
    const timer = window.setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, ms);
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) abort();
  });
}

/** Server-selected quick capture, with a longer guided option. */
export async function captureLiveness(
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement,
  action: LiveAction,
  signal: AbortSignal,
  onPrompt: (message: string) => void,
  mode: "quick" | "guided" = "guided",
): Promise<string[]> {
  if (!isLiveAction(action)) throw new Error("Refresh the page to load the updated live check.");
  const context = canvas.getContext("2d");
  if (!context || !video.videoWidth || !video.videoHeight) throw new Error("Camera is not ready. Restart the camera.");
  const scale = Math.min(1, 640 / Math.max(video.videoWidth, video.videoHeight));
  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);
  const frames: string[] = [];
  let previousVideoTime = -1;
  const count = mode === "quick" ? 10 : 16;
  const interval = mode === "quick" ? 120 : 150;
  const started = performance.now();
  onPrompt("Keep still, eyes open");
  for (let index = 0; index < count; index += 1) {
    if (signal.aborted) throw new DOMException("Capture cancelled.", "AbortError");
    if (video.readyState < 2 || video.currentTime === previousVideoTime) {
      throw new Error("Camera stopped updating. Restart the camera and try again.");
    }
    if (index === 2) onPrompt("Close eyes");
    if (index === (mode === "quick" ? 5 : 7)) onPrompt("Open eyes");
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    previousVideoTime = video.currentTime;
    frames.push(canvas.toDataURL("image/jpeg", .72));
    // Encoding time is included in the interval instead of added to it.
    await wait(Math.max(0, started + (index + 1) * interval - performance.now()), signal);
  }
  return frames;
}
