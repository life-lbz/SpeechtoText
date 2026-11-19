"""上传音频的临时文件管理：写入即用，用完即删。"""

import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

TEMP_PREFIX = "asr_"


@contextmanager
def temporary_audio_file(content: bytes, suffix: str):
    """把上传内容写入系统临时目录，退出上下文时删除。"""
    fd, path = tempfile.mkstemp(suffix=suffix, prefix=TEMP_PREFIX)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        yield Path(path)
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def cleanup_stale_files(max_age_seconds: int = 300) -> int:
    """启动时清理上次异常退出遗留的临时音频，返回清理数量。"""
    removed = 0
    temp_dir = Path(tempfile.gettempdir())
    deadline = time.time() - max_age_seconds
    for path in temp_dir.glob(f"{TEMP_PREFIX}*"):
        try:
            if path.is_file() and path.stat().st_mtime < deadline:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed
