from app.schemas.guides import GuideCreateRequest
from app.services.guide_ingest_service import GuideIngestService, build_structured_guide_data
from app.services.rag_service import RagService, tokenize_query
from app.services.vector_store_service import VectorStoreService


def test_tokenize_query_keeps_city_and_travel_terms() -> None:
    """中文长句检索应保留城市和旅行主题词。"""
    tokens = tokenize_query("上海到苏州两天一夜怎么玩？顺便查铁路和天气")

    assert "上海" in tokens
    assert "苏州" in tokens
    assert "两天一夜" in tokens
    assert "铁路" in tokens


def test_build_structured_guide_data_extracts_budget_transport_and_places() -> None:
    """结构化抽取应识别预算、交通、住宿和玩法标签。"""
    content = """
    南京两天一夜攻略，人均800-1200元。
    推荐住在新街口附近，地铁和打车都方便。
    第一天去夫子庙、老门东，晚上逛夜市吃小吃。
    第二天去南京博物院和中山陵，适合轻松慢游和历史人文路线。
    """

    structured = build_structured_guide_data("南京两天一夜攻略", content)

    assert structured["city"] == "南京"
    assert structured["days"] == 2
    assert structured["budget_min"] == 800
    assert structured["budget_max"] == 1200
    assert "地铁" in structured["transport_modes"]
    assert "打车" in structured["transport_modes"]
    assert any("新街口附近" in item for item in structured["lodging_suggestions"])
    assert "轻松" in structured["travel_style_tags"]
    assert "历史人文" in structured["travel_style_tags"]


def test_rag_service_guide_detail_returns_structured_payload(db_session, monkeypatch) -> None:
    """攻略详情接口应返回可直接给前端使用的结构化字段。"""

    monkeypatch.setattr(VectorStoreService, "index_chunks", lambda self, chunks: True)

    payload = GuideCreateRequest(
        title="杭州两天一夜攻略",
        content=(
            "杭州两天一夜攻略，人均900元。推荐住在西湖附近。"
            "第一天西湖、河坊街，第二天灵隐寺。地铁出行方便，也适合轻松拍照。"
        ),
        source_type="manual",
        source_url="https://example.com/hangzhou-guide",
    )
    result = GuideIngestService(db_session).add_guide(payload)
    detail = RagService(db_session).get_guide_detail(int(result["guide_id"]))

    assert detail is not None
    assert detail["structured"]["budget_range"] == "约900元"
    assert "西湖" in detail["structured"]["scenic_spots"]
    assert "地铁" in detail["structured"]["transport_modes"]
    assert detail["structured"]["days"] == 2
