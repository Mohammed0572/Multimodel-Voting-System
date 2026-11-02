import { useEffect, useRef } from "react";

/** Owns even a stream granted after navigation or a second start attempt. */
export function useCamera() {
  const streamRef = useRef<MediaStream | null>(null);
  const mountedRef = useRef(true);
  const generation = useRef(0);
  const starting = useRef(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const abortRef = useRef(new AbortController());

  const stopCamera = () => {
    generation.current += 1;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  };

  useEffect(() => {
    mountedRef.current = true;
    abortRef.current = new AbortController();
    return () => {
      mountedRef.current = false;
      abortRef.current.abort();
      generation.current += 1;
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    };
  }, []);

  const startCamera = async () => {
    if (starting.current) return false;
    starting.current = true;
    stopCamera();
    const current = generation.current;
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error("Camera access requires a supported browser on HTTPS or localhost.");
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } }, audio: false,
      });
      if (!mountedRef.current || current !== generation.current || !videoRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return false;
      }
      streamRef.current = stream;
      videoRef.current.srcObject = stream;
      await videoRef.current.play();
      return mountedRef.current && current === generation.current;
    } catch (error) {
      stopCamera();
      if (error instanceof DOMException) {
        const messages: Record<string, string> = {
          NotAllowedError: "Camera permission was denied. Allow camera access in your browser.",
          NotFoundError: "No camera was found. Connect a webcam and try again.",
          NotReadableError: "Camera is busy or unavailable. Close other camera apps and try again.",
        };
        throw Object.assign(new Error(messages[error.name] || "Camera could not start. Please try again."), { cause: error });
      }
      throw error;
    } finally {
      starting.current = false;
    }
  };

  return { videoRef, streamRef, mountedRef, abortRef, startCamera, stopCamera };
}
