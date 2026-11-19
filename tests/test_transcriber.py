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
        self.options = []

    def transcribe(self, audio, **kwargs):
        self.calls += 1
        self.options.append(kwargs)
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


def test_final_uses_quality_options_and_context():
    transcriber = Transcriber()
    model = FlakyModel(failures=0)
    transcriber._model = model

    transcriber.transcribe(np.zeros(1600, dtype=np.float32), "zh", "科大讯飞")

    assert model.options[0]["beam_size"] == 5
    assert model.options[0]["condition_on_previous_text"] is False
    assert "简体中文" in model.options[0]["initial_prompt"]
    assert "科大讯飞" in model.options[0]["initial_prompt"]


def test_chinese_result_is_simplified_and_punctuated():
    transcriber = Transcriber()
    model = FlakyModel(failures=0)
    model.transcribe = lambda audio, **kwargs: (
        [SimpleNamespace(text="這是語音識別的結果,然後再查看。")], None
    )
    transcriber._model = model

    assert transcriber.transcribe(np.zeros(1600, dtype=np.float32), "zh") == (
        "这是语音识别的结果，然后再查看。"
    )


def test_chinese_unpunctuated_segments_get_readable_boundaries():
    transcriber = Transcriber()
    model = FlakyModel(failures=0)
    model.transcribe = lambda audio, **kwargs: (
        [
            SimpleNamespace(text="第一份工作是产品经理", start=0, end=5),
            SimpleNamespace(text="主要对接智能语音座舱", start=5, end=10),
        ],
        None,
    )
    transcriber._model = model

    assert transcriber.transcribe(np.zeros(1600, dtype=np.float32), "zh") == (
        "第一份工作是产品经理，主要对接智能语音座舱。"
    )


def test_preview_keeps_fast_decode():
    transcriber = Transcriber()
    model = FlakyModel(failures=0)
    transcriber._model = model

    transcriber.transcribe(np.zeros(1600, dtype=np.float32), "zh", preview=True)

    assert model.options[0]["beam_size"] == 1


def test_cpu_model_load_uses_bounded_threads(monkeypatch):
    import faster_whisper

    options = {}

    def factory(model_size, **kwargs):
        options.update(kwargs)
        return object()

    monkeypatch.setattr(faster_whisper, "WhisperModel", factory)
    transcriber = Transcriber(device="cpu")
    transcriber.load()
    assert transcriber.ready
    assert options["device"] == "cpu"
    assert options["cpu_threads"] >= 1
