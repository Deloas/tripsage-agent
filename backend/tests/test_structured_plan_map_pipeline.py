from app.agents.nodes import (
    _build_structured_plan_fallback,
    _build_itinerary_from_structured_plan,
    _normalize_structured_plan,
    _render_structured_answer,
    _rerank_guides_for_destination,
)
from app.api.tools import _extract_structured_map_candidates
from app.schemas.tools import AiMapWorkbenchRequest


def test_structured_plan_normalization_and_rendering() -> None:
    """结构化规划应同时服务详细行程、精简地点摘要和稳定文本回复。"""
    payload = {
        "city": "深圳",
        "trip_summary": "两天轻松线，重点放在夜景、美食和海滨散步。",
        "planning_style": "轻松慢游",
        "budget_hint": "总预算控制在 1800 元左右更舒适。",
        "transport_hint": "优先高铁到达，市内地铁配合短打车。",
        "rainy_day_hint": "有雨时把海边段前置，下午切到室内馆区。",
        "risk_hint": "热门景点周末人流较大，预留机动时间。",
        "days": [
            {
                "day": 1,
                "title": "城市初识与夜景线",
                "summary": "上午轻松开场，下午海滨散步，晚上夜景收束。",
                "route_digest": "莲花山公园 -> 深圳博物馆 -> 深圳湾公园 -> 海上世界",
                "agenda": [
                    {
                        "time": "上午",
                        "title": "莲花山公园",
                        "detail": "轻松登高看城市天际线，适合作为开场。",
                        "place_name": "莲花山公园",
                        "transport_hint": "地铁到少年宫站后步行",
                    },
                    {
                        "time": "下午",
                        "title": "深圳湾公园",
                        "detail": "沿海散步，傍晚光线舒服。",
                        "place_name": "深圳湾公园",
                        "transport_hint": "地铁 9 号线直达",
                    },
                ],
                "places": [
                    {
                        "name": "莲花山公园",
                        "aliases": [],
                        "intro": "轻松登高看福田中轴线。",
                        "category": "scenic",
                        "stay_minutes": 120,
                        "transport_hint": "地铁到少年宫站",
                        "order": 1,
                    },
                    {
                        "name": "深圳湾公园",
                        "aliases": [],
                        "intro": "适合傍晚看海和慢慢散步。",
                        "category": "scenic",
                        "stay_minutes": 120,
                        "transport_hint": "地铁 9 号线",
                        "order": 2,
                    },
                ],
            }
        ],
    }

    plan = _normalize_structured_plan(payload, {"slots": {"destination": "深圳"}})

    assert plan is not None
    assert plan.city == "深圳"
    assert plan.days[0].places[0].name == "莲花山公园"
    assert plan.days[0].agenda[0].place_name == "莲花山公园"

    itinerary = _build_itinerary_from_structured_plan(plan)
    assert itinerary is not None
    assert itinerary[0].items[0]["title"] == "莲花山公园"

    answer = _render_structured_answer(plan, {"slots": {"destination": "深圳"}})
    assert "Day 1 地点清单" in answer
    assert "莲花山公园" in answer
    assert "深圳湾公园" in answer


def test_structured_map_candidates_prioritize_plan_places() -> None:
    """地图候选应优先直接读取结构化地点清单，而不是回退到长文本猜测。"""
    payload = AiMapWorkbenchRequest.model_validate(
        {
            "city": "深圳",
            "answer": "",
            "itinerary": [],
            "structured_plan": {
                "city": "深圳",
                "trip_summary": "深圳轻松两日游",
                "days": [
                    {
                        "day": 1,
                        "title": "海滨与夜景线",
                        "summary": "以海滨和夜景为主。",
                        "route_digest": "深圳湾公园 -> 海上世界",
                        "agenda": [],
                        "places": [
                            {
                                "name": "深圳湾公园",
                                "aliases": [],
                                "intro": "海边慢走。",
                                "order": 1,
                            },
                            {
                                "name": "华侨城创意文化园",
                                "aliases": ["OCT-LOFT"],
                                "intro": "适合文艺漫游。",
                                "order": 2,
                            },
                        ],
                    }
                ],
            },
            "mode": "driving",
        }
    )

    candidates = _extract_structured_map_candidates(payload)

    assert candidates
    assert candidates[0]["source"] == "structured_plan"
    assert any(item["name"] == "深圳湾公园" for item in candidates)
    assert any(item["name"] == "华侨城创意文化园" for item in candidates)
    assert any(item["name"] == "OCT-LOFT" for item in candidates)


def test_structured_fallback_prefers_real_place_pool() -> None:
    """兜底结构应优先使用真实地点池，而不是退回到抽象占位词。"""
    state = {
        "slots": {"destination": "深圳", "days": "2"},
        "planning_place_pool": [
            {"name": "莲花山公园", "reason": "高德城市候选：公园"},
            {"name": "深圳湾公园", "reason": "高德城市候选：夜景"},
            {"name": "海上世界", "reason": "高德城市候选：夜景"},
            {"name": "南头古城", "reason": "高德城市候选：古城"},
        ],
        "retrieved_guides": [],
        "context": {},
    }

    plan = _build_structured_plan_fallback(state)

    assert plan is not None
    assert plan.days
    all_places = [place.name for day in plan.days for place in day.places]
    assert "莲花山公园" in all_places
    assert "海上世界" in all_places
    assert "核心景点慢游" not in all_places


def test_destination_rerank_filters_false_positive_guides() -> None:
    """目标城市重排应压低被其它城市内容带偏的攻略片段。"""
    class DummyGuide:
        def __init__(self, payload: dict) -> None:
            self.payload = payload
            self.score = payload["score"]

        def model_dump(self) -> dict:
            return {**self.payload, "score": self.score}

    guides = [
        DummyGuide(
            {
                "guide_id": 1,
                "chunk_id": "a",
                "title": "深圳两日游夜景美食攻略",
                "city": "深圳",
                "content": "深圳湾公园、海上世界、莲花山公园都很适合两天慢游。",
                "score": 0.42,
            }
        ),
        DummyGuide(
            {
                "guide_id": 2,
                "chunk_id": "b",
                "title": "粤港澳合集",
                "city": "广州",
                "content": "广州香港澳门来回，中转深圳，适合卧铺出发。",
                "score": 0.66,
            }
        ),
    ]

    ranked = _rerank_guides_for_destination(guides, "深圳")

    assert ranked
    assert ranked[0].model_dump()["title"] == "深圳两日游夜景美食攻略"
