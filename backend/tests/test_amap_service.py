import pytest

from app.core.config import settings
from app.services.amap_service import AmapService


@pytest.mark.asyncio
async def test_amap_weather_fallback_without_key(monkeypatch: pytest.MonkeyPatch):
    """未配置高德 Key 时，天气工具应返回稳定兜底结构。"""
    monkeypatch.setattr(settings, "amap_api_key", "")
    result = await AmapService().get_weather("苏州")

    assert result["fallback"] is True
    assert result["city"] == "苏州"
    assert "weather" in result
    assert "risk_tags" in result


@pytest.mark.asyncio
async def test_amap_route_fallback_has_product_shape(monkeypatch: pytest.MonkeyPatch):
    """路线兜底结果也要保持产品可展示字段完整。"""
    monkeypatch.setattr(settings, "amap_api_key", "")
    result = await AmapService().route("苏州站", "拙政园", "苏州", "transit")

    assert result["fallback"] is True
    assert result["origin"] == "苏州站"
    assert result["destination"] == "拙政园"
    assert result["duration_minutes"] >= 1
    assert result["distance_meters"] >= 1
    assert result["mode_used"] == "driving"


def test_amap_config_status_does_not_expose_key():
    """高德诊断信息不能泄露本地 API Key。"""
    status = AmapService().config_status()

    assert status["provider"] == "amap"
    assert "api_key" not in status
    assert "AMAP_API_KEY" not in str(status)
