"""faster-whisper 推理服务：模型懒加载 + 线程安全调用。"""

import logging
import re
import threading
import time

import numpy as np
from opencc import OpenCC

from app.config import MODELS_DIR, settings
from app.services.paraformer import ParaformerModel

logger = logging.getLogger(__name__)

# 中文片段拼接后常带多余空格，去掉汉字之间的空白
_CJK_GAP = re.compile(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])")
_GPU_RETRY_SECONDS = 60
_CUDA_ERROR = re.compile(r"cuda|cublas|cudnn|cufft|out of memory", re.IGNORECASE)


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
        *,
        cpu_paraformer_path: str | None = None,
        gpu_model_size: str | None = None,
        gpu_model_path: str | None = None,
    ):
        self.model_size = model_size or settings.model_size
        self.cpu_paraformer_path = (
            settings.cpu_paraformer_path if cpu_paraformer_path is None else cpu_paraformer_path
        )
        self.gpu_model_size = gpu_model_size or settings.gpu_model_size
        self.gpu_model_path = settings.gpu_model_path if gpu_model_path is None else gpu_model_path
        self.device = device or settings.device
        self.compute_type = compute_type or settings.compute_type
        self._model = None
        self._simplify_chinese = OpenCC("t2s")
        self._load_lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self._active_device = None
        self._using_paraformer = False
        self._paraformer_failed = False
        self._probe_thread = None
        self._next_probe = 0.0
        self._acceleration = {}

    @property
    def ready(self) -> bool:
        return self._model is not None

    @property
    def acceleration_status(self) -> dict:
        return self._acceleration

    def _create_model(self, model_size_or_path: str, device: str, compute_type: str):
        from faster_whisper import WhisperModel

        started = time.monotonic()
        source = model_size_or_path
        if re.fullmatch(r"[\w.-]+", model_size_or_path):
            bundled = MODELS_DIR / f"faster-whisper-{model_size_or_path}"
            if (bundled / "model.bin").is_file():
                source = str(bundled)
        model = WhisperModel(source, device=device, compute_type=compute_type)
        logger.info(
            "model_loaded size=%s device=%s compute_type=%s elapsed=%.1fs",
            source, device, compute_type, time.monotonic() - started,
        )
        return model

    def _wants_paraformer(self, language: str) -> bool:
        return bool(self.cpu_paraformer_path) and language == "zh" and not self._paraformer_failed

    def _load_cpu_model(self, language: str, compute_type: str) -> None:
        model = None
        if self._wants_paraformer(language):
            try:
                model = ParaformerModel(self.cpu_paraformer_path)
            except Exception as exc:
                self._paraformer_failed = True
                logger.warning("FunASR 加载失败，使用 Whisper CPU: %s", exc)

        if model is None:
            self._model = self._create_model(self.model_size, "cpu", compute_type)
            model_name = self.model_size
        else:
            self._model = model
            model_name = "funasr-paraformer"
            logger.info("model_loaded size=%s device=cpu compute_type=int8", model_name)
        self._using_paraformer = model is not None
        self._active_device = "cpu"
        self._acceleration = {**self._acceleration, "device": "cpu", "model": model_name}

    def load(self) -> None:
        """加载模型（首次会下载权重）。重复调用安全。"""
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            device = "cpu" if self.device == "auto" else self.device
            compute_type = "int8" if self.device == "auto" else self.compute_type
            with self._infer_lock:
                if device == "cpu":
                    self._load_cpu_model("zh", compute_type)
                else:
                    self._model = self._create_model(self.model_size, device, compute_type)
                    self._active_device = device
                    self._acceleration = {"device": device, "model": self.model_size}
                if self.device == "auto":
                    self._start_gpu_probe()

    def _start_gpu_probe(self) -> None:
        """调用方持有推理锁，确保只有一个后台探测任务。"""
        if self._probe_thread is not None or time.monotonic() < self._next_probe:
            return
        self._acceleration = {
            "device": "cpu", "model": self._acceleration["model"], "gpu_status": "probing",
        }
        self._probe_thread = threading.Thread(target=self._probe_gpu, daemon=True)
        self._probe_thread.start()

    def _probe_gpu(self) -> None:
        try:
            from ctranslate2 import get_cuda_device_count

            if get_cuda_device_count() == 0:
                raise RuntimeError("未检测到 CUDA GPU")
            model = self._create_model(
                self.gpu_model_path or self.gpu_model_size, "cuda", "int8_float16",
            )
            # 关闭 VAD 并消费生成器，让探测覆盖真正的编码和解码。
            audio = np.zeros(settings.target_sample_rate, dtype=np.float32)
            segments, _ = model.transcribe(audio, language="en", beam_size=1, vad_filter=False)
            for _ in segments:
                pass
        except Exception as exc:
            with self._infer_lock:
                self._report_gpu_failure(str(exc))
                self._probe_thread = None
            return

        with self._infer_lock:
            self._model = model
            self._active_device = "cuda"
            self._using_paraformer = False
            self._acceleration = {
                "device": "cuda", "model": self.gpu_model_size, "gpu_status": "active",
            }
            self._probe_thread = None
            logger.info("GPU 验证通过，后续请求使用 CUDA")

    def _report_gpu_failure(self, reason: str) -> None:
        self._next_probe = time.monotonic() + _GPU_RETRY_SECONDS
        self._acceleration = {
            **self._acceleration,
            "gpu_status": "unavailable", "gpu_error": reason,
        }
        logger.warning("GPU 加速不可用: %s", reason)

    def transcribe(self, audio: np.ndarray, language: str, *, preview: bool = False) -> str:
        """执行识别，失败重试一次。返回识别文本（可能为空字符串）。"""
        if self._model is None:
            raise ModelNotReadyError("语音识别模型尚未就绪")

        last_error = ""
        with self._infer_lock:
            cpu_compute_type = "int8" if self.device == "auto" else self.compute_type
            if self._active_device == "cpu" and self._using_paraformer != self._wants_paraformer(language):
                try:
                    self._load_cpu_model(language, cpu_compute_type)
                except Exception as exc:
                    raise TranscriptionError(f"CPU 模型切换失败：{exc}") from exc
            if self.device == "auto" and self._active_device == "cpu":
                self._start_gpu_probe()
            attempt = 0
            while attempt < 2:
                attempt += 1
                try:
                    if self._using_paraformer:
                        text = self._model.transcribe(audio).strip()
                    else:
                        segments, _info = self._model.transcribe(
                            audio,
                            language=language,
                            beam_size=5 if language == "zh" and not preview else 1,
                            vad_filter=True,
                        )
                        text = "".join(segment.text for segment in segments).strip()
                    if language == "zh":
                        return self._simplify_chinese.convert(_CJK_GAP.sub("", text))
                    return text
                except Exception as exc:  # noqa: BLE001 - 统一转业务异常
                    last_error = str(exc)
                    logger.warning("推理第 %s 次失败: %s", attempt, exc)
                if (
                    self.device == "auto" and self._active_device == "cuda"
                    and _CUDA_ERROR.search(last_error)
                ):
                    try:
                        self._load_cpu_model(language, "int8")
                    except Exception as exc:
                        raise TranscriptionError(f"CPU 回退加载失败：{exc}") from exc
                    self._report_gpu_failure(last_error)
                    attempt = 1
                elif self._using_paraformer:
                    self._paraformer_failed = True
                    try:
                        self._load_cpu_model(language, cpu_compute_type)
                    except Exception as exc:
                        raise TranscriptionError(f"CPU 回退加载失败：{exc}") from exc
                    attempt = 1
        raise TranscriptionError(f"模型推理失败：{last_error}")
