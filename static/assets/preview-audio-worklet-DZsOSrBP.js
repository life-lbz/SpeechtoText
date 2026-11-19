const CHUNK_SECONDS = 4;
const HEADER_BYTES = 44;

class PreviewAudioProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.chunkSamples = Math.round(sampleRate * CHUNK_SECONDS);
    this.resetChunk();
  }

  resetChunk() {
    this.sampleCount = 0;
    const dataBytes = this.chunkSamples * 2;
    this.wav = new DataView(new ArrayBuffer(HEADER_BYTES + dataBytes));
    for (const [offset, label] of [[0, 'RIFF'], [8, 'WAVEfmt '], [36, 'data']]) {
      for (let index = 0; index < label.length; index += 1) {
        this.wav.setUint8(offset + index, label.charCodeAt(index));
      }
    }
    this.wav.setUint32(4, 36 + dataBytes, true);
    this.wav.setUint32(16, 16, true);
    this.wav.setUint16(20, 1, true); // PCM
    this.wav.setUint16(22, 1, true); // 单声道
    this.wav.setUint32(24, sampleRate, true);
    this.wav.setUint32(28, sampleRate * 2, true);
    this.wav.setUint16(32, 2, true);
    this.wav.setUint16(34, 16, true);
    this.wav.setUint32(40, dataBytes, true);
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel) return true;

    for (const value of channel) {
      const sample = Math.max(-1, Math.min(1, value));
      this.wav.setInt16(HEADER_BYTES + this.sampleCount * 2, sample * 32767, true);
      this.sampleCount += 1;
      if (this.sampleCount === this.chunkSamples) {
        const buffer = this.wav.buffer;
        this.port.postMessage(buffer, [buffer]);
        this.resetChunk();
      }
    }
    return true;
  }
}

registerProcessor('preview-audio', PreviewAudioProcessor);
