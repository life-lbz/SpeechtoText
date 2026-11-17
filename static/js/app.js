import { MicrophoneRecorder, mimeToExtension } from './recorder.js';
import { transcribeAudio, validateFile } from './uploader.js';
import { ResultRenderer, Toast, formatClock, formatSize } from './display.js';

const $ = (id) => document.getElementById(id);
const RECORDING_TIP = '正在实时识别，再次点击生成最终结果';
const PREVIEW_ERROR_TIP = '实时转写暂时不可用，停止后仍会尝试识别整段录音';

const els = {
  statusBadge: $('statusBadge'),
  statusText: $('statusText'),
  recordBtn: $('recordBtn'),
  timer: $('timer'),
  levelFill: $('levelFill'),
  recordTip: $('recordTip'),
  dropzone: $('dropzone'),
  fileInput: $('fileInput'),
  fileRow: $('fileRow'),
  fileName: $('fileName'),
  fileSize: $('fileSize'),
  uploadBtn: $('uploadBtn'),
  clearFileBtn: $('clearFileBtn'),
  resultText: $('resultText'),
  resultPlaceholder: $('resultPlaceholder'),
  resultMeta: $('resultMeta'),
  metaLang: $('metaLang'),
  metaDuration: $('metaDuration'),
  metaProcessing: $('metaProcessing'),
  copyBtn: $('copyBtn'),
  clearBtn: $('clearBtn'),
};

const state = {
  language: 'zh',
  busy: false,
  recording: false,
  requestingMicrophone: false,
  selectedFile: null,
};

let serviceStatus = 'initializing';
let preview = null;
const toast = new Toast($('toastStack'));
const renderer = new ResultRenderer(els);

/* ---------------- 状态与界面 ---------------- */

function setBadge(kind, text) {
  els.statusBadge.dataset.state = kind;
  els.statusText.textContent = text;
}

function updateStatus() {
  if (state.busy) return setBadge('busy', '识别中');
  if (state.recording) return setBadge('busy', '录音中');
  if (state.requestingMicrophone) return setBadge('loading', '等待麦克风授权');
  if (serviceStatus === 'initializing') return setBadge('loading', '模型加载中');
  if (serviceStatus === 'standby') return setBadge('loading', '模型将在首次识别时加载');
  if (serviceStatus !== 'ok') return setBadge('error', '模型不可用');
  return setBadge('ready', '服务就绪');
}

function inputLocked() {
  return state.busy || state.recording || state.requestingMicrophone;
}

function refreshControls() {
  const locked = inputLocked();
  els.recordBtn.disabled = state.busy || state.requestingMicrophone;
  els.uploadBtn.disabled = locked || !state.selectedFile;
  els.clearFileBtn.disabled = locked;
  els.fileInput.disabled = locked;
  document.querySelectorAll('.lang-btn').forEach((btn) => {
    btn.disabled = locked;
  });
}

function setRecordingUI(active) {
  state.recording = active;
  els.recordBtn.classList.toggle('is-recording', active);
  els.recordBtn.setAttribute('aria-label', active ? '停止录音' : '开始录音');
  els.recordTip.textContent = active
    ? (preview?.captureFailed ? PREVIEW_ERROR_TIP : RECORDING_TIP)
    : '点击麦克风，录音时下方会陆续显示文字';
  if (!active) els.levelFill.style.width = '0%';
  updateStatus();
  refreshControls();
}

function setBusy(busy) {
  state.busy = busy;
  updateStatus();
  refreshControls();
}

/* ---------------- 识别主流程 ---------------- */

async function recognize(blob, filename, fromRecording = false) {
  setBusy(true);
  try {
    const result = await transcribeAudio(blob, filename, state.language, { recording: fromRecording });
    renderer.render(result);
    if (result.text) {
      toast.show('识别完成', 'success', 2500);
    } else {
      toast.show('未检测到有效语音，请尝试更清晰的音频', 'warn', 5000);
    }
  } catch (error) {
    if (fromRecording) renderer.keepPreview();
    toast.show(error?.message || '识别失败，请重试', 'error', 6000);
  } finally {
    setBusy(false);
    if (serviceStatus !== 'ok') checkHealth();
  }
}

/* ---------------- 录音 ---------------- */

async function transcribePreviewChunk(blob) {
  const session = preview;
  if (!session) return;
  session.chunks.push(blob);
  if (session.processing) return;

  session.processing = true;
  const separator = session.language === 'en' ? ' ' : '';
  while (preview === session && session.chunks.length) {
    try {
      const result = await transcribeAudio(
        session.chunks.shift(), 'preview.wav', session.language,
        { signal: session.controller.signal, preview: true },
      );
      if (preview !== session) return;
      if (result.text) {
        session.text = session.text ? session.text + separator + result.text : result.text;
        renderer.renderPreview(session.text);
      }
      if (!session.captureFailed) els.recordTip.textContent = RECORDING_TIP;
    } catch {
      if (preview === session) els.recordTip.textContent = PREVIEW_ERROR_TIP;
    }
  }
  session.processing = false;
}

function stopPreview() {
  const session = preview;
  preview = null;
  if (session) {
    session.chunks.length = 0;
    session.controller.abort();
  }
}

const recorder = new MicrophoneRecorder({
  maxSeconds: 60,
  onChunk: transcribePreviewChunk,
  onPreviewError: () => {
    if (!preview) return;
    preview.captureFailed = true;
    els.recordTip.textContent = PREVIEW_ERROR_TIP;
  },
  onTick: (elapsed) => {
    els.timer.textContent = formatClock(elapsed);
  },
  onLevel: (level) => {
    els.levelFill.style.width = `${level}%`;
  },
  onLimit: () => {
    stopPreview();
    toast.show('录音已达 60 秒上限，已自动停止', 'warn', 5000);
  },
  onError: (error) => {
    stopPreview();
    setRecordingUI(false);
    els.timer.textContent = formatClock(0);
    renderer.keepPreview();
    toast.show(error?.message || '录音中断，请检查麦克风后重试', 'error', 6000);
  },
  onStop: (blob, type) => {
    stopPreview();
    setRecordingUI(false);
    els.timer.textContent = formatClock(0);
    if (!blob || blob.size === 0) {
      renderer.keepPreview();
      toast.show('没有采集到音频，请重试', 'error');
      return;
    }
    recognize(blob, `recording.${mimeToExtension(type)}`, true);
  },
});

els.recordBtn.addEventListener('click', async () => {
  if (state.busy || state.requestingMicrophone) return;
  if (state.recording) {
    stopPreview();
    recorder.stop();
    return;
  }
  state.requestingMicrophone = true;
  updateStatus();
  refreshControls();
  try {
    preview = {
      language: state.language, chunks: [], text: '', controller: new AbortController(),
      processing: false, captureFailed: false,
    };
    await recorder.start();
    renderer.clear();
    setRecordingUI(true);
  } catch (error) {
    stopPreview();
    const messages = {
      NotAllowedError: '麦克风权限被拒绝，请在浏览器地址栏重新授权',
      PermissionDeniedError: '麦克风权限被拒绝，请在浏览器地址栏重新授权',
      NotFoundError: '未检测到麦克风设备，请检查设备连接',
      NotReadableError: '麦克风被其他程序占用，请关闭后重试',
    };
    toast.show(messages[error?.name] || error?.message || '无法启动录音', 'error', 6000);
  } finally {
    state.requestingMicrophone = false;
    updateStatus();
    refreshControls();
  }
});

/* ---------------- 文件上传 ---------------- */

function setSelectedFile(file) {
  const problem = validateFile(file);
  if (problem) {
    clearSelectedFile();
    toast.show(problem, 'error', 5000);
    return;
  }
  state.selectedFile = file;
  els.fileName.textContent = file.name;
  els.fileSize.textContent = formatSize(file.size);
  els.fileRow.hidden = false;
  refreshControls();
}

function clearSelectedFile() {
  state.selectedFile = null;
  els.fileInput.value = '';
  els.fileRow.hidden = true;
  els.fileName.textContent = '';
  els.fileSize.textContent = '';
  refreshControls();
}

// dropzone 是 label，点击会原生触发 fileInput；这里只补充键盘访问
els.dropzone.addEventListener('keydown', (event) => {
  if ((event.key === 'Enter' || event.key === ' ') && !inputLocked()) {
    event.preventDefault();
    els.fileInput.click();
  }
});

els.fileInput.addEventListener('change', (event) => {
  if (inputLocked()) return;
  const file = event.target.files?.[0];
  if (file) setSelectedFile(file);
});

['dragenter', 'dragover'].forEach((name) => {
  els.dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    if (!inputLocked()) els.dropzone.classList.add('is-dragover');
  });
});

['dragleave', 'drop'].forEach((name) => {
  els.dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    els.dropzone.classList.remove('is-dragover');
  });
});

els.dropzone.addEventListener('drop', (event) => {
  if (inputLocked()) return;
  const file = event.dataTransfer?.files?.[0];
  if (file) setSelectedFile(file);
});

els.clearFileBtn.addEventListener('click', clearSelectedFile);

els.uploadBtn.addEventListener('click', () => {
  if (!state.selectedFile || inputLocked()) return;
  recognize(state.selectedFile, state.selectedFile.name);
});

/* ---------------- 语言切换 ---------------- */

document.querySelectorAll('.lang-btn').forEach((button) => {
  button.addEventListener('click', () => {
    state.language = button.dataset.lang;
    document.querySelectorAll('.lang-btn').forEach((item) => {
      item.classList.toggle('is-active', item === button);
    });
  });
});

/* ---------------- 结果操作 ---------------- */

els.copyBtn.addEventListener('click', async () => {
  const text = els.resultText.textContent || '';
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    toast.show('已复制到剪贴板', 'success', 2200);
  } catch {
    toast.show('复制失败，请手动选择文本复制', 'error');
  }
});

els.clearBtn.addEventListener('click', () => renderer.clear());

/* ---------------- 健康检查 ---------------- */

async function checkHealth() {
  try {
    const response = await fetch('/health', { cache: 'no-store' });
    const data = await response.json();
    serviceStatus = data.status;
    updateStatus();
    if (data.status === 'ok') {
      updateFootnote(data);
    } else if (data.status === 'initializing') {
      setTimeout(checkHealth, 3000);
    }
  } catch {
    serviceStatus = 'unhealthy';
    updateStatus();
    toast.show('无法连接后端服务，请确认 uvicorn 已启动', 'error', 6000);
  }
}

function updateFootnote(data) {
  const footer = document.getElementById('footnote');
  if (!footer) return;
  const engine = data.device === 'cuda'
    ? `faster-whisper ${data.model} · CUDA 加速`
    : 'FunASR Paraformer（中文）+ faster-whisper（英文）· CPU INT8';
  footer.textContent = `FastAPI · ${engine} · 模型加载完成后可断网运行`;
}

refreshControls();
updateStatus();
checkHealth();
