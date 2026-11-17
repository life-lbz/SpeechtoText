export const MAX_FILE_SIZE = 10 * 1024 * 1024;
export const ALLOWED_EXTENSIONS = ['wav', 'mp3', 'webm', 'ogg', 'm4a', 'flac'];

const STATUS_MESSAGES = {
  400: '音频文件格式不支持或已损坏，请重新选择',
  413: '文件超过 10MB 限制，请上传更小的音频',
  422: '语言参数异常，请刷新页面后重试',
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
  if (file.size > MAX_FILE_SIZE) return '文件超过 10MB 限制，请上传更小的音频';
  return '';
}

/** 上传音频并等待识别结果。 */
export async function transcribeAudio(blob, filename, language) {
  const form = new FormData();
  form.append('file', blob, filename);
  form.append('language', language);

  let response;
  try {
    response = await fetch('/api/transcribe', { method: 'POST', body: form });
  } catch {
    throw new TranscriptionRequestError('无法连接到识别服务，请确认后端已启动');
  }

  let payload = null;
  try {
    payload = await response.json();
  } catch {
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

  return payload;
}
