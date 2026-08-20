class VyomAudioProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.pending = [];
    this.targetRate = 16000;
    this.chunkSamples = 640;
    this.ratio = sampleRate / this.targetRate;
    this.levelFrame = 0;
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel) return true;

    let energy = 0;
    for (let index = 0; index < channel.length; index += 1) {
      const sample = channel[index];
      this.pending.push(sample);
      energy += sample * sample;
    }

    this.levelFrame += 1;
    if (this.levelFrame % 3 === 0) {
      this.port.postMessage({ type: "level", value: Math.sqrt(energy / channel.length) });
    }

    const sourceSamples = Math.ceil(this.chunkSamples * this.ratio);
    while (this.pending.length >= sourceSamples) {
      const pcm = new Int16Array(this.chunkSamples);
      for (let index = 0; index < this.chunkSamples; index += 1) {
        const sourcePosition = index * this.ratio;
        const lower = Math.floor(sourcePosition);
        const upper = Math.min(lower + 1, sourceSamples - 1);
        const mix = sourcePosition - lower;
        const sample = this.pending[lower] * (1 - mix) + this.pending[upper] * mix;
        const clamped = Math.max(-1, Math.min(1, sample));
        pcm[index] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
      }
      this.pending.splice(0, sourceSamples);
      this.port.postMessage({ type: "audio", buffer: pcm.buffer }, [pcm.buffer]);
    }

    return true;
  }
}

registerProcessor("vyom-audio-processor", VyomAudioProcessor);
