from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_home():
    response = client.get("/")
    assert response.status_code == 200
    assert "شركة جولدن كوست التجارية" in response.text

def test_manifest():
    response = client.get("/manifest.webmanifest")
    assert response.status_code == 200
    assert response.json()["dir"] == "rtl"
