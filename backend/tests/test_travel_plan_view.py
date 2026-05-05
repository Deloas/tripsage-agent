from app.agents.nodes import _build_travel_plan_view, _normalize_structured_plan


def test_travel_plan_view_builds_page_level_modules() -> None:
    """中文注释：页面级攻略渲染数据应直接由结构化计划产出。"""
    payload = {
        "city": "杭州",
        "trip_summary": "两天主打西湖夜景、美食和轻松漫游。",
        "planning_style": "轻松慢游",
        "budget_hint": "总预算控制在 2000 元左右更舒适。",
        "transport_hint": "优先高铁抵达，市内以地铁和步行为主。",
        "rainy_day_hint": "如遇下雨，先转室内博物馆和茶馆。",
        "risk_hint": "节假日热门点位建议预约并错峰。",
        "days": [
            {
                "day": 1,
                "title": "西湖主线",
                "summary": "白天看湖景，夜间收束到夜景和美食。",
                "route_digest": "西湖景区 -> 河坊街",
                "agenda": [
                    {
                        "time": "上午",
                        "title": "西湖景区",
                        "detail": "围绕西湖慢走，保留拍照和休息时间。",
                        "place_name": "西湖景区",
                        "transport_hint": "地铁后步行进入湖滨区域",
                    }
                ],
                "places": [
                    {
                        "name": "西湖景区",
                        "aliases": [],
                        "intro": "杭州最核心的城市名片，适合慢走看景。",
                        "category": "scenic",
                        "stay_minutes": 180,
                        "transport_hint": "地铁后步行进入湖滨区域",
                        "order": 1,
                    },
                    {
                        "name": "河坊街",
                        "aliases": [],
                        "intro": "适合接续夜游和本地小吃。",
                        "category": "food",
                        "stay_minutes": 120,
                        "transport_hint": "晚间打车或公交衔接更方便",
                        "order": 2,
                    },
                ],
            }
        ],
    }
    state = {
        "slots": {"destination": "杭州", "budget": "2000"},
        "retrieved_guides": [{"title": "杭州两日游", "content": "..."}, {"title": "西湖夜景攻略", "content": "..."}],
        "web_items": [{"title": "杭州天气"}, {"title": "杭州高铁"}],
        "decision_modules": [{"title": "交通建议"}, {"title": "预算提示"}],
    }

    plan = _normalize_structured_plan(payload, state)
    assert plan is not None

    view = _build_travel_plan_view(plan, state)

    assert view is not None
    assert view.overview.title == "杭州1日旅行方案"
    assert view.days[0].pois[0].name == "西湖景区"
    assert view.map_schedule is not None
    assert view.map_schedule.markers[0].title == "西湖景区"
    assert view.budget is not None
    assert view.budget.items
    assert view.supplements
