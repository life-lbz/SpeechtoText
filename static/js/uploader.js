import { findSpeechCuts, mergeOverlap, wavChunk } from './chunks.js';

/** @typedef {{text: string, language: 'zh'|'en', duration_seconds: number, processing_seconds: number}} TranscriptionResult */
/** @typedef {{signal?: AbortSignal, context?: string, preview?: boolean, recording?: boolean}} RequestOptions */
/** @typedef {{message: string, completed: number, total: number}} UploadProgress */
/** @typedef {{signal?: AbortSignal, context?: string, onProgress?: (value: UploadProgress) => void, onPartial?: (value: TranscriptionResult) => void}} UploadOptions */

export const MAX_FILE_SIZE = 10 * 1024 * 1024;
export const MAX_UPLOAD_SIZE = 100 * 1024 * 1024;
export const ALLOWED_EXTENSIONS = ['wav', 'mp3', 'webm', 'ogg', 'm4a', 'flac'];

const STATUS_MESSAGES = {
  400: '音频文件格式不支持或已损坏，请重新选择',
  413: '文件超过 10MB 限制，请上传更小的音频',
  422: '请检查语言和专业词提示（最多 200 字）',
  500: '识别服务暂时不可用，请稍后重试',
  503: '语音识别模型尚未就绪，请稍候再试',
};

export class TranscriptionRequestError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = 'TranscriptionRequestError';
    this.status = status;
  }
}

/** 前端预校验，返回空字符串表示通过。 */
export function validateFile(file) {
  if (!file) return '请选择音频文件';
  const extension = file.name.split('.').pop()?.toLowerCase() ?? '';
  if (!ALLOWED_EXTENSIONS.includes(extension)) {
    return `不支持的文件格式 .${extension || '未知'}，请选择 WAV/MP3/WEBM/OGG/M4A/FLAC`;
  }
  if (file.size === 0) return '音频文件为空，请重新选择';
  if (file.size > MAX_UPLOAD_SIZE) return '文件超过 100MB 限制，请先裁剪或压缩音频';
  return '';
}

/** 上传音频并等待识别结果。
 * @param {Blob} blob
 * @param {string} filename
 * @param {'zh'|'en'} language
 * @param {RequestOptions} [options]
 * @returns {Promise<TranscriptionResult>}
 */
export async function transcribeAudio(
  blob, filename, language, { signal, context = '', preview = false, recording = false } = {},
) {
  signal?.throwIfAborted();
  const form = new FormData();
  form.append('file', blob, filename);
  form.append('language', language);
  if (context.trim()) form.append('context', context.trim());
  if (preview) form.append('preview', 'true');
  if (recording) form.append('recording', 'true');

  let response;
  try {
    response = await fetch('/api/transcribe', { method: 'POST', body: form, signal });
  } catch (error) {
    signal?.throwIfAborted();
    if (error?.name === 'AbortError') throw error;
    throw new TranscriptionRequestError('无法连接到识别服务，请确认后端已启动');
  }

  let payload = null;
  try {
    payload = await response.json();
  } catch (error) {
    signal?.throwIfAborted();
    payload = null;
  }

  if (!response.ok) {
    const detail = payload?.detail;
    let message = STATUS_MESSAGES[response.status] || '识别失败，请重试';
    if ([400, 503].includes(response.status) && typeof detail === 'string' && detail) {
      message = detail;
    }
    throw new TranscriptionRequestError(message, response.status);
  }

  if (!payload || typeof payload.text !== 'string'
      || !Number.isFinite(payload.duration_seconds) || !Number.isFinite(payload.processing_seconds)) {
    throw new TranscriptionRequestError('识别服务返回了无效结果，请重试');
  }
  return payload;
}

/** 长音频在本机解码后逐段提交，浏览器不支持的小文件交给后端。
 * @param {File} file
 * @param {'zh'|'en'} language
 * @param {UploadOptions} [options]
 * @returns {Promise<TranscriptionResult>}
 */
export async function transcribeFile(file, language, {
  signal, context = '', onProgress = () => {}, onPartial = () => {},
} = {}) {
  const problem = validateFile(file);
  if (problem) throw new TranscriptionRequestError(problem);
  signal?.throwIfAborted();
  const direct = async () => {
    onProgress({ message: '正在识别音频', completed: 0, total: 1 });
    const result = await transcribeAudio(file, file.name, language, { signal, context });
    onProgress({ message: '识别完成', completed: 1, total: 1 });
    return result;
  };

  onProgress({ message: '正在本机解码长音频', completed: 0, total: 0 });
  const AudioContextClass = globalThis.AudioContext || globalThis.webkitAudioContext;
  if (!AudioContextClass) {
    if (file.size <= MAX_FILE_SIZE) return direct();
    throw new TranscriptionRequestError('此浏览器不支持长音频解码，请使用 Chrome 或 Edge');
  }
  let audioContext;
  let buffer;
  try {
    audioContext = new AudioContextClass({ sampleRate: 16000 });
    const bytes = await file.arrayBuffer();
    signal?.throwIfAborted();
    buffer = await audioContext.decodeAudioData(bytes);
    signal?.throwIfAborted();
  } catch (error) {
    signal?.throwIfAborted();
    if (file.size <= MAX_FILE_SIZE) return direct();
    throw new TranscriptionRequestError('浏览器无法解码此长音频，请转换为 WAV 或 MP3 后重试');
  } finally {
    if (audioContext) await audioContext.close();
  }
  if (!buffer.length) throw new TranscriptionRequestError('音频文件为空或已损坏');
  signal?.throwIfAborted();
  if (buffer.duration <= 60 && file.size <= MAX_FILE_SIZE) return direct();
  const channels = Array.from({ length: buffer.numberOfChannels }, (_, i) => buffer.getChannelData(i));
  const cuts = findSpeechCuts(channels, buffer.sampleRate);
  const total = cuts.length - 1;
  const result = { text: '', language, duration_seconds: buffer.duration, processing_seconds: 0 };
  for (let i = 0; i < total; i++) {
    signal?.throwIfAborted();
    onProgress({ message: `正在识别第 ${i + 1} / ${total} 段`, completed: i, total });
    const from = i === 0 ? 0 : Math.max(0, cuts[i] - Math.floor(buffer.sampleRate));
    const blob = wavChunk(buffer, from, cuts[i + 1]);
    if (blob.size > MAX_FILE_SIZE) throw new TranscriptionRequestError('分段音频超过 10MB，请转换为 16kHz WAV 后重试');
    const part = await transcribeAudio(blob, `part-${i + 1}.wav`, language, { signal, context });
    signal?.throwIfAborted();
    result.text = mergeOverlap(result.text, part.text, language);
    result.processing_seconds = Math.round((result.processing_seconds + part.processing_seconds) * 100) / 100;
    onPartial({ ...result });
    onProgress({ message: `已完成 ${i + 1} / ${total} 段`, completed: i + 1, total });
  }
  return result;
}
