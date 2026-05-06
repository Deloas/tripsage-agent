from app.agents.nodes import _build_travel_plan_view, _normalize_structured_plan, _should_keep_rich_answer


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


def test_should_reject_rich_answer_with_empty_place_sections() -> None:
    """中文注释：地点标题存在但内容为空时，不应直接把富文本正文返回给前端。"""
    payload = {
        "city": "深圳",
        "trip_summary": "两天深圳慢节奏方案。",
        "planning_style": "周末轻松游",
        "budget_hint": "预算 2000 元左右。",
        "transport_hint": "优先高铁与地铁。",
        "rainy_day_hint": "下雨时优先室内场馆。",
        "risk_hint": "热门海边点位注意错峰。",
        "days": [
            {
                "day": 1,
                "title": "海边与夜景",
                "summary": "白天海边，晚上夜景。",
                "route_digest": "深圳湾公园 -> 欢乐海岸",
                "agenda": [
                    {
                        "time": "下午",
                        "title": "深圳湾公园",
                        "detail": "适合散步看海。",
                        "place_name": "深圳湾公园",
                    }
                ],
                "places": [
                    {
                        "name": "深圳湾公园",
                        "intro": "适合傍晚散步和看海。",
                        "order": 1,
                    },
                    {
                        "name": "欢乐海岸",
                        "intro": "适合夜景与晚餐。",
                        "order": 2,
                    },
                ],
            }
        ],
    }
    state = {"slots": {"destination": "深圳"}}
    plan = _normalize_structured_plan(payload, state)
    assert plan is not None

    bad_rich_answer = "\n".join(
        [
            "## 深圳旅行方案",
            "### Day 1 | 海边与夜景",
            "白天海边，晚上夜景。",
            "当天地点清单：",
            "当天地点简介：",
            "下午 | 深圳湾公园：适合散步看海。",
        ]
    )

    assert _should_keep_rich_answer(bad_rich_answer, plan, state) is False


def test_travel_plan_view_exposes_product_day_modules() -> None:
    """中文注释：单日攻略应同时给前端暴露美食、交通、预算、风险和地图完整度。"""
    payload = {
        "city": "Hangzhou",
        "trip_summary": "Two day city plan.",
        "budget_hint": "Total budget around 2000.",
        "transport_hint": "Prefer high speed rail and metro.",
        "rainy_day_hint": "Switch to museums when raining.",
        "risk_hint": "Book popular places in advance.",
        "days": [
            {
                "day": 1,
                "title": "Lake and night view",
                "summary": "A relaxed first day.",
                "agenda": [
                    {
                        "time": "Morning",
                        "title": "West Lake Scenic Area",
                        "detail": "Walk around the lake.",
                        "place_name": "West Lake Scenic Area",
                    },
                    {
                        "time": "Evening",
                        "title": "Hefang Street",
                        "detail": "Food and night walk.",
                        "place_name": "Hefang Street",
                    },
                ],
                "places": [
                    {"name": "West Lake Scenic Area", "intro": "Core lake view.", "order": 1},
                ],
                "route_nodes": [
                    {"name": "West Lake Scenic Area", "intro": "Core lake view.", "order": 1},
                    {"name": "Hefang Street", "intro": "Food street.", "order": 2},
                ],
                "food_plan": {
                    "lunch": "Try local noodles near the lake.",
                    "dinner": "Eat around Hefang Street.",
                    "recommendations": ["Dongpo pork", "Lotus root starch"],
                },
                "transport_plan": {
                    "city_transport": "Metro plus walking.",
                    "segments": [
                        {
                            "origin": "West Lake Scenic Area",
                            "destination": "Hefang Street",
                            "mode": "metro/walk",
                            "hint": "Use map route for exact transfer.",
                        }
                    ],
                },
                "budget_plan": {"summary": "Keep day one under 800 yuan."},
                "pace_level": "Relaxed",
                "weather_backup": ["Move lake walk to indoor museum if raining."],
                "risk_notes": ["West Lake may be crowded on holidays."],
            }
        ],
    }

    plan = _normalize_structured_plan(payload, {"slots": {"destination": "Hangzhou", "budget": "2000"}})
    assert plan is not None
    assert [node.name for node in plan.days[0].route_nodes] == ["West Lake Scenic Area", "Hefang Street"]

    view = _build_travel_plan_view(plan, {"slots": {"destination": "Hangzhou", "budget": "2000"}})

    assert view is not None
    assert view.days[0].food_plan.dinner == "Eat around Hefang Street."
    assert view.days[0].transport_plan.segments[0].destination == "Hefang Street"
    assert view.days[0].budget_plan.summary == "Keep day one under 800 yuan."
    assert view.days[0].map_node_count == 2
    assert view.map_schedule is not None
    assert [marker.title for marker in view.map_schedule.markers] == ["West Lake Scenic Area", "Hefang Street"]
