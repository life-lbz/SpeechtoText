export class Toast {
  constructor(container) {
    this.container = container;
  }

  show(message, type = 'info', duration = 4000) {
    const node = document.createElement('div');
    node.className = `toast is-${type}`;
    node.textContent = message;
    this.container.appendChild(node);

    window.setTimeout(() => {
      node.classList.add('is-leaving');
      window.setTimeout(() => node.remove(), 220);
    }, duration);
  }
}

export class ResultRenderer {
  constructor(elements) {
    this.els = elements;
  }

  render(result) {
    const { els } = this;
    els.resultPlaceholder.hidden = true;
    els.resultMeta.hidden = false;
    els.metaLang.textContent = result.language === 'en' ? 'English' : '中文';
    els.metaDuration.textContent = `${Number(result.duration_seconds).toFixed(1)} 秒`;
    els.metaProcessing.textContent = `${Number(result.processing_seconds).toFixed(2)} 秒`;

    if (result.text) {
      els.resultText.hidden = false;
      els.resultText.textContent = result.text;
      els.copyBtn.disabled = false;
    } else {
      els.resultText.hidden = true;
      els.resultPlaceholder.hidden = false;
      els.resultPlaceholder.textContent = '未检测到有效语音，请尝试更清晰的音频';
      els.copyBtn.disabled = true;
    }
    els.clearBtn.disabled = false;
  }

  renderPreview(text) {
    const { els } = this;
    els.resultPlaceholder.hidden = true;
    els.resultText.hidden = false;
    els.resultText.textContent = text;
    els.copyBtn.disabled = false;
  }

  keepPreview() {
    if (!this.els.resultText.textContent) {
      this.clear();
      return;
    }
    this.els.clearBtn.disabled = false;
  }

  clear() {
    const { els } = this;
    els.resultText.hidden = true;
    els.resultText.textContent = '';
    els.resultPlaceholder.hidden = false;
    els.resultPlaceholder.textContent = '识别出的文字会显示在这里';
    els.resultMeta.hidden = true;
    els.metaLang.textContent = '--';
    els.metaDuration.textContent = '--';
    els.metaProcessing.textContent = '--';
    els.copyBtn.disabled = true;
    els.clearBtn.disabled = true;
  }
}

export function formatClock(seconds) {
  const total = Math.max(0, Math.floor(seconds));
  const minutes = String(Math.floor(total / 60)).padStart(2, '0');
  const rest = String(total % 60).padStart(2, '0');
  return `${minutes}:${rest}`;
}

export function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}
