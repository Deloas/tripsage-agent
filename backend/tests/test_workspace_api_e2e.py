from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import models  # noqa: F401
from app.db.session import Base
from app.db.session import get_db


def _build_auth_header(token: str) -> dict[str, str]:
    """构造统一的 Bearer 鉴权请求头。"""

    return {"Authorization": f"Bearer {token}"}


def test_workspace_api_logged_user_profile_flow_e2e(monkeypatch) -> None:
    """登录用户应能完整跑通认证、画像、历史导入、审计与撤销链路。"""

    import app.main as main_module

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = Session(bind=engine)

    class _FakeBootstrapService:
        """测试启动时跳过真实引导初始化，避免污染本地环境。"""

        def __init__(self, db: Session) -> None:
            self.db = db

        async def run(self) -> dict:
            return {
                "seed_inserted": 0,
                "seed_skipped": 0,
                "vector_rebuilt": False,
                "weibo_crawl": None,
            }

    monkeypatch.setattr(main_module, "init_db", lambda: None)
    monkeypatch.setattr(main_module, "BootstrapService", _FakeBootstrapService)

    app = main_module.create_app()

    def override_get_db():
        """把测试用内存数据库注入 FastAPI 依赖。"""

        yield session

    app.dependency_overrides[get_db] = override_get_db

    unique = uuid4().hex[:8]
    username = f"e2e_{unique}"
    password = "secret123"

    with TestClient(app) as client:
        register_response = client.post(
            "/api/auth/register",
            headers={"X-Client-Name": "pytest-e2e"},
            json={
                "display_name": "接口验收用户",
                "username": username,
                "password": password,
                "home_city": "上海",
                "travel_style": "轻松慢游",
            },
        )
        assert register_response.status_code == 200
        register_body = register_response.json()
        assert register_body["code"] == 0

        auth_data = register_body["data"]
        access_token = auth_data["access_token"]
        refresh_token = auth_data["refresh_token"]
        auth_header = _build_auth_header(access_token)

        me_response = client.get("/api/auth/me", headers=auth_header)
        assert me_response.status_code == 200
        me_body = me_response.json()
        assert me_body["code"] == 0
        assert me_body["data"]["user"]["display_name"] == "接口验收用户"
        assert me_body["data"]["user"]["username"].startswith("e2e-")

        feedback_response = client.post(
            "/api/preference-profile/feedback",
            headers=auth_header,
            json={
                "dimension": "transport",
                "value": "高铁",
                "action": "set_common",
                "conversation_id": "conv-e2e-001",
            },
        )
        assert feedback_response.status_code == 200
        feedback_body = feedback_response.json()
        assert feedback_body["code"] == 0
        assert "高铁" in feedback_body["data"]["long_term_profile"]["transport_modes"]

        lock_response = client.post(
            "/api/preference-profile/feedback",
            headers=auth_header,
            json={
                "dimension": "transport",
                "value": "高铁",
                "action": "lock_long_term",
                "conversation_id": "conv-e2e-001",
            },
        )
        assert lock_response.status_code == 200
        lock_body = lock_response.json()
        assert lock_body["code"] == 0
        assert any(item["value"] == "高铁" for item in lock_body["data"]["locked_items"])

        event_response = client.post(
            "/api/preference-profile/events",
            headers=auth_header,
            json={
                "action": "favorite_on",
                "conversation_id": "conv-e2e-001",
                "payload": {
                    "title": "南京周末高铁慢游",
                    "destination_city": "南京",
                    "budget": 1800,
                    "tags": ["周末", "历史", "美食"],
                    "summary": "高铁优先，轻松节奏，偏好历史与美食。",
                },
            },
        )
        assert event_response.status_code == 200
        event_body = event_response.json()
        assert event_body["code"] == 0
        assert "南京" in event_body["data"]["preferred_cities"]

        import_response = client.post(
            "/api/conversations/import-guest-session",
            headers=auth_header,
            json={
                "user_id": 99999,
                "title": "南京两天一夜",
                "messages": [
                    {"role": "user", "content": "我想从上海去南京玩两天一夜。"},
                    {"role": "assistant", "content": "建议优先高铁，并预留雨天备选。"},
                ],
                "plan_versions": [
                    {
                        "id": "guest-version-001",
                        "name": "初版方案",
                        "reason": "游客首次生成",
                        "created_at": datetime.now(UTC).isoformat(),
                        "response": {
                            "answer": "建议周末出发，优先高铁，安排博物馆与美食街。",
                            "cards": [{"type": "destination", "title": "南京"}],
                            "decision_modules": [
                                {
                                    "type": "rainy_day",
                                    "title": "雨天备选",
                                    "level": "warn",
                                    "summary": "已准备室内方案。",
                                    "points": ["优先博物馆", "减少步行暴露时间"],
                                }
                            ],
                        },
                    }
                ],
                "active_version_id": "guest-version-001",
                "latest_response": {
                    "answer": "建议周末出发，优先高铁，安排博物馆与美食街。",
                    "cards": [{"type": "destination", "title": "南京"}],
                },
                "destination_city": "南京",
                "budget": 1800,
                "start_date": "周末",
                "tags": ["周末", "高铁出行", "美食"],
            },
        )
        assert import_response.status_code == 200
        import_body = import_response.json()
        assert import_body["code"] == 0
        conversation_id = import_body["data"]["conversation_id"]

        conversations_response = client.get("/api/conversations", headers=auth_header)
        assert conversations_response.status_code == 200
        conversations_body = conversations_response.json()
        assert conversations_body["code"] == 0
        assert conversations_body["data"]["total"] >= 1
        assert any(item["id"] == conversation_id for item in conversations_body["data"]["items"])

        detail_response = client.get(f"/api/conversations/{conversation_id}", headers=auth_header)
        assert detail_response.status_code == 200
        detail_body = detail_response.json()
        assert detail_body["code"] == 0
        assert len(detail_body["data"]["messages"]) == 2

        profile_response = client.get(
            "/api/preference-profile",
            headers=auth_header,
            params={"conversation_id": "conv-e2e-001"},
        )
        assert profile_response.status_code == 200
        profile_body = profile_response.json()
        assert profile_body["code"] == 0
        assert "高铁" in profile_body["data"]["long_term_profile"]["transport_modes"]
        assert any(item["value"] == "高铁" for item in profile_body["data"]["locked_items"])

        audit_response = client.get(
            "/api/preference-profile/audit",
            headers=auth_header,
            params={"conversation_id": "conv-e2e-001", "limit_per_group": 10},
        )
        assert audit_response.status_code == 200
        audit_body = audit_response.json()
        assert audit_body["code"] == 0
        assert audit_body["data"]["summary"]["locked_total"] >= 1
        assert audit_body["data"]["summary"]["behavior_total"] >= 1

        timeline_response = client.get(
            "/api/preference-profile/timeline",
            headers=auth_header,
            params={"conversation_id": "conv-e2e-001", "limit": 20},
        )
        assert timeline_response.status_code == 200
        timeline_body = timeline_response.json()
        assert timeline_body["code"] == 0
        assert timeline_body["data"]["total"] >= 3
        undoable = next(item for item in timeline_body["data"]["items"] if item["can_undo"] is True)

        undo_response = client.post(
            "/api/preference-profile/timeline/undo",
            headers=auth_header,
            json={"event_id": undoable["id"], "conversation_id": "conv-e2e-001"},
        )
        assert undo_response.status_code == 200
        undo_body = undo_response.json()
        assert undo_body["code"] == 0
        assert undo_body["data"]["undone_event_id"] == undoable["id"]
        assert any(
            item["id"] == undoable["id"] and item["is_undone"] is True
            for item in undo_body["data"]["timeline"]["items"]
        )

        refresh_response = client.post(
            "/api/auth/refresh",
            headers={"X-Client-Name": "pytest-e2e-refresh"},
            json={"refresh_token": refresh_token},
        )
        assert refresh_response.status_code == 200
        refresh_body = refresh_response.json()
        assert refresh_body["code"] == 0
        refreshed_access_token = refresh_body["data"]["access_token"]
        refreshed_refresh_token = refresh_body["data"]["refresh_token"]
        refreshed_auth_header = _build_auth_header(refreshed_access_token)

        sessions_response = client.get("/api/auth/sessions", headers=refreshed_auth_header)
        assert sessions_response.status_code == 200
        sessions_body = sessions_response.json()
        assert sessions_body["code"] == 0
        assert sessions_body["data"]["total"] >= 1

        logout_response = client.post(
            "/api/auth/logout",
            json={"refresh_token": refreshed_refresh_token},
        )
        assert logout_response.status_code == 200
        logout_body = logout_response.json()
        assert logout_body["code"] == 0

    app.dependency_overrides.clear()
    session.close()
    Base.metadata.drop_all(bind=engine)
