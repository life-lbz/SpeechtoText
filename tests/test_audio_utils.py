import numpy as np

from app.services.audio_utils import is_digital_silence


def test_silence_and_quantization_floor_are_empty():
    assert is_digital_silence(np.zeros(16000, dtype=np.float32))
    assert is_digital_silence(np.full(16000, 1 / 32768, dtype=np.float32))


def test_quiet_nonzero_audio_is_not_discarded():
    audio = 0.001 * np.sin(np.arange(16000) * 0.1).astype(np.float32)
    assert not is_digital_silence(audio)
