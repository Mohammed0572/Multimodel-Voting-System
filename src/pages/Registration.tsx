import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { API_BASE } from "../context/AuthContext";
import { createWorker } from "tesseract.js";

type Status = {
  message: string;
  type: "info" | "success" | "error";
};

export function extractFields(text: string) {
  const extracted: Record<string, string> = {
    name: "",
    usn: "",
    branch: "",
    validity: "",
    dob: "",
  };

  const cleanedText = text.replace(/\r/g, "\n");
  const lines = cleanedText
    .split("\n")
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter(Boolean);

  const captureValue = (line: string, labelPatterns: RegExp[]) => {
    for (const pattern of labelPatterns) {
      const match = line.match(pattern);
      if (match) {
        return match[1].trim();
      }
    }
    return "";
  };

  for (const line of lines) {
    const lowerLine = line.toLowerCase();

    if (!extracted.usn) {
      const usnMatch =
        line.match(
          /(?:USN|Student\s*ID|Voter\s*ID)\s*(?:No\.?|Number)?\s*[:\-]?\s*([1][A-Z0-9]{9,})/i,
        ) ?? line.match(/\b([1][A-Z0-9]{9,})\b/);
      if (usnMatch) extracted.usn = usnMatch[1].toUpperCase();
    }

    if (!extracted.branch) {
      const branchValue = captureValue(line, [
        /(?:Branch|Department|Program)\s*[:\-]?\s*([A-Za-z0-9&/\s.-]+?)(?=\s*(?:Validity|Valid|Expiry|Date\s*of\s*Birth|DOB|USN|Name)\b|$)/i,
        /(?:Branch|Department|Program)\s*[:\-]?\s*([A-Za-z0-9&/\s.-]+)/i,
      ]);
      if (branchValue)
        extracted.branch = branchValue.replace(/\s+/g, " ").trim();
    }

    if (!extracted.validity) {
      const validityValue = captureValue(line, [
        /(?:Validity|Valid\s*Till|Expiry|Valid\s*Up\s*To)\s*[:\-]?\s*(\d{4}(?:\s*[-–]\s*\d{4})?|\d{2}[/-]\d{2}[/-]\d{4})/i,
        /(?:Validity|Valid\s*Till|Expiry)\s*[:\-]?\s*(\d{4})/i,
      ]);
      if (validityValue) extracted.validity = validityValue.trim();
    }

    if (!extracted.dob) {
      const dobMatch = line.match(
        /(?:Date\s*of\s*Birth|DOB)\s*[:\-]?\s*(\d{2}[-/]\d{2}[-/]\d{4})/i,
      );
      if (dobMatch) extracted.dob = dobMatch[1].trim();
    }

    if (!extracted.name) {
      const nameMatch = line.match(
        /(?:Name|Student\s*Name)\s*[:\-]?\s*([A-Z][A-Za-z'&.-]+(?:\s+[A-Z][A-Za-z'&.-]+){1,4})/,
      );
      if (nameMatch) extracted.name = nameMatch[1].replace(/\s+/g, " ").trim();
    }
  }

  const skipWords = [
    "identity",
    "card",
    "branch",
    "validity",
    "date",
    "blood",
    "usn",
    "school",
    "group",
    "engineering",
    "management",
    "principal",
    "kssem",
    "sangham",
    "college",
    "campus",
    "department",
  ];
  if (!extracted.name) {
    for (const line of lines) {
      const candidate = line.replace(/[^A-Za-z&\s.-]/g, "").trim();
      const words = candidate.split(/\s+/).filter(Boolean);
      const isNameLike =
        words.length >= 2 &&
        words.length <= 5 &&
        words.every(
          (word) =>
            /^[A-Z][A-Za-z'&.-]*$/.test(word) || /^[A-Z]{2,}$/.test(word),
        ) &&
        !words.some((word) => skipWords.includes(word.toLowerCase()));
      if (isNameLike) {
        extracted.name = candidate.replace(/\s+/g, " ").trim();
        break;
      }
    }
  }

  return extracted;
}

const Registration = () => {
  const navigate = useNavigate();

  const [step, setStep] = useState(1);
  const [status, setStatus] = useState<Status>({ message: "", type: "info" });
  const [isProcessing, setIsProcessing] = useState(false);
  const [isCameraActive, setIsCameraActive] = useState(false);

  const [name, setName] = useState("");
  const [usn, setUsn] = useState("");
  const [branch, setBranch] = useState("");
  const [validity, setValidity] = useState("");
  const [dob, setDob] = useState("");

  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    };
  }, []);

  const updateStatus = (message: string, type: Status["type"] = "info") => {
    setStatus({ message, type });
  };

  const waitForVideoFrame = async (video: HTMLVideoElement) => {
    if (
      video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA &&
      video.videoWidth &&
      video.videoHeight
    ) {
      return true;
    }

    return new Promise<boolean>((resolve) => {
      const timeout = window.setTimeout(() => {
        cleanup();
        resolve(false);
      }, 2500);

      const markReady = () => {
        cleanup();
        resolve(Boolean(video.videoWidth && video.videoHeight));
      };

      const cleanup = () => {
        window.clearTimeout(timeout);
        video.removeEventListener("loadedmetadata", markReady);
        video.removeEventListener("canplay", markReady);
      };

      video.addEventListener("loadedmetadata", markReady);
      video.addEventListener("canplay", markReady);
    });
  };

  const captureFaceFrames = async (
    video: HTMLVideoElement,
    canvas: HTMLCanvasElement,
    context: CanvasRenderingContext2D,
  ) => {
    const ready = await waitForVideoFrame(video);
    if (!ready) {
      throw new Error(
        "Camera preview is not ready yet. Wait a moment and try again.",
      );
    }

    const targetWidth = Math.min(video.videoWidth, 960);
    const targetHeight = Math.round(
      (video.videoHeight / video.videoWidth) * targetWidth,
    );
    canvas.width = targetWidth;
    canvas.height = targetHeight;

    const frames: string[] = [];
    for (let index = 0; index < 5; index += 1) {
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      frames.push(canvas.toDataURL("image/jpeg", 0.72));
      if (index < 4) {
        await new Promise((resolve) => window.setTimeout(resolve, 120));
      }
    }

    return frames;
  };

  const handleIDUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setIsProcessing(true);
    updateStatus("Reading ID card (this may take a few seconds)...", "info");

    try {
      const worker = await createWorker("eng");
      const { data } = await worker.recognize(file);
      await worker.terminate();

      const extracted = extractFields(data.text);
      setName(extracted.name);
      setUsn(extracted.usn);
      setBranch(extracted.branch);
      setValidity(extracted.validity);
      setDob(extracted.dob);

      updateStatus(
        "Details extracted! Please verify and correct if needed.",
        "success",
      );
      setStep(2);
    } catch (err) {
      console.error("OCR error:", err);
      updateStatus(
        "Could not read the ID card automatically. Please fill in details manually.",
        "error",
      );
      setStep(2);
    } finally {
      setIsProcessing(false);
    }
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
      updateStatus("Camera active. Keep face steady to capture.", "success");
      setStep(3);
    } catch {
      updateStatus("Camera access denied.", "error");
    }
  };

  const registerUser = async () => {
    if (!usn.trim()) {
      updateStatus("USN is required.", "error");
      return;
    }

    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || !isCameraActive) {
      updateStatus("Start camera first.", "error");
      return;
    }

    const context = canvas.getContext("2d");
    if (!context) return;

    setIsProcessing(true);
    updateStatus("Capturing face samples and registering...");

    try {
      const faceFramesBase64 = await captureFaceFrames(video, canvas, context);

      const response = await fetch(`${API_BASE}/register-user`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          voter_id: usn.trim().toLowerCase(),
          image_base64: faceFramesBase64[0],
          images_base64: faceFramesBase64,
          name,
          usn,
          branch,
          validity,
          dob,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || "Registration failed.");
      }

      updateStatus(
        "Registration successful! Redirecting to login...",
        "success",
      );
      setTimeout(() => navigate("/login"), 2000);
    } catch (error) {
      updateStatus(
        error instanceof Error ? error.message : "Error occurred.",
        "error",
      );
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <div className="grow flex flex-col items-center justify-center w-full my-8">
      <div className="w-full max-w-lg overflow-hidden rounded-md border border-hairline bg-paper shadow-sm">
        <div className="border-b border-hairline bg-paper-warm p-6 text-center">
          <h2 className="font-display text-2xl font-semibold text-ink">
            Voter Registration
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Register securely using your college ID card.
          </p>
        </div>

        <div className="p-6 sm:p-8 space-y-5">
          {/* Step indicators */}
          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground mb-2">
            {["Upload ID", "Verify Details", "Face Capture"].map((label, i) => (
              <div key={label} className="flex items-center gap-2">
                <span
                  className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold ${step > i + 1 ? "bg-india-green text-white" : step === i + 1 ? "bg-saffron text-white" : "bg-paper-warm border border-hairline text-muted-foreground"}`}
                >
                  {i + 1}
                </span>
                <span className={step === i + 1 ? "text-ink" : ""}>
                  {label}
                </span>
                {i < 2 && <span className="text-hairline">›</span>}
              </div>
            ))}
          </div>

          {step === 1 && (
            <div className="space-y-3">
              <label className="text-sm font-medium text-ink block">
                Upload your College ID Card
              </label>
              <p className="text-xs text-muted-foreground">
                The system will automatically read your USN, name, branch, DOB,
                and validity.
              </p>
              <label
                className={`flex flex-col items-center justify-center w-full h-36 border-2 border-dashed rounded-md cursor-pointer transition ${isProcessing ? "border-saffron bg-saffron/5" : "border-hairline hover:border-india-blue bg-paper-warm hover:bg-india-blue-lt/30"}`}
              >
                {isProcessing ? (
                  <>
                    <div className="w-6 h-6 border-2 border-saffron border-t-transparent rounded-full animate-spin mb-2" />
                    <span className="text-sm text-saffron font-medium">
                      Reading ID card...
                    </span>
                  </>
                ) : (
                  <>
                    <svg
                      className="w-8 h-8 mb-2 text-muted-foreground"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={1.5}
                        d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"
                      />
                    </svg>
                    <span className="text-sm text-muted-foreground">
                      Click to upload ID card photo
                    </span>
                    <span className="text-xs text-muted-foreground mt-1">
                      JPG, PNG, HEIC supported
                    </span>
                  </>
                )}
                <input
                  type="file"
                  accept="image/*"
                  onChange={handleIDUpload}
                  disabled={isProcessing}
                  className="hidden"
                />
              </label>
              <button
                type="button"
                onClick={() => setStep(2)}
                className="text-xs text-india-blue underline w-full text-center"
              >
                Skip — enter details manually
              </button>
            </div>
          )}

          {step >= 2 && (
            <div className="space-y-4">
              <label className="text-sm font-medium text-ink block border-b pb-2">
                Verify & Edit Your Details
              </label>
              <div className="grid grid-cols-2 gap-4">
                <div className="col-span-2">
                  <label className="text-xs font-medium text-muted-foreground block mb-1">
                    USN *
                  </label>
                  <input
                    type="text"
                    value={usn}
                    onChange={(e) => setUsn(e.target.value)}
                    placeholder="1KG23CB052"
                    className="w-full rounded-md border border-hairline px-3 py-2 text-sm focus:border-saffron focus:outline-none"
                  />
                </div>
                <div className="col-span-2">
                  <label className="text-xs font-medium text-muted-foreground block mb-1">
                    Full Name
                  </label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="SYED MOHAMMED NAQVI"
                    className="w-full rounded-md border border-hairline px-3 py-2 text-sm focus:border-saffron focus:outline-none"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-muted-foreground block mb-1">
                    Branch
                  </label>
                  <input
                    type="text"
                    value={branch}
                    onChange={(e) => setBranch(e.target.value)}
                    placeholder="CS&BS"
                    className="w-full rounded-md border border-hairline px-3 py-2 text-sm focus:border-saffron focus:outline-none"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-muted-foreground block mb-1">
                    Date of Birth
                  </label>
                  <input
                    type="text"
                    value={dob}
                    onChange={(e) => setDob(e.target.value)}
                    placeholder="06-04-2005"
                    className="w-full rounded-md border border-hairline px-3 py-2 text-sm focus:border-saffron focus:outline-none"
                  />
                </div>
                <div className="col-span-2">
                  <label className="text-xs font-medium text-muted-foreground block mb-1">
                    Validity
                  </label>
                  <input
                    type="text"
                    value={validity}
                    onChange={(e) => setValidity(e.target.value)}
                    placeholder="2027"
                    className="w-full rounded-md border border-hairline px-3 py-2 text-sm focus:border-saffron focus:outline-none"
                  />
                </div>
              </div>
              {step === 2 && (
                <button
                  type="button"
                  onClick={startWebcam}
                  className="w-full mt-2 bg-saffron text-paper py-2.5 rounded-md font-semibold text-sm"
                >
                  Proceed to Face Capture →
                </button>
              )}
            </div>
          )}

          <div className={step === 3 ? "block" : "hidden"}>
            <label className="text-sm font-medium text-ink block border-b pb-2 mb-3">
              Capture Your Face
            </label>
            <div className="relative aspect-video w-full overflow-hidden rounded-md border border-hairline bg-paper-warm mb-4">
              <video
                ref={videoRef}
                autoPlay
                playsInline
                muted
                className="h-full w-full scale-x-[-1] object-cover"
              />
              <canvas ref={canvasRef} className="hidden" />
              {/* Oval face guide */}
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                <div className="w-40 h-52 rounded-full border-2 border-saffron border-dashed opacity-60" />
              </div>
            </div>
            <button
              type="button"
              onClick={registerUser}
              disabled={isProcessing}
              className="w-full bg-saffron text-paper py-2.5 rounded-md font-semibold text-sm disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isProcessing
                ? "Registering..."
                : "📸 Capture & Complete Registration"}
            </button>
          </div>

          {status.message && (
            <div
              className={`p-3 border-l-4 rounded-sm text-sm ${status.type === "error" ? "bg-[#FFF5F5] border-danger text-danger" : status.type === "success" ? "bg-india-green-light border-india-green text-india-green" : "bg-india-blue-lt border-india-blue text-india-blue"}`}
            >
              {status.message}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default Registration;
