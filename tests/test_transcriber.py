from threading import Event
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
        self.options = {}

    def transcribe(self, audio, **kwargs):
        self.calls += 1
        self.options = kwargs
        if self.calls <= self.failures:
            raise RuntimeError("boom")
        return [SimpleNamespace(text=" 語音 "), SimpleNamespace(text="識別系統。")], None


def test_transcribe_requires_loaded_model():
    with pytest.raises(ModelNotReadyError):
        Transcriber().transcribe(np.zeros(1600, dtype=np.float32), "zh")


@pytest.mark.parametrize(("preview", "beam_size"), [(False, 5), (True, 1)])
def test_chinese_output_is_simplified(preview, beam_size):
    transcriber = Transcriber()
    model = FlakyModel(failures=0)
    transcriber._model = model

    text = transcriber.transcribe(np.zeros(1600, dtype=np.float32), "zh", preview=preview)

    assert text == "语音识别系统。"
    assert model.options["beam_size"] == beam_size


def test_transcribe_retries_once_then_succeeds():
    transcriber = Transcriber()
    model = FlakyModel(failures=1)
    transcriber._model = model

    assert transcriber.transcribe(np.zeros(1600, dtype=np.float32), "en") == "語音 識別系統。"
    assert model.calls == 2
    assert model.options["beam_size"] == 1


def test_transcribe_raises_after_retry_exhausted():
    transcriber = Transcriber()
    model = FlakyModel(failures=5)
    transcriber._model = model

    with pytest.raises(TranscriptionError):
        transcriber.transcribe(np.zeros(1600, dtype=np.float32), "zh")
    assert model.calls == 2


def test_auto_starts_on_cpu_promotes_and_retries_on_cpu(monkeypatch):
    import ctranslate2

    allow_probe = Event()
    cpu_model = FlakyModel(failures=0)
    gpu_model = FlakyModel(failures=0)
    model_loads = []
    transcriber = Transcriber(
        "base", device="auto", cpu_paraformer_path="",
        gpu_model_size="large-v3-turbo", gpu_model_path="local-turbo",
    )

    def get_cuda_device_count():
        assert allow_probe.wait(timeout=5)
        return 1

    def create_model(model_size_or_path, device, compute_type):
        model_loads.append((model_size_or_path, device, compute_type))
        return gpu_model if device == "cuda" else cpu_model

    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", get_cuda_device_count)
    monkeypatch.setattr(transcriber, "_create_model", create_model)
    transcriber.load()
    probe_thread = transcriber._probe_thread
    audio = np.zeros(1600, dtype=np.float32)
    try:
        assert transcriber.acceleration_status["device"] == "cpu"
        assert transcriber.acceleration_status["model"] == "base"
        expected = transcriber.transcribe(audio, "en")
    finally:
        allow_probe.set()
        probe_thread.join(timeout=5)

    assert transcriber.acceleration_status["device"] == "cuda"
    assert transcriber.acceleration_status["model"] == "large-v3-turbo"
    assert gpu_model.calls == 1

    def fail_on_gpu(*args, **kwargs):
        raise RuntimeError("CUDA out of memory")

    monkeypatch.setattr(gpu_model, "transcribe", fail_on_gpu)
    assert transcriber.transcribe(audio, "en") == expected
    assert transcriber.acceleration_status["device"] == "cpu"
    assert transcriber.acceleration_status["model"] == "base"
    assert transcriber.acceleration_status["gpu_error"] == "CUDA out of memory"
    assert transcriber.transcribe(audio, "en") == expected
    assert model_loads == [
        ("base", "cpu", "int8"),
        ("local-turbo", "cuda", "int8_float16"),
        ("base", "cpu", "int8"),
    ]


def test_cpu_selects_paraformer_for_chinese_and_whisper_for_english(monkeypatch):
    class FakeParaformer:
        def __init__(self, path):
            assert path == "local-paraformer"

        def transcribe(self, audio):
            return "中文转写"

    transcriber = Transcriber("base", device="cpu", cpu_paraformer_path="local-paraformer")
    monkeypatch.setattr("app.services.transcriber.ParaformerModel", FakeParaformer)
    whisper = FlakyModel(failures=0)
    monkeypatch.setattr(transcriber, "_create_model", lambda *args: whisper)
    audio = np.zeros(1600, dtype=np.float32)

    transcriber.load()
    assert transcriber.acceleration_status["model"] == "funasr-paraformer"
    assert transcriber.transcribe(audio, "zh") == "中文转写"
    assert transcriber.transcribe(audio, "en") == "語音 識別系統。"
    assert transcriber.acceleration_status["model"] == "base"
    assert transcriber.transcribe(audio, "zh") == "中文转写"

    def fail_on_cpu(self, audio):
        raise RuntimeError("ONNX error")

    monkeypatch.setattr(FakeParaformer, "transcribe", fail_on_cpu)
    assert transcriber.transcribe(audio, "zh") == "语音识别系统。"
    assert transcriber.acceleration_status["model"] == "base"
