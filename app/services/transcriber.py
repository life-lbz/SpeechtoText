"""faster-whisper 推理服务：模型懒加载 + 线程安全调用。"""

import logging
import re
import threading
import time

import numpy as np
from opencc import OpenCC

from app.config import settings

logger = logging.getLogger(__name__)

# 中文片段拼接后常带多余空格，去掉汉字之间的空白
_CJK_GAP = re.compile(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])")
_CJK_COMMA = re.compile(r"(?<=[\u4e00-\u9fff]),(?=[\u4e00-\u9fff])")
_TO_SIMPLIFIED = OpenCC("t2s")
_ZH_PROMPT = "以下是简体中文的普通话访谈转写，请使用自然的逗号和句号。"


class ModelNotReadyError(RuntimeError):
    """模型尚未加载完成。"""


class TranscriptionError(RuntimeError):
    """模型推理失败。"""


class Transcriber:
    """单例推理器，CPU 推理串行执行以避免多线程争抢算力。"""

    def __init__(
        self,
        model_size: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
    ):
        self.model_size = model_size or settings.model_size
        self.device = device or settings.device
        self.compute_type = compute_type or settings.compute_type
        self._model = None
        self._load_lock = threading.Lock()
        self._infer_lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        """加载模型（首次会下载权重）。重复调用安全。"""
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            started = time.monotonic()
            from faster_whisper import WhisperModel

            model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
                cpu_threads=settings.cpu_threads,
            )
            self._model = model
            logger.info(
                "model_loaded size=%s device=%s compute_type=%s elapsed=%.1fs",
                self.model_size,
                self.device,
                self.compute_type,
                time.monotonic() - started,
            )

    def transcribe(
        self, audio: np.ndarray, language: str, context: str = "", preview: bool = False
    ) -> str:
        """执行识别，失败重试一次。返回识别文本（可能为空字符串）。"""
        if self._model is None:
            raise ModelNotReadyError("语音识别模型尚未就绪")

        last_error: Exception | None = None
        hints = context.strip().replace(",", "、").replace("，", "、").strip("、。")
        prompt = f"{_ZH_PROMPT}{hints}。" if hints else _ZH_PROMPT
        with self._infer_lock:
            for attempt in (1, 2):
                try:
                    segments, _info = self._model.transcribe(
                        audio,
                        language=language,
                        beam_size=1 if preview else 5,
                        vad_filter=False,
                        condition_on_previous_text=False,
                        initial_prompt=prompt if language == "zh" else context or None,
                    )
                    parts = list(segments)
                    if language == "zh" and not preview:
                        chunks = []
                        for index, segment in enumerate(parts):
                            chunk = segment.text.strip()
                            if (
                                index < len(parts) - 1
                                and hasattr(segment, "end")
                                and chunk
                                and chunk[-1] not in "，。！？；,.!?;"
                            ):
                                chunk += "。" if len(chunk) >= 40 else "，"
                            chunks.append(chunk)
                        text = "".join(chunks).strip()
                        if parts and hasattr(parts[-1], "end") and re.search(r"[\u4e00-\u9fff]$", text):
                            text += "。"
                    else:
                        text = "".join(segment.text for segment in parts).strip()
                    if language == "zh":
                        text = _TO_SIMPLIFIED.convert(text)
                        text = _CJK_COMMA.sub("，", text)
                        text = _CJK_GAP.sub("", text)
                    return text
                except Exception as exc:  # noqa: BLE001 - 统一转业务异常
                    last_error = exc
                    logger.warning("推理第 %s 次失败: %s", attempt, exc)
        raise TranscriptionError(f"模型推理失败：{last_error}")
