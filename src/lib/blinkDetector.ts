import {
  FaceLandmarker,
  FilesetResolver,
  type FaceLandmarkerResult,
} from "@mediapipe/tasks-vision";

/**
 * Real-time, in-browser blink watcher.
 *
 * This module only decides when to capture frames. The authoritative liveness
 * decision remains server-side using independent dlib landmarks and EAR.
 */
const WASM_BASE_PATH = "/mediapipe/wasm";
const MODEL_ASSET_PATH = "/mediapipe/face_landmarker.task";
const BLINK_CLOSED_THRESHOLD = 0.5;
const BLINK_OPEN_THRESHOLD = 0.25;

let landmarkerPromise: Promise<FaceLandmarker> | null = null;

export function getFaceLandmarker(): Promise<FaceLandmarker> {
  if (!landmarkerPromise) {
    landmarkerPromise = (async () => {
      const fileset = await FilesetResolver.forVisionTasks(WASM_BASE_PATH);
      try {
        return await FaceLandmarker.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: MODEL_ASSET_PATH, delegate: "GPU" },
          runningMode: "VIDEO",
          numFaces: 1,
          outputFaceBlendshapes: true,
          outputFacialTransformationMatrixes: false,
        });
      } catch (gpuError) {
        console.warn(
          "MediaPipe GPU delegate unavailable, falling back to CPU:",
          gpuError,
        );
        return FaceLandmarker.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: MODEL_ASSET_PATH, delegate: "CPU" },
          runningMode: "VIDEO",
          numFaces: 1,
          outputFaceBlendshapes: true,
          outputFacialTransformationMatrixes: false,
        });
      }
    })();
  }
  return landmarkerPromise;
}

export type BlinkWatchResult = {
  frames: string[];
  blinkConfirmed: boolean;
};

export type BlinkWatchOptions = {
  timeoutMs?: number;
  jpegQuality?: number;
  onStatus?: (message: string) => void;
};

export async function watchForBlink(
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement,
  { timeoutMs = 6000, jpegQuality = 0.7, onStatus }: BlinkWatchOptions = {},
): Promise<BlinkWatchResult> {
  const landmarker = await getFaceLandmarker();
  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("Could not prepare canvas for capture.");
  }

  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;

  const captureFrame = (): string => {
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", jpegQuality);
  };

  return new Promise((resolve, reject) => {
    let rafId = 0;
    let openFrame: string | null = null;
    let closedFrame: string | null = null;
    let closedPeakScore = 0;
    let postFrame: string | null = null;
    let state: "watching-open" | "watching-closed" = "watching-open";
    let settled = false;

    const cleanup = () => {
      window.cancelAnimationFrame(rafId);
      window.clearTimeout(timeoutId);
    };

    const finish = (blinkConfirmed: boolean) => {
      if (settled) return;
      settled = true;
      cleanup();
      const frames = [openFrame, closedFrame, postFrame].filter(
        (frame): frame is string => Boolean(frame),
      );
      if (frames.length < 2) {
        reject(
          new Error(
            "Could not get a clear view of your face. Please try again.",
          ),
        );
        return;
      }
      resolve({ frames, blinkConfirmed });
    };

    const timeoutId = window.setTimeout(() => finish(false), timeoutMs);

    const tick = () => {
      if (settled) return;
      if (video.readyState >= 2) {
        try {
          const result: FaceLandmarkerResult = landmarker.detectForVideo(
            video,
            performance.now(),
          );
          const shapes = result.faceBlendshapes?.[0]?.categories ?? [];
          const left =
            shapes.find((category) => category.categoryName === "eyeBlinkLeft")
              ?.score ?? 0;
          const right =
            shapes.find((category) => category.categoryName === "eyeBlinkRight")
              ?.score ?? 0;
          const blinkScore = (left + right) / 2;

          if (state === "watching-open") {
            if (blinkScore < BLINK_OPEN_THRESHOLD) {
              openFrame = captureFrame();
            } else if (blinkScore >= BLINK_CLOSED_THRESHOLD && openFrame) {
              state = "watching-closed";
              closedPeakScore = blinkScore;
              closedFrame = captureFrame();
              onStatus?.("Blink detected…");
            }
          } else if (state === "watching-closed") {
            if (blinkScore >= closedPeakScore) {
              closedPeakScore = blinkScore;
              closedFrame = captureFrame();
            }
            if (blinkScore < BLINK_OPEN_THRESHOLD) {
              postFrame = captureFrame();
              finish(true);
              return;
            }
          }
        } catch (error) {
          console.warn("Blink detector frame error:", error);
        }
      }
      rafId = window.requestAnimationFrame(tick);
    };

    rafId = window.requestAnimationFrame(tick);
  });
}
