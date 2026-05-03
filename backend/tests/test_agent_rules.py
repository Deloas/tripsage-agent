from app.agents.nodes import evaluate_local_guide_coverage, extract_slots_by_rules, infer_intent_by_rules


def test_infer_railway_intent() -> None:
    """包含高铁和车次时应识别为铁路查询。"""
    assert infer_intent_by_rules("明天杭州到南京有哪些高铁车次") == "railway_query"


def test_extract_city_slots() -> None:
    """规则槽位抽取应识别出出发地和目的地。"""
    slots = extract_slots_by_rules("上海出发去南京三天，预算800元", {})
    assert slots["origin"] == "上海"
    assert slots["destination"] == "南京"
    assert slots["budget"] == "800"


def test_local_guide_coverage_prefers_local_results_when_hits_are_strong() -> None:
    """自动模式应在本地命中质量足够时跳过联网增强。"""
    state = {
        "user_message": "南京两天一夜轻松美食行程",
        "slots": {"destination": "南京"},
        "retrieved_guides": [
            {
                "guide_id": 1,
                "title": "南京两天一夜轻松美食攻略",
                "city": "南京",
                "content": "南京两天一夜轻松美食攻略，夫子庙、老门东、南京博物院都适合慢游。",
                "score": 0.82,
                "source": {"title": "guide-1", "url": "https://example.com/1"},
            },
            {
                "guide_id": 2,
                "title": "南京周末慢游路线",
                "city": "南京",
                "content": "周末去南京可以住新街口，白天逛博物院和老门东，晚上吃小吃。",
                "score": 0.76,
                "source": {"title": "guide-2", "url": "https://example.com/2"},
            },
        ],
    }

    coverage = evaluate_local_guide_coverage(state)

    assert coverage["coverage_score"] >= 0.58
    assert coverage["needs_web_search"] is False


def test_local_guide_coverage_triggers_web_search_when_destination_misses() -> None:
    """自动模式在目标城市未被本地命中覆盖时应触发联网增强。"""
    state = {
        "user_message": "西安三天历史路线",
        "slots": {"destination": "西安"},
        "retrieved_guides": [
            {
                "guide_id": 7,
                "title": "成都三天吃喝路线",
                "city": "成都",
                "content": "成都三天主要看美食和慢节奏街区。",
                "score": 0.41,
                "source": {"title": "guide-7", "url": "https://example.com/7"},
            },
        ],
    }

    coverage = evaluate_local_guide_coverage(state)

    assert coverage["needs_web_search"] is True
    assert "目标城市" in coverage["decision_reason"]
