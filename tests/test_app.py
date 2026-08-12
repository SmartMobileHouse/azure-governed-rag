from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_is_live():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_ready_reports_config():
    r = client.get("/ready")
    assert r.status_code == 200
    body = r.json()
    # With nothing configured in CI, readiness is False but the shape is stable.
    assert set(body["configured"]) == {"azure_openai", "content_safety", "language", "postgres"}


def test_root():
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["name"] == "azure-governed-rag"
