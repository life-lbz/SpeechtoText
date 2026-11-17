const PREFERRED_MIME_TYPES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/ogg;codecs=opus',
  'audio/ogg',
];

function pickMimeType() {
  if (typeof MediaRecorder === 'undefined') return '';
  return PREFERRED_MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type)) || '';
}

export function mimeToExtension(mimeType = '') {
  if (mimeType.includes('ogg')) return 'ogg';
  if (mimeType.includes('mp4') || mimeType.includes('aac')) return 'm4a';
  if (mimeType.includes('wav')) return 'wav';
  return 'webm';
}

/**
 * 麦克风录音封装：开始 / 停止 / 计时 / 音量可视化 / 60 秒自动停止。
 */
export class MicrophoneRecorder {
  constructor({ maxSeconds = 60, onTick, onLevel, onStop, onLimit, onError } = {}) {
    this.maxSeconds = maxSeconds;
    this.onTick = onTick;
    this.onLevel = onLevel;
    this.onStop = onStop;
    this.onLimit = onLimit;
    this.onError = onError;

    this.recorder = null;
    this.stream = null;
    this.chunks = [];
    this.startedAt = 0;
    this.timerId = null;
    this.limitTimerId = null;
    this.meterRaf = null;
    this.audioCtx = null;
    this.analyser = null;
  }

  async start() {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error('当前浏览器不支持录音，请使用 Chrome 或 Edge');
    }

    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });

    try {
      const mimeType = pickMimeType();
      const recorder = new MediaRecorder(this.stream, mimeType ? { mimeType } : undefined);
      this.recorder = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) this.chunks.push(event.data);
      };
      recorder.onstop = () => {
        const type = recorder.mimeType || mimeType || 'audio/webm';
        const blob = new Blob(this.chunks, { type });
        this._cleanup();
        this.onStop?.(blob, type);
      };
      recorder.onerror = (event) => {
        this._cleanup();
        this.onError?.(event.error);
      };

      this.startedAt = performance.now();
      recorder.start(250);
      this._startTimer();
      this._startMeter();
    } catch (error) {
      this._cleanup();
      throw error;
    }
  }

  stop() {
    if (this.recorder && this.recorder.state !== 'inactive') {
      this._stopTimer();
      try {
        this.recorder.stop();
      } catch (error) {
        this._cleanup();
        this.onError?.(error);
      }
    }
  }

  _startTimer() {
    this._emitTick(0);
    this.timerId = window.setInterval(() => {
      const elapsed = (performance.now() - this.startedAt) / 1000;
      this._emitTick(elapsed);
    }, 100);
    this.limitTimerId = window.setTimeout(() => {
      this._emitTick(this.maxSeconds);
      this.onLimit?.();
      this.stop();
    }, this.maxSeconds * 1000);
  }

  _stopTimer() {
    if (this.timerId !== null) {
      window.clearInterval(this.timerId);
      this.timerId = null;
    }
    window.clearTimeout(this.limitTimerId);
    this.limitTimerId = null;
  }

  _cleanup() {
    if (this.recorder) {
      this.recorder.ondataavailable = null;
      this.recorder.onstop = null;
      this.recorder.onerror = null;
      this.recorder = null;
    }
    this.chunks = [];
    this._stopTimer();
    this._stopMeter();
    this._releaseStream();
  }

  _emitTick(elapsed) {
    this.onTick?.(Math.min(elapsed, this.maxSeconds));
  }

  _startMeter() {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      this.audioCtx = new AudioCtx();
      this.analyser = this.audioCtx.createAnalyser();
      this.analyser.fftSize = 512;
      this.audioCtx.createMediaStreamSource(this.stream).connect(this.analyser);
      const data = new Uint8Array(this.analyser.fftSize);

      const loop = () => {
        if (!this.analyser) return;
        this.analyser.getByteTimeDomainData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i += 1) {
          const value = (data[i] - 128) / 128;
          sum += value * value;
        }
        const rms = Math.sqrt(sum / data.length);
        this.onLevel?.(Math.min(100, Math.round(rms * 320)));
        this.meterRaf = requestAnimationFrame(loop);
      };
      this.meterRaf = requestAnimationFrame(loop);
    } catch {
      // 音量可视化失败不影响录音主流程
      this._stopMeter();
    }
  }

  _stopMeter() {
    if (this.meterRaf !== null) {
      cancelAnimationFrame(this.meterRaf);
      this.meterRaf = null;
    }
    this.analyser = null;
    if (this.audioCtx) {
      this.audioCtx.close().catch(() => {});
      this.audioCtx = null;
    }
    this.onLevel?.(0);
  }

  _releaseStream() {
    if (this.stream) {
      this.stream.getTracks().forEach((track) => track.stop());
      this.stream = null;
    }
  }
}
