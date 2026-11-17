"""上传音频的格式与大小校验。"""

from pathlib import Path

from app.config import settings


class AudioValidationError(Exception):
    """文件校验失败，携带建议的 HTTP 状态码。"""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def validate_upload(filename: str | None, size: int) -> str:
    """校验上传文件，返回可信的文件后缀名。"""
    safe_name = Path(filename or "").name  # 去掉目录成分，防路径遍历
    suffix = Path(safe_name).suffix.lower()

    if not safe_name or suffix not in settings.allowed_extensions:
        raise AudioValidationError(
            f"不支持的文件格式：{suffix or '(未知)'}，仅支持 WAV/MP3/WEBM/OGG/M4A/FLAC。",
            status_code=400,
        )
    if size <= 0:
        raise AudioValidationError("音频文件为空，请重新上传。", status_code=400)
    if size > settings.max_file_size:
        raise AudioValidationError(
            "File too large. Maximum size is 10MB.", status_code=413
        )
    return suffix
