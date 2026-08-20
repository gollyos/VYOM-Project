type MicrophoneCallbacks = {
  onAudio: (pcm: ArrayBuffer) => void;
  onLevel: (level: number) => void;
};

export class MicrophoneCapture {
  private context: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private processor: AudioWorkletNode | null = null;
  private silentGain: GainNode | null = null;

  async start(callbacks: MicrophoneCallbacks) {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new DOMException("No microphone API is available.", "NotFoundError");
    }

    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      video: false,
    });

    this.context = new AudioContext({ latencyHint: "interactive" });
    await this.context.audioWorklet.addModule("/vyom-audio-processor.js");
    await this.context.resume();

    this.source = this.context.createMediaStreamSource(this.stream);
    this.processor = new AudioWorkletNode(this.context, "vyom-audio-processor", {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      outputChannelCount: [1],
    });
    this.silentGain = this.context.createGain();
    this.silentGain.gain.value = 0;

    this.processor.port.onmessage = (event: MessageEvent<{ type: string; buffer?: ArrayBuffer; value?: number }>) => {
      if (event.data.type === "audio" && event.data.buffer) callbacks.onAudio(event.data.buffer);
      if (event.data.type === "level" && typeof event.data.value === "number") {
        callbacks.onLevel(event.data.value);
      }
    };

    this.source.connect(this.processor);
    this.processor.connect(this.silentGain);
    this.silentGain.connect(this.context.destination);
  }

  async stop() {
    this.processor?.disconnect();
    this.source?.disconnect();
    this.silentGain?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    if (this.context && this.context.state !== "closed") await this.context.close();
    this.context = null;
    this.stream = null;
    this.source = null;
    this.processor = null;
    this.silentGain = null;
  }
}

function decodeBase64Pcm(value: string) {
  const binary = window.atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  const sampleCount = Math.floor(bytes.byteLength / 2);
  const samples = new Float32Array(sampleCount);
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let energy = 0;
  for (let index = 0; index < sampleCount; index += 1) {
    const sample = view.getInt16(index * 2, true) / 0x8000;
    samples[index] = sample;
    energy += sample * sample;
  }
  return { samples, level: Math.sqrt(energy / Math.max(sampleCount, 1)) };
}

export function pcmBufferToBase64(buffer: ArrayBuffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let index = 0; index < bytes.length; index += 1) binary += String.fromCharCode(bytes[index]);
  return window.btoa(binary);
}

export class PcmAudioPlayer {
  private context: AudioContext | null = null;
  private nextStartTime = 0;
  private sources = new Set<AudioBufferSourceNode>();

  constructor(
    private readonly onStart: () => void,
    private readonly onIdle: () => void,
    private readonly onLevel: (level: number) => void,
  ) {}

  async enqueue(base64Audio: string, sampleRate: number) {
    if (!this.context || this.context.state === "closed") {
      this.context = new AudioContext({ latencyHint: "interactive" });
    }
    if (this.context.state === "suspended") await this.context.resume();

    const { samples, level } = decodeBase64Pcm(base64Audio);
    const audioBuffer = this.context.createBuffer(1, samples.length, sampleRate);
    audioBuffer.copyToChannel(samples, 0);
    const source = this.context.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(this.context.destination);

    const startAt = Math.max(this.context.currentTime + 0.018, this.nextStartTime);
    this.nextStartTime = startAt + audioBuffer.duration;
    this.sources.add(source);
    this.onLevel(level);
    if (this.sources.size === 1) this.onStart();

    source.onended = () => {
      this.sources.delete(source);
      source.disconnect();
      if (this.sources.size === 0) {
        this.nextStartTime = this.context?.currentTime ?? 0;
        this.onLevel(0);
        this.onIdle();
      }
    };
    source.start(startAt);
  }

  clear() {
    this.sources.forEach((source) => {
      source.onended = null;
      try { source.stop(); } catch { /* source already stopped */ }
      source.disconnect();
    });
    this.sources.clear();
    this.nextStartTime = this.context?.currentTime ?? 0;
    this.onLevel(0);
    this.onIdle();
  }

  async close() {
    this.clear();
    if (this.context && this.context.state !== "closed") await this.context.close();
    this.context = null;
  }

  get isPlaying() {
    return this.sources.size > 0;
  }
}
