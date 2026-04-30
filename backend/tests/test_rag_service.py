from app.services.rag_service import tokenize_query


def test_tokenize_query_keeps_city_and_travel_terms() -> None:
    """中文长句检索应保留城市和旅行主题词，避免本地攻略漏召回。"""
    tokens = tokenize_query("上海到苏州两天一夜怎么玩？顺便查铁路和天气")

    assert "上海" in tokens
    assert "苏州" in tokens
    assert "两天一夜" in tokens
    assert "铁路" in tokens
