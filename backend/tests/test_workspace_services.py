import json

import pytest

from app.agents.graph import TripAgent
from app.api import workspace as workspace_api
from app.db.models import (
    Conversation,
    Itinerary,
    Message,
    PlanVersion,
    SharedPlan,
    ToolCall,
    TravelPreferenceEvent,
    TravelPreferenceProfile,
)
from app.schemas.chat import ChatRequest
from app.schemas.workspace import (
    ConversationUpdateRequest,
    GuestSessionImportRequest,
    PreferenceBehaviorEventRequest,
    PreferenceFeedbackRequest,
    PreferenceTimelineUndoRequest,
    UserCreateRequest,
    UserLoginRequest,
    UserProfileUpdateRequest,
)
from app.services.auth_service import AuthService
from app.services.conversation_service import ConversationService
from app.services.preference_service import PreferenceService
from app.services.tool_log_service import ToolLogger
from app.services.user_service import UserService


SHANGHAI = "\u4e0a\u6d77"
NANJING = "\u5357\u4eac"
HANGZHOU = "\u676d\u5dde"
WEEKEND = "\u5468\u672b"
HIGH_SPEED_RAIL = "\u9ad8\u94c1"
RELAXED = "\u8f7b\u677e"
FOOD = "\u7f8e\u98df"
HISTORY = "\u5386\u53f2"
RAIN_BACKUP = "\u96e8\u5929\u5907\u9009"


def _auth_header(token: str) -> str:
    return f"Bearer {token}"


def _create_logged_user(db_session):
    service = UserService(db_session)
    service.ensure_default_user()
    service.create_user(
        UserCreateRequest(
            display_name="Xiaolin",
            username="xiaolin",
            password="secret123",
            home_city=SHANGHAI,
            travel_style=RELAXED,
        )
    )
    auth = service.login(
        UserLoginRequest(username="xiaolin", password="secret123"),
        client_name="pytest",
        user_agent="pytest-agent",
    )
    return auth


def test_preference_profile_learns_from_interaction(db_session) -> None:
    """偏好画像应能从用户问题和智能体结果中沉淀城市、预算和兴趣。"""
    service = PreferenceService(db_session)
    service.learn_from_interaction(
        f"{SHANGHAI}\u51fa\u53d1\uff0c\u9884\u7b97800\u5143\uff0c\u60f3{RELAXED}\u4e00\u70b9\uff0c\u559c\u6b22{FOOD}\u548c{HISTORY}\uff0c\u4f18\u5148{HIGH_SPEED_RAIL}\u3002",
        {
            "answer": f"\u5efa\u8bae\u53bb{NANJING}\u3002",
            "cards": [{"type": "destination", "title": NANJING}],
        },
    )

    profile = service.get_profile()

    assert SHANGHAI in profile.preferred_cities
    assert NANJING in profile.preferred_cities
    assert profile.budget_range
    assert HIGH_SPEED_RAIL in profile.transport_modes
    assert RELAXED in profile.pace_tags
    assert FOOD in profile.interest_tags


def test_preference_profile_tracks_negative_and_behavior_signals(db_session) -> None:
    """偏好画像应同时识别负向偏好与真实行为反馈。"""
    service = PreferenceService(db_session, user_key="42")
    service.learn_from_interaction(
        f"{SHANGHAI}出发，预算2000元，不要早班车，别太赶，优先{HIGH_SPEED_RAIL}，想多吃点{FOOD}。",
        {"answer": f"建议去{NANJING}。", "cards": [{"type": "destination", "title": NANJING}]},
        slots={"destination": NANJING, "budget": "2000", "days": 2},
        conversation_id="conv-pref-1",
    )
    service.learn_from_interaction(
        "请基于我刚才采纳的模块继续优化。",
        {"answer": "", "cards": []},
        context={
            "decision_module_action": "accept",
            "decision_module": {
                "type": "budget",
                "title": "预算提示",
                "summary": "建议控制交通与餐饮总成本",
                "points": ["预算控制", "少打车"],
            },
        },
        conversation_id="conv-pref-1",
    )

    profile = service.get_profile()
    events = db_session.query(TravelPreferenceEvent).filter(TravelPreferenceEvent.user_key == "42").all()

    assert any("早班车" in item for item in profile.negative_preferences)
    assert any("预算控制" in item for item in profile.behavior_signals)
    assert profile.profile_strength in {"growing", "strong"}
    assert profile.recent_evidence
    assert len(events) >= 4


def test_preference_profile_accepts_manual_feedback(db_session) -> None:
    """用户应能把系统判断纠正为长期偏好或明确避让。"""
    service = PreferenceService(db_session, user_key="84")
    service.learn_from_interaction(
        f"{SHANGHAI}出发，预算1800元，想轻松一点，优先{HIGH_SPEED_RAIL}。",
        {"answer": f"建议去{NANJING}。", "cards": [{"type": "destination", "title": NANJING}]},
        conversation_id="conv-manual-1",
    )

    profile = service.apply_manual_feedback(
        dimension="interest",
        value=FOOD,
        polarity="positive",
        conversation_id="conv-manual-1",
    )
    profile = service.apply_manual_feedback(
        dimension="transport",
        value=HIGH_SPEED_RAIL,
        polarity="negative",
        conversation_id="conv-manual-1",
    )
    profile = service.apply_manual_feedback(
        dimension="avoidance",
        value="早班车",
        polarity="negative",
        conversation_id="conv-manual-1",
    )

    events = db_session.query(TravelPreferenceEvent).filter(TravelPreferenceEvent.user_key == "84").all()

    assert FOOD in profile.interest_tags
    assert HIGH_SPEED_RAIL not in profile.transport_modes
    assert any(HIGH_SPEED_RAIL in item for item in profile.negative_preferences)
    assert any("早班车" in item for item in profile.negative_preferences)
    assert any(item.source_type == "manual_prefer" for item in events)
    assert any(item.source_type == "manual_avoid" for item in events)


def test_preference_profile_splits_long_term_and_session_layers(db_session) -> None:
    """画像应同时给出长期层和本次层，并支持把长期偏好移除。"""

    service = PreferenceService(db_session, user_key="108")
    service.apply_manual_feedback(
        dimension="transport",
        value=HIGH_SPEED_RAIL,
        action="set_common",
        conversation_id="conv-layer-1",
    )
    service.apply_manual_feedback(
        dimension="interest",
        value=FOOD,
        action="session_only",
        polarity="positive",
        conversation_id="conv-layer-1",
    )

    profile = service.get_profile(conversation_id="conv-layer-1")

    assert HIGH_SPEED_RAIL in profile.long_term_profile.transport_modes
    assert FOOD in profile.session_profile.interest_tags
    assert FOOD not in profile.long_term_profile.interest_tags

    profile = service.apply_manual_feedback(
        dimension="transport",
        value=HIGH_SPEED_RAIL,
        action="remove_long_term",
        conversation_id="conv-layer-1",
    )

    assert HIGH_SPEED_RAIL not in profile.long_term_profile.transport_modes


def test_conversation_service_lists_and_reads_history(db_session) -> None:
    """历史规划中心应能列出会话摘要并恢复消息。"""
    db_session.add(Conversation(id="conv-history", title="history plan"))
    db_session.add(Message(conversation_id="conv-history", role="user", content="How to visit Nanjing?"))
    db_session.add(Message(conversation_id="conv-history", role="assistant", content="Use a 2-day plan."))
    db_session.add(
        PlanVersion(
            id="version-history",
            conversation_id="conv-history",
            name="initial",
            reason="test",
            response_json='{"answer":"Use a 2-day plan."}',
        )
    )
    db_session.commit()

    service = ConversationService(db_session)
    items = service.list_conversations()
    detail = service.get_conversation("conv-history")

    assert len(items) == 1
    assert items[0].message_count == 2
    assert items[0].version_count == 1
    assert detail.messages[0].content == "How to visit Nanjing?"


def test_conversation_service_updates_archive_metadata(db_session) -> None:
    """历史中心应支持收藏、标签和筛选字段的持久化。"""
    db_session.add(Conversation(id="conv-archive", title="original title", user_id=1))
    db_session.add(Message(conversation_id="conv-archive", role="user", content="Weekend trip to Hangzhou"))
    db_session.commit()

    service = ConversationService(db_session)
    summary = service.update_conversation(
        "conv-archive",
        ConversationUpdateRequest(
            title=f"{HANGZHOU}{WEEKEND}\u6162\u6e38",
            is_favorite=True,
            tags=[WEEKEND, "\u6c5f\u5357", FOOD],
            destination_city=HANGZHOU,
            budget=1500,
            start_date=WEEKEND,
        ),
        user_id=1,
    )

    assert summary.title == f"{HANGZHOU}{WEEKEND}\u6162\u6e38"
    assert summary.is_favorite is True
    assert summary.tags == [WEEKEND, "\u6c5f\u5357", FOOD]
    assert summary.destination_city == HANGZHOU
    assert summary.budget == 1500
    assert summary.start_date == WEEKEND


def test_conversation_service_syncs_archive_metadata_from_agent(db_session) -> None:
    """智能体完成后应自动补齐历史检索所需的目的地、预算和标签。"""
    db_session.add(Conversation(id="conv-sync", title="Want to visit Nanjing", user_id=1))
    db_session.commit()

    service = ConversationService(db_session)
    service.sync_archive_meta(
        "conv-sync",
        f"\u60f3\u53bb{NANJING}\u73a9",
        {
            "answer": f"\u5efa\u8bae{WEEKEND}{HIGH_SPEED_RAIL}\u53bb{NANJING}\uff0c\u8bb0\u5f97\u51c6\u5907{RAIN_BACKUP}\u3002",
            "cards": [{"type": "destination", "title": NANJING}],
            "decision_modules": [{"type": "rainy_day", "level": "warn"}],
        },
        {"destination": NANJING, "budget": "1800", "date": WEEKEND, "origin": SHANGHAI},
        user_id=1,
    )
    summary = service.list_conversations(user_id=1)[0]

    assert summary.title == f"{WEEKEND} {NANJING}\u51fa\u884c"
    assert summary.destination_city == NANJING
    assert summary.budget == 1800
    assert summary.start_date == WEEKEND
    assert NANJING in summary.tags
    assert f"{WEEKEND}\u51fa\u884c" in summary.tags


def test_conversation_service_deletes_related_records(db_session) -> None:
    """删除会话时应一并清理消息、版本、分享、行程和工具日志。"""
    db_session.add(Conversation(id="conv-delete", title="to delete", user_id=1))
    db_session.add(Message(conversation_id="conv-delete", role="user", content="Delete me"))
    db_session.add(
        PlanVersion(
            id="version-delete",
            conversation_id="conv-delete",
            name="initial",
            reason="test",
            response_json='{"answer":"Delete me"}',
        )
    )
    db_session.add(
        SharedPlan(
            id="share-delete",
            version_id="version-delete",
            conversation_id="conv-delete",
            title="share delete",
            response_json="{}",
        )
    )
    db_session.add(
        Itinerary(
            conversation_id="conv-delete",
            title="delete itinerary",
            destination=NANJING,
            plan_json="{}",
        )
    )
    db_session.add(
        ToolCall(
            conversation_id="conv-delete",
            tool_name="guide_search",
            input_json="{}",
            status="success",
        )
    )
    db_session.commit()

    service = ConversationService(db_session)
    result = service.delete_conversation("conv-delete", user_id=1)

    assert result["deleted"] is True
    assert db_session.get(Conversation, "conv-delete") is None
    assert db_session.query(Message).filter(Message.conversation_id == "conv-delete").count() == 0
    assert db_session.query(PlanVersion).filter(PlanVersion.conversation_id == "conv-delete").count() == 0
    assert db_session.query(SharedPlan).filter(SharedPlan.conversation_id == "conv-delete").count() == 0
    assert db_session.query(Itinerary).filter(Itinerary.conversation_id == "conv-delete").count() == 0
    assert db_session.query(ToolCall).filter(ToolCall.conversation_id == "conv-delete").count() == 0


class _FakeGraph:
    async def ainvoke(self, state):
        return {
            "intent": "itinerary_planning",
            "cards": [{"type": "destination", "title": NANJING, "summary": "test"}],
            "itinerary": [],
            "tool_calls_view": [],
            "sources": [],
            "warnings": [],
            "decision_modules": [],
            "slots": {"destination": NANJING, "budget": "800", "date": WEEKEND},
            "final_answer": "test answer",
        }


@pytest.mark.asyncio
async def test_trip_agent_guest_mode_does_not_persist_history_or_profile(db_session) -> None:
    """游客模式应返回结果，但不写入历史会话和偏好画像。"""
    agent = TripAgent(db_session)
    agent.graph = _FakeGraph()

    response = await agent.run(
        ChatRequest(
            message=f"{WEEKEND}\u60f3\u53bb{NANJING}\u4e24\u5929\u600e\u4e48\u73a9\uff1f",
            context={"persist_session": False},
        )
    )

    assert response.answer == "test answer"
    assert db_session.query(Conversation).count() == 0
    assert db_session.query(Message).count() == 0
    assert db_session.query(TravelPreferenceProfile).count() == 0


def test_tool_logger_can_keep_guest_tool_trace_in_memory(db_session) -> None:
    """游客模式下工具调用应只保留在内存，不落数据库。"""
    buffer: list[dict] = []
    logger = ToolLogger(db_session, conversation_id="guest-conv", enabled=False, memory_buffer=buffer)
    logger.record("guide_search", {"query": NANJING}, "hit 3 guide chunks", "success", 28)

    assert len(buffer) == 1
    assert buffer[0]["tool_name"] == "guide_search"
    assert db_session.query(ToolCall).count() == 0


def test_workspace_guest_mode_returns_empty_history_and_ephemeral_profile(db_session) -> None:
    """游客模式应返回空历史，并明确提示不会沉淀用户画像。"""
    history_response = workspace_api.list_conversations(authorization=None, db=db_session)
    profile_response = workspace_api.get_preference_profile(authorization=None, db=db_session)

    history_body = json.loads(history_response.body)
    profile_body = json.loads(profile_response.body)

    assert history_body["code"] == 0
    assert history_body["data"] == {"items": [], "total": 0}
    assert profile_body["code"] == 0
    assert profile_body["data"]["preferred_cities"] == []
    assert "\u6e38\u5ba2\u6a21\u5f0f" in profile_body["data"]["recommendation_hint"]


def test_workspace_guest_mode_blocks_history_mutation_routes(db_session) -> None:
    """游客模式下不允许读取、编辑或删除持久化历史会话。"""
    detail_response = workspace_api.get_conversation("guest-conv", authorization=None, db=db_session)
    update_response = workspace_api.update_conversation(
        "guest-conv",
        ConversationUpdateRequest(title="\u6e38\u5ba2\u4e0d\u80fd\u4fdd\u5b58"),
        authorization=None,
        db=db_session,
    )
    delete_response = workspace_api.delete_conversation("guest-conv", authorization=None, db=db_session)

    detail_body = json.loads(detail_response.body)
    update_body = json.loads(update_response.body)
    delete_body = json.loads(delete_response.body)

    assert detail_body["code"] == 5015
    assert update_body["code"] == 5016
    assert delete_body["code"] == 5017


def test_workspace_can_import_guest_session_into_logged_user(db_session) -> None:
    """登录用户应能把游客临时方案转入历史中心，并沉淀版本与偏好画像。"""
    auth = _create_logged_user(db_session)
    payload = GuestSessionImportRequest(
        user_id=999,
        title=f"{NANJING}{WEEKEND}\u8ba1\u5212",
        destination_city=NANJING,
        budget=1200,
        start_date=WEEKEND,
        tags=[WEEKEND, f"{HIGH_SPEED_RAIL}\u51fa\u884c"],
        active_version_id="guest-version-1",
        messages=[
            {"role": "assistant", "content": "Welcome to TripSage"},
            {"role": "user", "content": f"{WEEKEND}\u4ece{SHANGHAI}\u53bb{NANJING}\u4e24\u5929\u600e\u4e48\u73a9\uff1f"},
            {"role": "assistant", "content": f"\u53ef\u4ee5\u4f18\u5148{HIGH_SPEED_RAIL}\uff0c\u5e76\u51c6\u5907{RAIN_BACKUP}\u3002"},
        ],
        plan_versions=[
            {
                "id": "guest-version-1",
                "name": "\u521d\u7248",
                "reason": "\u6e38\u5ba2\u6a21\u5f0f\u9996\u6b21\u751f\u6210",
                "created_at": "2026-04-30T15:00:00Z",
                "response": {
                    "conversation_id": "guest-local",
                    "answer": f"\u5efa\u8bae{WEEKEND}\u4ece{SHANGHAI}\u53bb{NANJING}\uff0c\u4f18\u5148{HIGH_SPEED_RAIL}\uff0c\u96e8\u5929\u53ef\u53bb\u5ba4\u5185\u9986\u3002",
                    "intent": "itinerary_planning",
                    "cards": [{"type": "destination", "title": NANJING, "summary": "\u6587\u5316 + \u7f8e\u98df"}],
                    "itinerary": [],
                    "tool_calls": [{"tool_name": "guide_search", "status": "success"}],
                    "sources": [{"title": "Nanjing Guide", "url": "https://example.com"}],
                    "warnings": [],
                    "decision_modules": [{"type": "rainy_day", "title": RAIN_BACKUP, "level": "warn", "summary": "\u5ba4\u5185\u5907\u6848\u5df2\u51c6\u5907", "points": []}],
                },
            }
        ],
        latest_response={
            "answer": f"\u5efa\u8bae{WEEKEND}\u4ece{SHANGHAI}\u53bb{NANJING}\uff0c\u4f18\u5148{HIGH_SPEED_RAIL}\uff0c\u96e8\u5929\u53ef\u53bb\u5ba4\u5185\u9986\u3002",
            "cards": [{"type": "destination", "title": NANJING, "summary": "\u6587\u5316 + \u7f8e\u98df"}],
            "decision_modules": [{"type": "rainy_day", "title": RAIN_BACKUP, "level": "warn", "summary": "\u5ba4\u5185\u5907\u6848\u5df2\u51c6\u5907", "points": []}],
        },
    )

    response = workspace_api.import_guest_session(
        payload,
        authorization=_auth_header(auth.access_token),
        db=db_session,
    )
    body = json.loads(response.body)

    assert body["code"] == 0
    conversation_id = body["data"]["conversation_id"]
    detail = ConversationService(db_session).get_conversation(conversation_id, user_id=auth.user.id)
    summary = ConversationService(db_session).list_conversations(user_id=auth.user.id)[0]
    versions = db_session.query(PlanVersion).filter(PlanVersion.conversation_id == conversation_id).all()
    profile = PreferenceService(db_session, user_key=str(auth.user.id)).get_profile()

    assert detail.title
    assert len(detail.messages) == 3
    assert summary.destination_city == NANJING
    assert summary.budget == 1200
    assert summary.start_date == WEEKEND
    assert len(versions) == 1
    assert NANJING in profile.preferred_cities


def test_workspace_preference_feedback_route_updates_profile(db_session) -> None:
    """画像纠正接口应能立即返回更新后的聚合结果。"""
    auth = _create_logged_user(db_session)
    authorization = _auth_header(auth.access_token)

    response = workspace_api.submit_preference_feedback(
        PreferenceFeedbackRequest(
            dimension="transport",
            value=HIGH_SPEED_RAIL,
            polarity="positive",
            conversation_id="conv-feedback-1",
        ),
        authorization=authorization,
        db=db_session,
    )
    body = json.loads(response.body)

    assert body["code"] == 0
    assert HIGH_SPEED_RAIL in body["data"]["transport_modes"]


def test_workspace_preference_feedback_route_supports_session_action(db_session) -> None:
    """纠偏接口应支持“仅本次生效”这类分层动作。"""

    auth = _create_logged_user(db_session)
    authorization = _auth_header(auth.access_token)

    response = workspace_api.submit_preference_feedback(
        PreferenceFeedbackRequest(
            dimension="interest",
            value=FOOD,
            action="session_only",
            polarity="positive",
            conversation_id="conv-feedback-2",
        ),
        authorization=authorization,
        db=db_session,
    )
    body = json.loads(response.body)

    assert body["code"] == 0
    assert FOOD in body["data"]["session_profile"]["interest_tags"]
    assert FOOD not in body["data"]["long_term_profile"]["interest_tags"]


def test_workspace_preference_behavior_event_route_updates_profile(db_session) -> None:
    """行为事件接口应把收藏、历史续写等动作写入行为画像。"""

    auth = _create_logged_user(db_session)
    authorization = _auth_header(auth.access_token)

    response = workspace_api.submit_preference_behavior_event(
        PreferenceBehaviorEventRequest(
            action="favorite_on",
            conversation_id="conv-event-1",
            payload={
                "title": f"{NANJING}周末慢游",
                "destination_city": NANJING,
                "budget": 1800,
                "tags": [WEEKEND, FOOD],
                "summary": "高铁优先，轻松，美食历史。",
            },
        ),
        authorization=authorization,
        db=db_session,
    )
    body = json.loads(response.body)
    events = db_session.query(TravelPreferenceEvent).filter(TravelPreferenceEvent.user_key == str(auth.user.id)).all()

    assert body["code"] == 0
    assert any("收藏" in item for item in body["data"]["behavior_signals"])
    assert NANJING in body["data"]["preferred_cities"]
    assert any(item.source_type == "favorite_on" for item in events)


def test_workspace_preference_timeline_route_returns_undoable_items(db_session) -> None:
    """画像时间线应把可逆动作聚合出来，并标明可撤销。"""

    auth = _create_logged_user(db_session)
    authorization = _auth_header(auth.access_token)

    workspace_api.submit_preference_feedback(
        PreferenceFeedbackRequest(
            dimension="transport",
            value=HIGH_SPEED_RAIL,
            action="set_common",
            conversation_id="conv-timeline-1",
        ),
        authorization=authorization,
        db=db_session,
    )

    response = workspace_api.get_preference_profile_timeline(
        conversation_id="conv-timeline-1",
        limit=10,
        authorization=authorization,
        db=db_session,
    )
    body = json.loads(response.body)

    assert body["code"] == 0
    assert body["data"]["items"]
    assert body["data"]["items"][0]["can_undo"] is True
    assert "设为常用" in body["data"]["items"][0]["title"]


def test_workspace_preference_timeline_undo_route_reverts_profile_and_marks_item(db_session) -> None:
    """撤销接口应能回滚最近一次画像动作，并让时间线显示已撤销。"""

    auth = _create_logged_user(db_session)
    authorization = _auth_header(auth.access_token)

    workspace_api.submit_preference_feedback(
        PreferenceFeedbackRequest(
            dimension="interest",
            value=FOOD,
            action="session_only",
            conversation_id="conv-undo-1",
        ),
        authorization=authorization,
        db=db_session,
    )

    timeline_response = workspace_api.get_preference_profile_timeline(
        conversation_id="conv-undo-1",
        authorization=authorization,
        db=db_session,
    )
    timeline_body = json.loads(timeline_response.body)
    event_id = timeline_body["data"]["items"][0]["id"]

    undo_response = workspace_api.undo_preference_timeline_event(
        PreferenceTimelineUndoRequest(event_id=event_id, conversation_id="conv-undo-1"),
        authorization=authorization,
        db=db_session,
    )
    undo_body = json.loads(undo_response.body)

    assert undo_body["code"] == 0
    assert undo_body["data"]["timeline"]["items"][0]["is_undone"] is True
    assert FOOD not in undo_body["data"]["profile"]["session_profile"]["interest_tags"]


def test_preference_profile_supports_lock_and_blacklist_governance(db_session) -> None:
    """画像治理应支持长期锁定、加入黑名单、移除黑名单与解除锁定。"""

    service = PreferenceService(db_session, user_key="256")
    service.apply_manual_feedback(
        dimension="transport",
        value=HIGH_SPEED_RAIL,
        action="set_common",
        conversation_id="conv-governance-1",
    )

    profile = service.apply_manual_feedback(
        dimension="transport",
        value=HIGH_SPEED_RAIL,
        action="lock_long_term",
        conversation_id="conv-governance-1",
    )
    assert any(item.value == HIGH_SPEED_RAIL for item in profile.locked_items)

    profile = service.apply_manual_feedback(
        dimension="transport",
        value=HIGH_SPEED_RAIL,
        action="avoid",
        conversation_id="conv-governance-1",
    )
    assert any(item.value == HIGH_SPEED_RAIL for item in profile.blacklist_items)

    profile = service.apply_manual_feedback(
        dimension="transport",
        value=HIGH_SPEED_RAIL,
        action="remove_avoid",
        conversation_id="conv-governance-1",
    )
    assert all(item.value != HIGH_SPEED_RAIL for item in profile.blacklist_items)
    assert any(item.value == HIGH_SPEED_RAIL for item in profile.locked_items)
    assert HIGH_SPEED_RAIL in profile.long_term_profile.transport_modes

    profile = service.apply_manual_feedback(
        dimension="transport",
        value=HIGH_SPEED_RAIL,
        action="unlock_long_term",
        conversation_id="conv-governance-1",
    )
    assert all(item.value != HIGH_SPEED_RAIL for item in profile.locked_items)


def test_workspace_preference_audit_route_returns_grouped_view(db_session) -> None:
    """画像审计接口应返回治理摘要以及按维度、来源、作用域分组的结果。"""

    auth = _create_logged_user(db_session)
    authorization = _auth_header(auth.access_token)

    workspace_api.submit_preference_feedback(
        PreferenceFeedbackRequest(
            dimension="interest",
            value=FOOD,
            action="set_common",
            conversation_id="conv-audit-1",
        ),
        authorization=authorization,
        db=db_session,
    )
    workspace_api.submit_preference_feedback(
        PreferenceFeedbackRequest(
            dimension="interest",
            value=FOOD,
            action="lock_long_term",
            conversation_id="conv-audit-1",
        ),
        authorization=authorization,
        db=db_session,
    )
    workspace_api.submit_preference_behavior_event(
        PreferenceBehaviorEventRequest(
            action="memory_open",
            conversation_id="conv-audit-1",
            payload={"title": "画像中心", "summary": "用户打开画像工作台"},
        ),
        authorization=authorization,
        db=db_session,
    )

    response = workspace_api.get_preference_profile_audit(
        conversation_id="conv-audit-1",
        limit_per_group=10,
        authorization=authorization,
        db=db_session,
    )
    body = json.loads(response.body)
    dimension_items = [
        item
        for group in body["data"]["by_dimension"]
        for item in group["items"]
    ]

    assert body["code"] == 0
    assert body["data"]["summary"]["locked_total"] >= 1
    assert body["data"]["summary"]["explicit_total"] >= 1
    assert any(group["key"] == "interest" for group in body["data"]["by_dimension"])
    assert any(item["source_type"] == "manual_lock" for item in dimension_items)
    assert any(item["source_type"] == "memory_open" for item in dimension_items)


def test_workspace_preference_feedback_route_blocks_guest_mode(db_session) -> None:
    """游客模式下不允许沉淀人工画像纠正。"""
    response = workspace_api.submit_preference_feedback(
        PreferenceFeedbackRequest(
            dimension="interest",
            value=FOOD,
            polarity="positive",
        ),
        authorization=None,
        db=db_session,
    )
    body = json.loads(response.body)

    assert body["code"] == 5019


def test_auth_service_can_refresh_revoke_and_list_sessions(db_session) -> None:
    """正式鉴权链路应支持刷新令牌轮换、会话读取和注销。"""
    auth = _create_logged_user(db_session)
    service = AuthService(db_session)

    state = service.get_auth_state(auth.access_token)
    sessions = service.list_sessions(auth.user.id, current_session_id=auth.session.id)
    refreshed = service.refresh_session(auth.refresh_token, client_name="pytest-browser", user_agent="pytest-agent")

    assert state.user.id == auth.user.id
    assert state.session.id == auth.session.id
    assert len(sessions) == 1
    assert sessions[0].is_current is True
    assert refreshed.refresh_token != auth.refresh_token
    assert refreshed.access_token != auth.access_token

    service.revoke_session(refreshed.refresh_token)

    with pytest.raises(ValueError):
      service.get_auth_state(refreshed.access_token)


def test_workspace_auth_routes_support_profile_and_session_center(db_session) -> None:
    """账号中心应能读取当前登录态、修改资料并列出登录会话。"""
    auth = _create_logged_user(db_session)
    authorization = _auth_header(auth.access_token)

    me_response = workspace_api.get_auth_me(authorization=authorization, db=db_session)
    update_response = workspace_api.update_me(
        UserProfileUpdateRequest(
            display_name="Lin",
            home_city=HANGZHOU,
            travel_style=f"{RELAXED} + {HIGH_SPEED_RAIL}",
            current_password="secret123",
            new_password="secret456",
        ),
        authorization=authorization,
        db=db_session,
    )
    sessions_response = workspace_api.list_auth_sessions(authorization=authorization, db=db_session)

    me_body = json.loads(me_response.body)
    update_body = json.loads(update_response.body)
    sessions_body = json.loads(sessions_response.body)

    assert me_body["code"] == 0
    assert me_body["data"]["user"]["username"] == "xiaolin"
    assert update_body["code"] == 0
    assert update_body["data"]["display_name"] == "Lin"
    assert update_body["data"]["home_city"] == HANGZHOU
    assert sessions_body["code"] == 0
    assert sessions_body["data"]["total"] == 1

    relogin = UserService(db_session).login(
        UserLoginRequest(username="xiaolin", password="secret456"),
        client_name="pytest-2",
        user_agent="pytest-agent-2",
    )
    revoke_response = workspace_api.revoke_auth_session(
        relogin.session.id,
        authorization=authorization,
        db=db_session,
    )
    revoke_body = json.loads(revoke_response.body)

    assert revoke_body["code"] == 0


def test_user_service_creates_lists_and_registers_local_users(db_session) -> None:
    """本地用户服务应支持创建、注册、登录与默认用户初始化。"""
    service = UserService(db_session)
    default_user = service.ensure_default_user()
    created = service.create_user(
        UserCreateRequest(
            display_name="Xiaochen",
            username="xiaochen",
            password="secret123",
            home_city=SHANGHAI,
            travel_style=RELAXED,
        )
    )
    registered = service.register(
        UserCreateRequest(
            display_name="Momo",
            username="momo",
            password="secret123",
            home_city=HANGZHOU,
            travel_style=FOOD,
        ),
        client_name="pytest-register",
        user_agent="pytest-agent",
    )
    users = service.list_users()
    auth = service.login(
        UserLoginRequest(username="xiaochen", password="secret123"),
        client_name="pytest-login",
        user_agent="pytest-agent",
    )

    assert default_user.id
    assert created.display_name == "Xiaochen"
    assert registered.user.username == "momo"
    assert len(users) == 3
    assert auth.user.id == created.id
    assert auth.access_token.count(".") == 2
