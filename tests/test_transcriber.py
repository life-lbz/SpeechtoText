from types import SimpleNamespace

import numpy as np
import pytest

from app.services.transcriber import (
    ModelNotReadyError,
    Transcriber,
    TranscriptionError,
)


class FlakyModel:
    """前 N 次调用抛错，之后返回固定文本。"""

    def __init__(self, failures=1):
        self.failures = failures
        self.calls = 0

    def transcribe(self, audio, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("boom")
        return [SimpleNamespace(text=" 你好 "), SimpleNamespace(text="世界。")], None


def test_transcribe_requires_loaded_model():
    with pytest.raises(ModelNotReadyError):
        Transcriber().transcribe(np.zeros(1600, dtype=np.float32), "zh")


def test_transcribe_joins_segments_and_strips():
    transcriber = Transcriber()
    transcriber._model = FlakyModel(failures=0)

    text = transcriber.transcribe(np.zeros(1600, dtype=np.float32), "zh")

    assert text == "你好世界。"


def test_transcribe_retries_once_then_succeeds():
    transcriber = Transcriber()
    model = FlakyModel(failures=1)
    transcriber._model = model

    assert transcriber.transcribe(np.zeros(1600, dtype=np.float32), "en") == "你好 世界。"
    assert model.calls == 2


def test_transcribe_raises_after_retry_exhausted():
    transcriber = Transcriber()
    model = FlakyModel(failures=5)
    transcriber._model = model

    with pytest.raises(TranscriptionError):
        transcriber.transcribe(np.zeros(1600, dtype=np.float32), "zh")
    assert model.calls == 2
