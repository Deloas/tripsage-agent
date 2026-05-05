from app.services.preference_service import PreferenceService


def test_preference_profile_separates_origin_and_destination(db_session) -> None:
    """用户说“从上海去杭州”时，只把杭州沉淀为目的地偏好。"""
    service = PreferenceService(db_session, user_key="route-precision")

    profile = service.learn_from_interaction(
        "我想从上海去杭州玩两天，预算2000左右，不想太赶，优先高铁，喜欢美食和夜景，别安排太多爬山。",
        {"answer": "", "cards": []},
        conversation_id="conv-route-precision",
    )

    assert "杭州" in profile.preferred_cities
    assert "上海" not in profile.preferred_cities
    assert profile.budget_range == "1700-2300元"
    assert "高铁" in profile.transport_modes
    assert "轻松" in profile.pace_tags
    assert "美食" in profile.interest_tags
    assert "夜景" in profile.interest_tags
    assert "历史" not in profile.interest_tags
    assert any("爬山" in item for item in profile.negative_preferences)
    assert "上海" not in profile.recommendation_hint
    assert "历史" not in profile.recommendation_hint
