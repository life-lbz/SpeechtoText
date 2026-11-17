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
    assert not fake_transcriber.calls[0][2]


def test_realtime_fragment_uses_preview_mode(client, fake_transcriber, sample_wav):
    response = client.post(
        "/api/transcribe",
        files={"file": ("preview.wav", sample_wav, "audio/wav")},
        data={"language": "zh", "preview": "true"},
    )
    assert response.status_code == 200
    assert fake_transcriber.calls[0][1:] == ("zh", True)


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


def test_oversized_chunked_body_returns_413(client, fake_transcriber):
    def body():
        yield b'--bound\r\nContent-Disposition: form-data; name="file"; filename="large.wav"\r\n\r\n'
        for _ in range(13):
            yield b"x" * (1024 * 1024)
        yield b"\r\n--bound--\r\n"

    response = client.post(
        "/api/transcribe",
        content=body(),
        headers={"Content-Type": "multipart/form-data; boundary=bound"},
    )
    assert response.request.headers.get("transfer-encoding") == "chunked"
    assert response.status_code == 413
    assert not fake_transcriber.calls


def test_audio_longer_than_60_seconds_is_allowed_for_upload_only(client, fake_transcriber):
    from tests.helpers import make_wav_bytes

    long_wav = make_wav_bytes(seconds=61)
    files = {"file": ("long.wav", long_wav, "audio/wav")}
    upload = client.post("/api/transcribe", files=files, data={"language": "zh"})
    assert upload.status_code == 200
    assert upload.json()["duration_seconds"] == 61.0

    for mode in ("recording", "preview"):
        response = client.post("/api/transcribe", files=files, data={"language": "zh", mode: "true"})
        assert response.status_code == 400
        assert "60" in response.json()["detail"]
    assert len(fake_transcriber.calls) == 1


def test_lazy_model_load_failure_returns_503_and_can_retry(
    client, fake_transcriber, sample_wav, monkeypatch
):
    fake_transcriber.ready = False
    load = fake_transcriber.load

    def fail_load():
        raise RuntimeError("model missing")

    payload = {
        "files": {"file": ("chinese.wav", sample_wav, "audio/wav")},
        "data": {"language": "zh"},
    }
    monkeypatch.setattr(fake_transcriber, "load", fail_load)
    response = client.post("/api/transcribe", **payload)
    assert response.status_code == 503
    assert client.get("/health").json() == {"status": "unhealthy"}
    assert not fake_transcriber.calls

    monkeypatch.setattr(fake_transcriber, "load", load)
    assert client.post("/api/transcribe", **payload).status_code == 200
    assert client.get("/health").json() == {"status": "ok"}


def test_corrupt_wav_returns_400_without_loading_model(client, fake_transcriber):
    fake_transcriber.ready = False
    response = client.post(
        "/api/transcribe",
        files={"file": ("broken.wav", b"not-a-real-audio", "audio/wav")},
        data={"language": "zh"},
    )
    assert response.status_code == 400
    assert not fake_transcriber.ready
