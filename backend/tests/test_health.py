from fastapi.testclient import TestClient

from app.main import app


def test_health_check() -> None:
    """健康检查应返回统一成功结构。"""
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["status"] == "healthy"

