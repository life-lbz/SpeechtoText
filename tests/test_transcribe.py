def test_transcribe_wav_success(client, fake_transcriber, sample_wav):
    response = client.post(
        "/api/transcribe",
        files={"file": ("chinese.wav", sample_wav, "audio/wav")},
        data={"language": "zh"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["text"] == fake_transcriber.text
    assert body["language"] == "zh"
    assert 0.9 <= body["duration_seconds"] <= 1.1
    assert body["processing_seconds"] >= 0
    assert len(fake_transcriber.calls) == 1


def test_transcribe_passes_language_to_model(client, fake_transcriber, sample_wav):
    response = client.post(
        "/api/transcribe",
        files={"file": ("english.wav", sample_wav, "audio/wav")},
        data={"language": "en"},
    )
    assert response.status_code == 200
    assert fake_transcriber.calls[0][1] == "en"


def test_empty_file_returns_400(client):
    response = client.post(
        "/api/transcribe",
        files={"file": ("empty.wav", b"", "audio/wav")},
        data={"language": "zh"},
    )
    assert response.status_code == 400


def test_unsupported_extension_returns_400(client):
    response = client.post(
        "/api/transcribe",
        files={"file": ("note.txt", b"hello", "text/plain")},
        data={"language": "zh"},
    )
    assert response.status_code == 400
    assert "不支持" in response.json()["detail"]


def test_invalid_language_returns_422(client, sample_wav):
    response = client.post(
        "/api/transcribe",
        files={"file": ("chinese.wav", sample_wav, "audio/wav")},
        data={"language": "fr"},
    )
    assert response.status_code == 422
    assert "zh" in response.json()["detail"]


def test_oversized_file_returns_413(client):
    payload = b"0" * (10 * 1024 * 1024 + 1024)
    response = client.post(
        "/api/transcribe",
        files={"file": ("big.wav", payload, "audio/wav")},
        data={"language": "zh"},
    )
    assert response.status_code == 413


def test_audio_longer_than_60_seconds_returns_400(client):
    from tests.helpers import make_wav_bytes

    long_wav = make_wav_bytes(seconds=61)
    response = client.post(
        "/api/transcribe",
        files={"file": ("long.wav", long_wav, "audio/wav")},
        data={"language": "zh"},
    )
    assert response.status_code == 400
    assert "60" in response.json()["detail"]


def test_model_not_ready_returns_503(client, fake_transcriber, sample_wav):
    fake_transcriber.ready = False
    response = client.post(
        "/api/transcribe",
        files={"file": ("chinese.wav", sample_wav, "audio/wav")},
        data={"language": "zh"},
    )
    assert response.status_code == 503


def test_corrupt_wav_returns_400(client):
    response = client.post(
        "/api/transcribe",
        files={"file": ("broken.wav", b"not-a-real-audio", "audio/wav")},
        data={"language": "zh"},
    )
    assert response.status_code == 400
