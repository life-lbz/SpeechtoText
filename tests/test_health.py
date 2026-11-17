def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["model_ready"] is True


def test_index_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "本地语音识别" in response.text


def test_health_reports_unhealthy_without_model(client, fake_transcriber):
    fake_transcriber.ready = False
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] in {"initializing", "unhealthy"}
