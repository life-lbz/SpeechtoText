"""应用级配置。所有可调参数集中在此，便于测试与环境切换。"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _register_cuda_dlls() -> None:
    """Windows 下把 pip 安装的 NVIDIA 运行时 DLL 加入搜索路径。

    ctranslate2 通过 LoadLibrary 加载 cuBLAS / cuDNN，默认找不到
    nvidia-*-cu12 放在 site-packages 里的二进制目录，需要显式注册。
    """
    if os.name != "nt":
        return
    nvidia_dir = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    if not nvidia_dir.is_dir():
        return
    handles = []
    paths = []
    for component in sorted(nvidia_dir.iterdir()):
        bin_dir = component / "bin"
        if not bin_dir.is_dir():
            continue
        paths.append(str(bin_dir))
        try:
            handles.append(os.add_dll_directory(str(bin_dir)))
        except OSError:
            pass
    if paths:
        os.environ["PATH"] = os.pathsep.join(paths + [os.environ.get("PATH", "")])
        _DLL_HANDLES.extend(handles)


_DLL_HANDLES: list = []
_register_cuda_dlls()
STATIC_DIR = BASE_DIR / "static"
INDEX_FILE = STATIC_DIR / "index.html"
MODELS_DIR = BASE_DIR / "models"
PARAFORMER_DIR = MODELS_DIR / "funasr-paraformer"


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


@dataclass(frozen=True)
class Settings:
    # ASR 模型参数
    model_size: str = os.getenv("ASR_MODEL_SIZE", "base")
    cpu_paraformer_path: str | None = os.getenv(
        "ASR_CPU_PARAFORMER_PATH",
        str(PARAFORMER_DIR) if (PARAFORMER_DIR / "model_quant.onnx").is_file() else None,
    )
    gpu_model_size: str = os.getenv("ASR_GPU_MODEL_SIZE", "large-v3-turbo")
    gpu_model_path: str | None = os.getenv("ASR_GPU_MODEL_PATH")
    device: str = os.getenv("ASR_DEVICE", "auto")
    compute_type: str = os.getenv("ASR_COMPUTE_TYPE", "int8")
    preload_model: bool = _env_flag("ASR_PRELOAD", True)

    # 上传约束
    max_file_size: int = 10 * 1024 * 1024  # 10MB
    max_duration_seconds: float = 60.0
    recording_tolerance_seconds: float = 0.5  # 容纳浏览器停止录音和编码的少量偏差

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
