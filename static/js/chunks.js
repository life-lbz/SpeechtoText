/** 在约 30 秒附近寻找短暂停顿，返回连续且覆盖全部音频的边界。 */
export function findSpeechCuts(samples, sampleRate) {
  if (!Number.isFinite(sampleRate) || sampleRate <= 0) throw new RangeError('Invalid sample rate');
  const channels = Array.isArray(samples) ? samples : [samples];
  const length = channels[0]?.length || 0;
  const cuts = [0];
  const targetLength = Math.max(1, Math.floor(sampleRate * 30));
  const searchRadius = Math.floor(sampleRate * 4);
  const windowSize = Math.max(1, Math.floor(sampleRate * 0.02));
  // 剩余不足 34 秒时直接作为末段，避免制造极短的尾片段。
  while (cuts.at(-1) + targetLength + searchRadius < length) {
    const start = cuts.at(-1);
    const target = start + targetLength;
    const first = Math.max(start + 1, target - searchRadius);
    const last = Math.min(length - windowSize, target + searchRadius);
    let best = target;
    let lowest = Infinity;
    for (let at = first; at <= last; at += windowSize) {
      let energy = 0;
      for (const channel of channels) {
        for (let i = at; i < at + windowSize; i++) energy += Math.abs(channel[i]);
      }
      energy /= windowSize * channels.length;
      // 静音窗口能量相同时，选最接近目标位置的窗口。
      const middle = at + Math.floor(windowSize / 2);
      if (energy < lowest || (energy === lowest && Math.abs(middle - target) < Math.abs(best - target))) {
        lowest = energy;
        best = middle;
      }
    }
    cuts.push(lowest < 0.02 ? best : target);
  }
  if (length) cuts.push(length);
  return cuts;
}

/** 只合并有限的边界重叠，保留换行，避免吞掉整句重复内容。 */
export function mergeOverlap(previous, next, language = 'zh') {
  const text = next.trim();
  if (!previous) return text;
  if (!text) return previous;
  const limit = Math.min(previous.length, text.length, language === 'en' ? 80 : 20);
  for (let n = limit; n >= 2; n--) {
    const tail = previous.slice(-n);
    const head = text.slice(0, n);
    if (tail !== head) continue;
    if (n === text.length && /[。！？.!?]$/.test(text)) continue;
    if (language === 'en') {
      // 英文必须匹配完整词组，不能把 car + carpet 合并成 carpet。
      const before = previous.at(-(n + 1));
      if ((before && /[\p{L}\p{N}]/u.test(before)) || /[\p{L}\p{N}]/u.test(text[n] || '')) continue;
      if (head.trim().split(/\s+/).length < 2) continue;
    }
    return previous + text.slice(n);
  }
  return `${previous}\n${text}`;
}

/** 在编码每个片段时混合声道，避免复制整段音频。 */
export function wavChunk(buffer, from, to) {
  const frames = to - from;
  const bytes = new ArrayBuffer(44 + frames * 2);
  const view = new DataView(bytes);
  const label = (offset, value) => {
    for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i));
  };
  label(0, 'RIFF'); view.setUint32(4, 36 + frames * 2, true); label(8, 'WAVE');
  label(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, 1, true); view.setUint32(24, buffer.sampleRate, true);
  view.setUint32(28, buffer.sampleRate * 2, true); view.setUint16(32, 2, true);
  view.setUint16(34, 16, true); label(36, 'data'); view.setUint32(40, frames * 2, true);
  const channels = Array.from({ length: buffer.numberOfChannels }, (_, i) => buffer.getChannelData(i));
  for (let i = 0; i < frames; i++) {
    let value = 0;
    for (const channel of channels) value += channel[from + i] / channels.length;
    value = Math.max(-1, Math.min(1, value));
    view.setInt16(44 + i * 2, Math.round(value * (value < 0 ? 32768 : 32767)), true);
  }
  return new Blob([bytes], { type: 'audio/wav' });
}
