from app.schemas.plans import PlanVersionCreate
from app.services.plan_version_service import PlanVersionService


def _payload(version_id: str, name: str, warnings: list[str] | None = None) -> PlanVersionCreate:
    """构造最小可用版本数据，避免测试依赖真实大模型输出。"""
    return PlanVersionCreate(
        id=version_id,
        conversation_id="conv-test-001",
        name=name,
        reason="测试版本",
        created_at="2026-04-29T10:00:00",
        response={
            "conversation_id": "conv-test-001",
            "answer": "测试回答",
            "intent": "plan_trip",
            "cards": [],
            "itinerary": [{"day": 1, "title": name, "items": []}],
            "tool_calls": [{"tool_name": "amap_weather", "status": "success"}],
            "sources": [{"title": "本地攻略"}],
            "warnings": warnings or [],
            "decision_modules": [],
        },
    )


def test_plan_version_save_and_list(db_session) -> None:
    """方案版本应能保存并按会话读取。"""
    service = PlanVersionService(db_session)
    service.save(_payload("version-a", "初版"))
    service.save(_payload("version-b", "优化版 1"))

    items = service.list_by_conversation("conv-test-001")

    assert len(items) == 2
    assert items[0].name == "初版"
    assert items[1].response["itinerary"][0]["title"] == "优化版 1"


def test_plan_version_compare(db_session) -> None:
    """版本对比应返回工具、来源、风险和行程维度的差异指标。"""
    service = PlanVersionService(db_session)
    service.save(_payload("version-a", "初版"))
    service.save(_payload("version-b", "优化版 1", warnings=["雨天风险"]))

    result = service.compare("version-a", "version-b")

    assert result.base_id == "version-a"
    assert result.target_id == "version-b"
    assert result.metrics["warning_delta"] == 1
    assert result.highlights


def test_plan_version_export_and_share(db_session) -> None:
    """方案版本应支持导出和创建本地分享页。"""
    service = PlanVersionService(db_session)
    service.save(_payload("version-export", "导出版"))

    markdown = service.export("version-export", "markdown")
    html = service.export("version-export", "html")
    share = service.create_share("version-export")
    loaded = service.get_share(share.id)

    assert markdown.filename.endswith(".md")
    assert "# 旅行方案 - 导出版" in markdown.content
    assert html.filename.endswith(".html")
    assert share.version_id == "version-export"
    assert loaded.response["answer"] == "测试回答"
