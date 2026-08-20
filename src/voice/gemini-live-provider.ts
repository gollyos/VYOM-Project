import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type {
  VoiceProvider,
  VoiceProviderEvent,
  VoiceProviderInfo,
  VoiceProviderListener,
} from "./types";

export class GeminiLiveVoiceProvider implements VoiceProvider {
  private listeners = new Set<VoiceProviderListener>();
  private unlisten: UnlistenFn | null = null;

  async getInfo() {
    return invoke<VoiceProviderInfo>("voice_provider_info");
  }

  async connect() {
    await this.ensureEventBridge();
    return invoke<VoiceProviderInfo>("voice_connect");
  }

  async sendAudio(audioBase64: string) {
    await invoke("voice_send_audio", { audioBase64 });
  }

  /** Speak a Brain-produced result through the live session. */
  async speak(text: string) {
    await invoke("voice_speak", { text });
  }

  async endAudioStream() {
    await invoke("voice_audio_stream_end");
  }

  async disconnect() {
    await invoke("voice_disconnect");
  }

  async subscribe(listener: VoiceProviderListener) {
    this.listeners.add(listener);
    await this.ensureEventBridge();
    return () => this.listeners.delete(listener);
  }

  destroy() {
    this.listeners.clear();
    this.unlisten?.();
    this.unlisten = null;
  }

  private async ensureEventBridge() {
    if (this.unlisten) return;
    this.unlisten = await listen<VoiceProviderEvent>("voice-event", ({ payload }) => {
      this.listeners.forEach((listener) => listener(payload));
    });
  }
}
