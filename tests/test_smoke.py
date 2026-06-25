from fastapi.testclient import TestClient

from app.main import app


def test_root_endpoint():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["message"] == "Distributed Task Platform API"

