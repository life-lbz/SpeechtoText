import { MicrophoneRecorder, mimeToExtension } from './recorder.js';
import { transcribeAudio, validateFile } from './uploader.js';
import { ResultRenderer, Toast, formatClock, formatSize } from './display.js';

const $ = (id) => document.getElementById(id);

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
  selectedFile: null,
};

const service = { ready: false, loading: true };
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
  if (service.loading) return setBadge('loading', '模型加载中');
  if (!service.ready) return setBadge('error', '模型不可用');
  return setBadge('ready', '服务就绪');
}

function refreshControls() {
  els.recordBtn.disabled = state.busy;
  els.uploadBtn.disabled = state.busy || !state.selectedFile;
  els.clearFileBtn.disabled = state.busy;
  document.querySelectorAll('.lang-btn').forEach((btn) => {
    btn.disabled = state.busy || state.recording;
  });
  els.dropzone.style.pointerEvents = state.busy ? 'none' : '';
}

function setRecordingUI(active) {
  state.recording = active;
  els.recordBtn.classList.toggle('is-recording', active);
  els.recordBtn.setAttribute('aria-label', active ? '停止录音' : '开始录音');
  els.recordTip.textContent = active
    ? '正在录音，再次点击停止并自动识别'
    : '点击麦克风开始录音，停止后自动识别';
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

async function recognize(blob, filename) {
  setBusy(true);
  try {
    const result = await transcribeAudio(blob, filename, state.language);
    renderer.render(result);
    if (result.text) {
      toast.show('识别完成', 'success', 2500);
    } else {
      toast.show('未检测到有效语音，请尝试更清晰的音频', 'warn', 5000);
    }
  } catch (error) {
    toast.show(error?.message || '识别失败，请重试', 'error', 6000);
  } finally {
    setBusy(false);
  }
}

/* ---------------- 录音 ---------------- */

const recorder = new MicrophoneRecorder({
  maxSeconds: 60,
  onTick: (elapsed) => {
    els.timer.textContent = formatClock(elapsed);
  },
  onLevel: (level) => {
    els.levelFill.style.width = `${level}%`;
  },
  onLimit: () => {
    toast.show('录音已达 60 秒上限，已自动停止', 'warn', 5000);
  },
  onStop: (blob, type) => {
    setRecordingUI(false);
    els.timer.textContent = formatClock(0);
    if (!blob || blob.size === 0) {
      toast.show('没有采集到音频，请重试', 'error');
      return;
    }
    recognize(blob, `recording.${mimeToExtension(type)}`);
  },
});

els.recordBtn.addEventListener('click', async () => {
  if (state.busy) return;
  if (state.recording) {
    recorder.stop();
    return;
  }
  try {
    await recorder.start();
    setRecordingUI(true);
  } catch (error) {
    const messages = {
      NotAllowedError: '麦克风权限被拒绝，请在浏览器地址栏重新授权',
      PermissionDeniedError: '麦克风权限被拒绝，请在浏览器地址栏重新授权',
      NotFoundError: '未检测到麦克风设备，请检查设备连接',
      NotReadableError: '麦克风被其他程序占用，请关闭后重试',
    };
    toast.show(messages[error?.name] || error?.message || '无法启动录音', 'error', 6000);
  }
});

/* ---------------- 文件上传 ---------------- */

function setSelectedFile(file) {
  const problem = validateFile(file);
  if (problem) {
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
  if ((event.key === 'Enter' || event.key === ' ') && !state.busy) {
    event.preventDefault();
    els.fileInput.click();
  }
});

els.fileInput.addEventListener('change', (event) => {
  const file = event.target.files?.[0];
  if (file) setSelectedFile(file);
});

['dragenter', 'dragover'].forEach((name) => {
  els.dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    els.dropzone.classList.add('is-dragover');
  });
});

['dragleave', 'drop'].forEach((name) => {
  els.dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    els.dropzone.classList.remove('is-dragover');
  });
});

els.dropzone.addEventListener('drop', (event) => {
  if (state.busy) return;
  const file = event.dataTransfer?.files?.[0];
  if (file) setSelectedFile(file);
});

els.clearFileBtn.addEventListener('click', clearSelectedFile);

els.uploadBtn.addEventListener('click', () => {
  if (!state.selectedFile || state.busy) return;
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
    service.ready = Boolean(data.model_ready);
    service.loading = data.status === 'initializing';
    updateStatus();
    if (!service.ready && service.loading) {
      window.setTimeout(checkHealth, 2000);
    }
  } catch {
    service.ready = false;
    service.loading = false;
    updateStatus();
    toast.show('无法连接后端服务，请确认 uvicorn 已启动', 'error', 6000);
  }
}

refreshControls();
updateStatus();
checkHealth();
