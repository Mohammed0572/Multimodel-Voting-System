import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useLanguage } from "../context/LanguageContext";
import { useAuth, API_BASE } from "../context/AuthContext";

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
  const [status, setStatus] = useState<Status>({ message: "", type: "info" });
  const [isProcessing, setIsProcessing] = useState(false);

  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    };
  }, []);

  const updateStatus = (message: string, type: Status["type"] = "info") => {
    setStatus({ message, type });
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
    if (!navigator.mediaDevices?.getUserMedia) {
      updateStatus("This browser does not support camera access.", "error");
      return;
    }

    try {
      updateStatus("Requesting camera access…");
      streamRef.current?.getTracks().forEach((track) => track.stop());
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: "user",
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => undefined);
      }
      setIsCameraActive(true);
      updateStatus(
        "Camera active. Center your face, then verify your identity.",
        "success",
      );
    } catch (error) {
      console.error("Webcam error:", error);
      updateStatus(
        "Camera access was denied or is unavailable. Check browser permissions and try again.",
        "error",
      );
    }
  };

  const verifyVoter = async (event?: React.FormEvent) => {
    event?.preventDefault();
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

    setIsProcessing(true);
    updateStatus("Recording liveness data… Please blink naturally.");

    try {
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      const frames: string[] = [];
      const maxFrames = 10;

      for (let index = 0; index < maxFrames; index += 1) {
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
        frames.push(canvas.toDataURL("image/jpeg", 0.7));
        if (index < maxFrames - 1) {
          await new Promise((resolve) => window.setTimeout(resolve, 150));
        }
      }

      updateStatus("Verifying identity securely…");
      const response = await fetch(`${API_BASE}/verify-face`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          voter_id: normalizedVoterId,
          images_base64: frames,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        if (response.status === 401) {
          throw new Error("Face mismatch or Voter ID not found.");
        }
        throw new Error(
          errorData.detail || "Verification failed. Please try again.",
        );
      }

      const data = await response.json();
      setAuth({
        voter_id: data.voter_id,
        role: data.role,
        name: data.name || undefined,
        usn: data.usn || undefined,
        branch: data.branch || undefined,
        validity: data.validity || undefined,
        dob: data.dob || undefined,
      });
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      setIsCameraActive(false);
      updateStatus("Identity verified. Checking eligibility and preparing your private voting session…", "success");
      navigate("/voting");
    } catch (error) {
      console.error("Verification error:", error);
      updateStatus(
        error instanceof Error
          ? error.message
          : "Network error. Please check the authentication service.",
        "error",
      );
    } finally {
      setIsProcessing(false);
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
      </div>
    </div>
  );
};

export default VoterLogin;
