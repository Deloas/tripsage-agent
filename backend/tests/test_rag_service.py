import json

from app.db.models import GuideImportRecord
from app.schemas.guides import GuideCreateRequest, GuideUpdateRequest
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


def test_update_guide_rebuilds_detail_chunks_and_places(db_session, monkeypatch) -> None:
    """编辑已入库攻略后，应重建正文、地点抽取和向量切片。"""

    deleted_chunk_ids: list[str] = []
    indexed_chunks: list[dict] = []

    def fake_delete_chunks(self, chunk_ids):
        deleted_chunk_ids.extend(chunk_ids)
        return True

    def fake_index_chunks(self, chunks):
        indexed_chunks.extend(chunks)
        return True

    monkeypatch.setattr(VectorStoreService, "delete_chunks", fake_delete_chunks)
    monkeypatch.setattr(VectorStoreService, "index_chunks", fake_index_chunks)

    result = GuideIngestService(db_session).add_guide(
        GuideCreateRequest(
            title="苏州基础攻略",
            content="苏州一日游，先去拙政园，再去平江路。适合轻松拍照。",
            source_type="manual",
            source_url="https://example.com/suzhou-old",
        )
    )

    update_result = GuideIngestService(db_session).update_guide(
        int(result["guide_id"]),
        GuideUpdateRequest(
            title="杭州西湖一日游攻略",
            content="杭州一日游，上午去西湖，下午去灵隐寺。推荐地铁出行，人均300元，适合轻松慢游。",
            category="杭州",
            source_url="https://example.com/hangzhou-new",
            structured={
                "city": "杭州",
                "days": 1,
                "budget_min": 300,
                "budget_max": 300,
                "scenic_spots": ["西湖", "灵隐寺"],
                "transport_modes": ["地铁"],
                "travel_style_tags": ["轻松"],
            },
        ),
    )

    detail = RagService(db_session).get_guide_detail(int(result["guide_id"]))

    assert update_result is not None
    assert update_result["city"] == "杭州"
    assert detail is not None
    assert detail["title"] == "杭州西湖一日游攻略"
    assert detail["source_url"] == "https://example.com/hangzhou-new"
    assert detail["structured"]["budget_range"] == "约300元"
    assert "西湖" in detail["structured"]["scenic_spots"]
    assert deleted_chunk_ids
    assert indexed_chunks


def test_rag_service_guide_detail_includes_import_audit(db_session, monkeypatch) -> None:
    """攻略详情应附带导入质检信息，供前端展示图片与差异对照。"""

    monkeypatch.setattr(VectorStoreService, "index_chunks", lambda self, chunks: True)

    result = GuideIngestService(db_session).add_guide(
        GuideCreateRequest(
            title="鏉窞瑗挎箹涓€鏃ユ父鏀荤暐",
            content=(
                "鏉窞瑗挎箹涓€鏃ユ父鏀荤暐\n"
                "榫欑繑妗ュ湴閾佺珯鍑哄彂锛屽厛鍘讳簩鍏洯鐮佸ご锛屽啀鍘讳笁娼嵃鏈堛€?\n"
                "棰勭畻绾?00 鍏冿紝閫傚悎杞绘澗鎱㈡父銆?"
            ),
            source_type="manual",
            source_url="https://example.com/import-audit-guide",
        )
    )

    db_session.add(
        GuideImportRecord(
            url="https://example.com/import-audit-guide",
            status="indexed",
            mode="link",
            title="鏉窞瑗挎箹涓€鏃ユ父鏀荤暐",
            guide_id=int(result["guide_id"]),
            quality_json=json.dumps({"score": 88, "grade": "A"}, ensure_ascii=False),
            diagnostics_json=json.dumps(
                {
                    "fetch_method": "browser_render",
                    "image_count": 2,
                    "image_urls": [
                        "https://example.com/images/westlake-1.jpg",
                        "https://example.com/images/westlake-2.jpg",
                    ],
                    "source_preview_lines": [
                        "榫欑繑妗ュ湴閾佺珯鍑哄彂锛屽厛鍘讳簩鍏洯鐮佸ご",
                        "鍐嶅幓涓夋江鍗版湀锛屾渶鍚庡幓鑺辨腐瑙傞奔",
                    ],
                    "final_preview_lines": [
                        "榫欑繑妗ュ湴閾佺珯鍑哄彂锛屽厛鍘讳簩鍏洯鐮佸ご",
                        "鍐嶅幓涓夋江鍗版湀锛岄绠楃害 200 鍏?",
                    ],
                },
                ensure_ascii=False,
            ),
        )
    )
    db_session.commit()

    detail = RagService(db_session).get_guide_detail(int(result["guide_id"]))

    assert detail is not None
    assert detail["import_audit"] is not None
    assert detail["import_audit"]["image_urls"][0] == "https://example.com/images/westlake-1.jpg"
    assert detail["import_audit"]["confidence"]["overall"] > 0
    assert any(item["type"] == "shared" for item in detail["import_audit"]["diff_blocks"])
