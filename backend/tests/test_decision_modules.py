from app.agents.nodes import build_decision_modules


def test_decision_modules_have_product_sections() -> None:
    """规划结果应拆成产品化决策模块，而不是只有长文本。"""
    modules = build_decision_modules(
        {
            "slots": {"budget": "1200", "days": "2"},
            "weather_result": {"weather": "小雨", "risk_tags": ["雨雪天气"]},
            "railway_result": {
                "date": "2026-05-01",
                "fallback": False,
                "trains": [{"train_no": "G1"}],
            },
            "route_result": {"duration_minutes": 18},
            "retrieved_guides": [{"title": "苏州攻略"}],
            "web_items": [],
        }
    )

    assert [module.type for module in modules] == [
        "transport",
        "rainy_day",
        "intensity",
        "budget",
        "risk",
    ]
    assert modules[0].meta["train_count"] == 1
    assert modules[1].level == "warn"
