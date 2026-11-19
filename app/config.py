"""应用级配置。所有可调参数集中在此，便于测试与环境切换。"""

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
INDEX_FILE = STATIC_DIR / "index.html"


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


@dataclass(frozen=True)
class Settings:
    # ASR 模型参数
    model_size: str = os.getenv("ASR_MODEL_SIZE", "small")
    device: str = os.getenv("ASR_DEVICE", "cpu")
    compute_type: str = os.getenv("ASR_COMPUTE_TYPE", "int8")
    cpu_threads: int = max(1, int(os.getenv("ASR_CPU_THREADS", "4")))
    preload_model: bool = _env_flag("ASR_PRELOAD", True)

    # 上传约束
    max_file_size: int = 10 * 1024 * 1024  # 10MB
    max_duration_seconds: float = 60.0
    recording_tolerance_seconds: float = 0.5  # 容纳浏览器停止录音和编码的少量偏差
    temp_max_age_seconds: int = 300

    # 音频参数
    target_sample_rate: int = 16000
    allowed_extensions: frozenset = frozenset(
        {".wav", ".mp3", ".webm", ".ogg", ".m4a", ".flac"}
    )
    allowed_languages: tuple = ("zh", "en")

    @property
    def max_body_size(self) -> int:
        """multipart 编码有额外开销，请求体上限略大于文件上限。"""
        return self.max_file_size + 2 * 1024 * 1024


settings = Settings()
