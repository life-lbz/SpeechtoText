"""测试辅助：构造真实可解码的 WAV 数据。"""

import io
import wave

import numpy as np


def make_wav_bytes(
    seconds: float = 1.0,
    sample_rate: int = 16000,
    channels: int = 1,
    sample_width: int = 2,
    frequency: float = 440.0,
) -> bytes:
    frames = int(seconds * sample_rate)
    timeline = np.linspace(0, seconds, frames, endpoint=False)
    tone = 0.2 * np.sin(2 * np.pi * frequency * timeline)

    if sample_width == 2:
        data = (tone * 32767).astype("<i2")
    else:  # 仅用于非 16bit 的边界用例
        data = (tone * 127 + 128).astype(np.uint8)

    if channels > 1:
        data = np.repeat(data, channels)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(sample_width)
        writer.setframerate(sample_rate)
        writer.writeframes(data.tobytes())
    return buffer.getvalue()
