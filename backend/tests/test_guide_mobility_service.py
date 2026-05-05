from app.schemas.guides import GuideCreateRequest
from app.services.guide_ingest_service import GuideIngestService
from app.services.guide_mobility_service import GuideMobilityService
from app.services.vector_store_service import VectorStoreService


def test_guide_route_preview_builds_map_and_railway_seed(db_session, monkeypatch) -> None:
    """攻略详情页应能把抽取地点生成路线预览，并给铁路工作台准备目的地条件。"""
    monkeypatch.setattr(VectorStoreService, "index_chunks", lambda self, chunks: True)

    result = GuideIngestService(db_session).add_guide(
        GuideCreateRequest(
            title="杭州两天一夜攻略",
            content=(
                "杭州两天一夜攻略，人均900元。第一天从杭州东站到西湖、河坊街，"
                "第二天去灵隐寺，适合轻松拍照和夜景。优先高铁到达。"
            ),
            source_type="manual",
            source_url="https://example.com/hangzhou-mobility",
        )
    )

    import asyncio

    preview = asyncio.run(GuideMobilityService(db_session).build_route_preview(int(result["guide_id"])))

    assert preview is not None
    assert preview["guide_id"] == int(result["guide_id"])
    assert preview["city"] == "杭州"
    assert len(preview["nodes"]) >= 2
    assert len(preview["routes"]) >= 1
    assert preview["total_duration_minutes"] > 0
    assert preview["railway_seed"]["destination"] == "杭州"
    assert preview["railway_seed"]["destination_station"]
