"""音频时长计算工具。"""

import numpy as np


def audio_duration(audio: np.ndarray, sample_rate: int = 16000) -> float:
    """按采样点数计算音频时长（秒）。"""
    if audio is None or audio.size == 0:
        raise ValueError("音频数据为空，无法计算时长")
    return audio.size / float(sample_rate)
