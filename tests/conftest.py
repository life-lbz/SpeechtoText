import os

# 测试不加载真实模型（必须在导入 app 之前设置）
os.environ["ASR_PRELOAD"] = "0"

import pytest
from fastapi.testclient import TestClient

from tests.helpers import make_wav_bytes


class FakeTranscriber:
    """测试替身：不加载权重，直接返回固定文本。"""

    def __init__(self, text="你好，欢迎使用本地语音识别系统。", ready=True):
        self.text = text
        self.ready = ready
        self.calls = []

    def load(self):
        self.ready = True

    def transcribe(self, audio, language):
        self.calls.append((audio, language))
        return self.text


@pytest.fixture
def fake_transcriber():
    return FakeTranscriber()


@pytest.fixture
def client(fake_transcriber):
    from app.main import create_app

    app = create_app()
    app.state.transcriber = fake_transcriber
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def sample_wav():
    return make_wav_bytes(seconds=1.0)
