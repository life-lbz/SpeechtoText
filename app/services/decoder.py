"""音频解码：统一转换为 16kHz 单声道 float32 numpy 数组。"""

import wave
from pathlib import Path
from typing import BinaryIO

import numpy as np

from app.config import settings


class AudioDecodeError(Exception):
    """音频无法解码或内容为空。"""


class AudioTooLongError(AudioDecodeError):
    """音频超过允许的时长。"""


def decode_audio(
    source: str | Path | BinaryIO, target_sr: int | None = None, *,
    max_seconds: float | None = None, suffix: str | None = None,
) -> np.ndarray:
    """解码任意支持的音频文件为 float32 波形（取值范围 -1.0 ~ 1.0）。"""
    target_sr = target_sr or settings.target_sample_rate
    if isinstance(source, (str, Path)):
        path = Path(source)
        suffix = path.suffix
        source = str(path)

    if (suffix or "").lower() == ".wav":
        try:
            return _decode_wav(source, target_sr, max_seconds)
        except AudioDecodeError:
            raise
        except Exception:
            # 部分 WAV 使用非 PCM 编码，交由 av 兜底
            if not isinstance(source, str):
                source.seek(0)

    return _decode_with_av(source, target_sr, max_seconds)


def _decode_wav(source: str | BinaryIO, target_sr: int, max_seconds: float | None) -> np.ndarray:
    with wave.open(source, "rb") as reader:
        channels = reader.getnchannels()
        sample_width = reader.getsampwidth()
        frame_rate = reader.getframerate()
        compression = reader.getcomptype()
        if max_seconds is not None and reader.getnframes() > int(frame_rate * max_seconds):
            raise AudioTooLongError
        frames = bytearray()
        batch_frames = max(1, 65536 // (channels * sample_width))
        while block := reader.readframes(batch_frames):
            frames.extend(block)

    if compression != "NONE":
        raise AudioDecodeError("不支持的 WAV 编码")
    if not frames:
        raise AudioDecodeError("音频文件为空")

    if sample_width == 1:
        data = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sample_width == 2:
        data = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif sample_width == 3:
        raw = np.frombuffer(frames, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        values = raw[:, 0] | (raw[:, 1] << 8) | (raw[:, 2] << 16)
        values = np.where(values >= 1 << 23, values - (1 << 24), values)
        data = values.astype(np.float32) / float(1 << 23)
    elif sample_width == 4:
        data = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise AudioDecodeError("不支持的 WAV 位深")

    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return _resample(data, frame_rate, target_sr)


def _decode_with_av(source: str | BinaryIO, target_sr: int, max_seconds: float | None) -> np.ndarray:
    try:
        import av
    except ImportError as exc:  # pragma: no cover - 依赖缺失时的兜底
        raise AudioDecodeError("缺少音频解码组件 av") from exc

    chunks: list[np.ndarray] = []
    max_samples = None if max_seconds is None else int(target_sr * max_seconds)
    sample_count = 0

    def append_frame(frame):
        nonlocal sample_count
        sample_count += frame.samples
        if max_samples is not None and sample_count > max_samples:
            raise AudioTooLongError
        chunks.append(frame.to_ndarray().reshape(-1))

    try:
        with av.open(source, mode="r") as container:
            stream = next(
                (item for item in container.streams if item.type == "audio"), None
            )
            if stream is None:
                raise AudioDecodeError("文件中未检测到音频轨道")
            stream.thread_type = "AUTO"
            resampler = av.AudioResampler(format="s16", layout="mono", rate=target_sr)
            for frame in container.decode(stream):
                for resampled in resampler.resample(frame):
                    append_frame(resampled)
            for resampled in resampler.resample(None):
                append_frame(resampled)
    except AudioDecodeError:
        raise
    except Exception as exc:
        raise AudioDecodeError(f"音频解码失败：{exc}") from exc

    if not chunks:
        raise AudioDecodeError("音频文件为空或已损坏")
    samples = np.concatenate(chunks).astype(np.float32)
    samples /= 32768.0
    return samples


def _resample(data: np.ndarray, source_sr: int, target_sr: int) -> np.ndarray:
    """线性插值重采样，避免引入 scipy 依赖。"""
    data = np.asarray(data, dtype=np.float32)
    if data.size == 0:
        raise AudioDecodeError("音频文件为空")
    if source_sr == target_sr:
        return data

    target_length = max(1, int(round(data.size * target_sr / source_sr)))
    source_index = np.arange(data.size, dtype=np.float64)
    target_index = np.linspace(0, data.size - 1, target_length)
    return np.interp(target_index, source_index, data).astype(np.float32)
