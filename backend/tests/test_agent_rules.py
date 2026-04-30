from app.agents.nodes import extract_slots_by_rules, infer_intent_by_rules


def test_infer_railway_intent() -> None:
    """包含高铁和车次时应识别为铁路查询。"""
    assert infer_intent_by_rules("明天杭州到南京有哪些高铁车次") == "railway_query"


def test_extract_city_slots() -> None:
    """规则槽位抽取应识别出出发地和目的地。"""
    slots = extract_slots_by_rules("上海出发去南京三天，预算800元", {})
    assert slots["origin"] == "上海"
    assert slots["destination"] == "南京"
    assert slots["budget"] == "800"

