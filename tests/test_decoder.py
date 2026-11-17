import numpy as np
import pytest

from app.services.audio_utils import audio_duration
from app.services.decoder import AudioDecodeError, decode_audio
from tests.helpers import make_wav_bytes


def test_decode_wav_returns_float32_mono(tmp_path):
    path = tmp_path / "tone.wav"
    path.write_bytes(make_wav_bytes(seconds=0.5))

    audio = decode_audio(path)

    assert audio.dtype == np.float32
    assert audio.ndim == 1
    assert abs(audio_duration(audio) - 0.5) < 0.01
    assert np.max(np.abs(audio)) > 0.1


def test_decode_resamples_to_16k(tmp_path):
    path = tmp_path / "tone44k.wav"
    path.write_bytes(make_wav_bytes(seconds=0.5, sample_rate=44100))

    audio = decode_audio(path, target_sr=16000)

    assert abs(audio_duration(audio, 16000) - 0.5) < 0.02


def test_decode_mixes_stereo_to_mono(tmp_path):
    path = tmp_path / "stereo.wav"
    path.write_bytes(make_wav_bytes(seconds=0.3, channels=2))

    audio = decode_audio(path)

    assert audio.ndim == 1
    assert abs(audio_duration(audio) - 0.3) < 0.01


def test_decode_empty_wav_raises(tmp_path):
    path = tmp_path / "empty.wav"
    path.write_bytes(make_wav_bytes(seconds=0))

    with pytest.raises(AudioDecodeError):
        decode_audio(path)


def test_decode_corrupt_file_raises(tmp_path):
    path = tmp_path / "broken.wav"
    path.write_bytes(b"definitely not audio")

    with pytest.raises(AudioDecodeError):
        decode_audio(path)


def test_audio_duration_rejects_empty_array():
    with pytest.raises(ValueError):
        audio_duration(np.array([], dtype=np.float32))
