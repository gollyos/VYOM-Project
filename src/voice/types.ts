export type VoiceRuntimeState =
  | "Idle"
  | "Listening"
  | "Understanding"
  | "Speaking"
  | "Interrupted";

export type VoiceConnectionState =
  | "inactive"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected"
  | "error";

export type VoiceErrorCode =
  | "native-required"
  | "microphone-unavailable"
  | "permission-denied"
  | "provider-unconfigured"
  | "provider-disconnected"
  | "api-error";

export type VoiceRuntimeError = {
  code: VoiceErrorCode;
  message: string;
  recoverable: boolean;
};

export type VoiceProviderInfo = {
  provider: string;
  model: string;
  configured: boolean;
};

export type VoiceProviderEvent = {
  kind:
    | "connecting"
    | "connected"
    | "disconnected"
    | "input-transcript"
    | "output-transcript"
    | "audio"
    | "interrupted"
    | "generation-complete"
    | "turn-complete"
    | "error";
  text?: string;
  data?: string;
  sampleRate?: number;
  code?: VoiceErrorCode;
  message?: string;
  recoverable?: boolean;
  model?: string;
};

export type VoiceProviderListener = (event: VoiceProviderEvent) => void;

export interface VoiceProvider {
  getInfo(): Promise<VoiceProviderInfo>;
  connect(): Promise<VoiceProviderInfo>;
  sendAudio(audioBase64: string): Promise<void>;
  /** Speak Brain-produced text; the provider must read it verbatim. */
  speak(text: string): Promise<void>;
  endAudioStream(): Promise<void>;
  disconnect(): Promise<void>;
  subscribe(listener: VoiceProviderListener): Promise<() => void>;
}
