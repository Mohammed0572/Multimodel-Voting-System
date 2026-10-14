const VOICE_ASSISTANT_PREFERENCE = "voting-voice-assistant-enabled";

export function isVoiceAssistantSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    "speechSynthesis" in window &&
    typeof SpeechSynthesisUtterance !== "undefined"
  );
}

export function isVoiceAssistantEnabled(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(VOICE_ASSISTANT_PREFERENCE) === "true";
  } catch {
    return false;
  }
}

export function setVoiceAssistantEnabled(enabled: boolean): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(VOICE_ASSISTANT_PREFERENCE, String(enabled));
  } catch {
    // Voice can still be used for this page if browser storage is unavailable.
  }
  if (!enabled && isVoiceAssistantSupported()) window.speechSynthesis.cancel();
}

export function announceVoiceMessage(message: string): void {
  if (!message || !isVoiceAssistantEnabled() || !isVoiceAssistantSupported()) return;

  const utterance = new SpeechSynthesisUtterance(message);
  utterance.volume = 1;
  utterance.rate = 0.96;
  utterance.pitch = 1;
  const englishVoice = window.speechSynthesis
    .getVoices()
    .find((voice) => voice.lang.toLowerCase().startsWith("en-in")) ??
    window.speechSynthesis
      .getVoices()
      .find((voice) => voice.lang.toLowerCase().startsWith("en"));
  if (englishVoice) utterance.voice = englishVoice;

  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
}
