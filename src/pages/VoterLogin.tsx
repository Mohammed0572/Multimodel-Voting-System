import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Link } from "react-router-dom";
import { useLanguage } from "../context/LanguageContext";
import { useAuth, API_BASE } from "../context/AuthContext";
import {
  announceVoiceMessage,
  isVoiceAssistantEnabled,
  isVoiceAssistantSupported,
  setVoiceAssistantEnabled,
} from "../lib/voiceAssistant";

import { useCamera } from "../lib/useCamera";
import { captureLiveness, isLiveAction } from "../lib/livenessCapture";

const VOTER_ID_PATTERN = /^[A-Z0-9/-]{1,64}$/;

type Status = {
  message: string;
  type: "info" | "success" | "error";
};

const VoterLogin = () => {
  const { t } = useLanguage();
  const { setAuth } = useAuth();
  const [voterId, setVoterId] = useState("");
  const [isCameraActive, setIsCameraActive] = useState(false);
  const [lightingMessage, setLightingMessage] = useState("");
  const [status, setStatus] = useState<Status>({ message: "", type: "info" });
  const [isProcessing, setIsProcessing] = useState(false);
  const [guidedCapture, setGuidedCapture] = useState(false);
  const [profileNotice, setProfileNotice] = useState("");
  const [voiceEnabled, setVoiceEnabled] = useState(isVoiceAssistantEnabled);

  const { videoRef, mountedRef, abortRef, startCamera, stopCamera } = useCamera();
  const processingRef = useRef(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (!isCameraActive) {
      setLightingMessage("");
      return;
    }

    const sampleCanvas = document.createElement("canvas");
    sampleCanvas.width = 32;
    sampleCanvas.height = 24;
    const sampleContext = sampleCanvas.getContext("2d", { willReadFrequently: true });
    const intervalId = window.setInterval(() => {
      const video = videoRef.current;
      if (!video || video.readyState < 2 || !sampleContext) return;
      sampleContext.drawImage(video, 0, 0, sampleCanvas.width, sampleCanvas.height);
      const pixels = sampleContext.getImageData(0, 0, sampleCanvas.width, sampleCanvas.height).data;
      let brightness = 0;
      for (let index = 0; index < pixels.length; index += 4) {
        brightness += 0.2126 * pixels[index] + 0.7152 * pixels[index + 1] + 0.0722 * pixels[index + 2];
      }
      brightness /= pixels.length / 4;
      setLightingMessage(
        brightness < 42
          ? "Lighting is low. Face a window or lamp; your face should be clearly visible."
          : brightness > 225
            ? "The camera looks overexposed. Turn away from direct light."
            : "Lighting looks good. Keep your face centered for the live movement check.",
      );
    }, 500);

    return () => window.clearInterval(intervalId);
  }, [isCameraActive, videoRef]);

  const updateStatus = (message: string, type: Status["type"] = "info") => {
    if (!mountedRef.current) return;
    setStatus({ message, type });
    if (type === "error" || type === "success") announceVoiceMessage(message);
  };

  const toggleVoiceAssistant = () => {
    if (!isVoiceAssistantSupported()) return;
    const enabled = !voiceEnabled;
    setVoiceAssistantEnabled(enabled);
    setVoiceEnabled(enabled);
    if (enabled) {
      announceVoiceMessage(
        "Voice guidance is on. I will speak important login updates, errors, and voting confirmations.",
      );
    }
  };

  const handlePaste = (event: React.ClipboardEvent<HTMLInputElement>) => {
    const pastedText = event.clipboardData.getData("text").trim().toUpperCase();
    if (!VOTER_ID_PATTERN.test(pastedText)) {
      event.preventDefault();
      updateStatus(
        "Use up to 64 characters: letters, numbers, hyphens, or slashes.",
        "error",
      );
      return;
    }
    event.preventDefault();
    setVoterId(pastedText);
  };

  const startWebcam = async () => {
    try {
      updateStatus("Camera initializing…");
      if (await startCamera()) {
        setIsCameraActive(true);
        updateStatus("Camera ready. Tap Verify, keep still and follow the eye prompts.");
      }
    } catch (error) {
      updateStatus(error instanceof Error ? error.message : "Camera is unavailable.", "error");
    }
  };

  const verifyVoter = async (event?: React.FormEvent) => {
    event?.preventDefault();
    if (processingRef.current) return;
    const normalizedVoterId = voterId.trim().toUpperCase();

    if (!VOTER_ID_PATTERN.test(normalizedVoterId)) {
      updateStatus(
        "Enter a valid Voter ID using letters, numbers, hyphens, or slashes.",
        "error",
      );
      return;
    }

    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (
      !video ||
      !canvas ||
      !isCameraActive ||
      video.readyState < 2 ||
      !video.videoWidth
    ) {
      updateStatus(
        "Start the camera and wait for the live preview before verifying.",
        "error",
      );
      return;
    }

    const context = canvas.getContext("2d");
    if (!context) {
      updateStatus(
        "The browser could not prepare the camera capture. Please try again.",
        "error",
      );
      return;
    }

    processingRef.current = true;
    setIsProcessing(true);
    updateStatus("Starting a fresh live check…");

    const attempt = new AbortController();
    const lifetimeSignal = abortRef.current.signal;
    const cancelAttempt = () => attempt.abort();
    lifetimeSignal.addEventListener("abort", cancelAttempt, { once: true });
    if (lifetimeSignal.aborted) attempt.abort();
    let timedOut = false;
    const timeout = window.setTimeout(() => {
      timedOut = true;
      attempt.abort();
    }, 30_000);

    try {
      const challengeResponse = await fetch(
        `${API_BASE}/liveness/challenge?voter_id=${encodeURIComponent(normalizedVoterId)}&guided=${guidedCapture || voiceEnabled}`,
        { credentials: "include", signal: attempt.signal },
      );
      const challengeData = await challengeResponse.json().catch(() => ({}));
      if (challengeResponse.ok && challengeData.face_engine_version !== 3) {
        throw new Error("The face service is still running the old version. Restart the demo, refresh this page, and try again.");
      }
      if (!challengeResponse.ok || !challengeData.challenge_id || !isLiveAction(challengeData.challenge)) {
        throw new Error(
          challengeData.detail || "Could not start the live check. Please try again.",
        );
      }

      updateStatus(
        challengeData.instruction ||
          "Keep your face centered. I’ll tell you when to blink.",
      );
      setProfileNotice(challengeData.face_update_pending
        ? "Your replacement is awaiting administrator approval. Your previous face profile is still active."
        : challengeData.profile_model === "sface-2021dec-v1"
          ? "Your updated face profile is active."
          : "This is an older face profile. One new enrollment and administrator approval will enable quick login.");
      const frames = await captureLiveness(video, canvas, challengeData.challenge, attempt.signal, (message) => {
        updateStatus(message);
        announceVoiceMessage(message);
      }, challengeData.capture_mode === "quick" ? "quick" : "guided");

      updateStatus("Liveness check and identity verification…");
      const response = await fetch(`${API_BASE}/verify-face`, {
        method: "POST",
        signal: attempt.signal,
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          voter_id: normalizedVoterId,
          challenge_id: challengeData.challenge_id,
          images_base64: frames,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(
          errorData.detail ||
            (response.status === 401
              ? "Face verification failed. Check your voter ID, face lighting, and blink, then try again."
              : "Verification failed. Please try again."),
        );
      }

      const data = await response.json();
      if (!mountedRef.current) return;
      setAuth({
        voter_id: data.voter_id,
        role: data.role,
        name: data.name || undefined,
        usn: data.usn || undefined,
        branch: data.branch || undefined,
        validity: data.validity || undefined,
        dob: data.dob || undefined,
      });
      stopCamera();
      setIsCameraActive(false);
      updateStatus(
        "Face recognized. You are logged in. Checking your voting eligibility now.",
        "success",
      );
      navigate("/voting");
    } catch (error) {
      console.error("Verification error:", error);
      updateStatus(
        timedOut ? "Verification took too long. Please start a fresh live check." : error instanceof Error
          ? error.message === "Failed to fetch"
            ? `Authentication service unavailable at ${API_BASE}. Start the FastAPI backend and try again.`
            : error.message
          : "Network error. Please check the authentication service.",
        "error",
      );
    } finally {
      window.clearTimeout(timeout);
      lifetimeSignal.removeEventListener("abort", cancelAttempt);
      processingRef.current = false;
      if (mountedRef.current) setIsProcessing(false);
    }
  };

  return (
    <div className="grow flex flex-col items-center justify-center w-full">
      <div className="w-full max-w-md overflow-hidden rounded-md border border-hairline bg-paper shadow-sm">
        <div className="border-b border-hairline bg-paper-warm p-6 text-center">
          <h2 className="font-display text-2xl font-semibold text-ink">
            {t("voter.title")}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("voter.subtitle")}
          </p>
          <button
            type="button"
            onClick={toggleVoiceAssistant}
            disabled={!isVoiceAssistantSupported()}
            aria-pressed={voiceEnabled}
            className="mt-4 inline-flex items-center justify-center gap-2 rounded-md border border-hairline bg-paper px-3 py-2 text-sm font-medium text-ink hover:border-ink disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span aria-hidden="true">{voiceEnabled ? "🔊" : "🔈"}</span>
            {isVoiceAssistantSupported()
              ? `Voice guidance ${voiceEnabled ? "on" : "off"}`
              : "Voice guidance unavailable in this browser"}
          </button>
          <p className="mt-1 text-xs text-muted-foreground">
            Speaks login errors and important voting updates.
          </p>
        </div>

        <form onSubmit={verifyVoter} className="p-6 sm:p-8 space-y-5">
          <div>
            <label className="text-sm font-medium text-ink" htmlFor="voterId">
              {t("voter.id_label")}
            </label>
            <input
              id="voterId"
              type="text"
              value={voterId}
              onChange={(event) => setVoterId(event.target.value.toUpperCase())}
              onPaste={handlePaste}
              placeholder="e.g. VTR-84291"
              className="mt-2 w-full rounded-md border border-hairline bg-paper px-3 py-2 text-sm text-ink placeholder:text-muted-foreground focus:border-saffron focus:outline-none focus:ring-1 focus:ring-saffron"
              maxLength={64}
              autoComplete="off"
              autoCapitalize="characters"
              spellCheck={false}
              aria-describedby="voter-id-help"
            />
            <p
              id="voter-id-help"
              className="mt-1 text-xs text-muted-foreground"
            >
              Letters, numbers, hyphens, and slashes only.
            </p>
          </div>

          <div>
            <label className="text-sm font-medium text-ink">
              {t("voter.step2")}
            </label>
            <p className="mb-2 text-xs text-muted-foreground">
              {t("voter.align_face")}
            </p>
            <div className="group relative aspect-video w-full overflow-hidden rounded-md border border-hairline bg-paper-warm">
              <video
                ref={videoRef}
                autoPlay
                playsInline
                muted
                className="h-full w-full scale-x-[-1] object-cover"
                aria-label="Live camera preview"
              />
              <canvas ref={canvasRef} className="hidden" />
              {!isCameraActive && (
                <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-paper-warm text-muted-foreground">
                  <svg
                    className="w-12 h-12 mb-2"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                    aria-hidden="true"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="2"
                      d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5v12z"
                    />
                  </svg>
                  <span className="text-base font-bold">
                    {t("voter.cam_inactive")}
                  </span>
                </div>
              )}
            </div>
            <p className="mt-2 rounded-sm border border-india-blue/20 bg-india-blue-lt px-3 py-2 text-xs leading-relaxed text-india-blue">
              <strong>Live verification:</strong> Keep your head still. Close both
              eyes, then open them when prompted.
            </p>
            <label className="mt-3 flex items-center gap-2 text-sm text-muted-foreground">
              <input type="checkbox" checked={guidedCapture} disabled={isProcessing}
                onChange={event => setGuidedCapture(event.target.checked)} />
              Give me more time for the eye prompts
            </label>
            {profileNotice && <p className="mt-2 text-sm text-india-blue" role="note">{profileNotice}</p>}
            {isCameraActive && lightingMessage && (
              <p
                className={`mt-2 text-xs ${lightingMessage.startsWith("Lighting is low") || lightingMessage.startsWith("The camera looks") ? "text-amber-700" : "text-india-green"}`}
                aria-live="polite"
              >
                {lightingMessage}
              </p>
            )}
          </div>

          {status.message && (
            <div
              role={status.type === "error" ? "alert" : "status"}
              aria-live={status.type === "error" ? "assertive" : "polite"}
              className={`p-4 border-l-4 rounded-sm ${status.type === "error" ? "bg-[#FFF5F5] border-danger text-danger" : status.type === "success" ? "bg-india-green-light border-india-green text-india-green" : "bg-india-blue-lt border-india-blue text-india-blue"}`}
            >
              <strong>{t("voter.status")}</strong> {status.message}
            </div>
          )}

          <div className="flex gap-3 pt-2">
            {!isCameraActive ? (
              <button
                type="button"
                onClick={startWebcam}
                className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-hairline bg-paper px-4 py-2 text-sm font-semibold text-ink hover:border-ink"
              >
                {t("voter.enable_cam")}
              </button>
            ) : (
              <button
                type="submit"
                disabled={isProcessing}
                className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-saffron px-4 py-2 text-sm font-semibold text-paper shadow-sm hover:bg-saffron/90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isProcessing ? t("voter.processing") : t("voter.verify_btn")}
              </button>
            )}
          </div>
        </form>
        <div className="border-t border-hairline px-6 py-4 text-center text-sm text-muted-foreground">
          Face not matching?{" "}
          <Link to="/register" className="font-medium text-india-blue underline">
            Update your face image
          </Link>
          <p className="mt-1 text-xs">
            A replacement is activated after an administrator checks your ID card.
          </p>
        </div>
      </div>
    </div>
  );
};

export default VoterLogin;
