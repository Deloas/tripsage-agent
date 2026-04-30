import re
import json

import pytest

from app.core.config import settings
from app.services.mcp_railway_service import McpRailwayService


def test_railway_tool_safety_filter():
    """12306 MCP 只允许查询类工具，屏蔽登录支付等风险工具。"""
    service = McpRailwayService()

    assert service.is_safe_tool("query_tickets")
    assert service.is_safe_tool("station_search")
    assert not service.is_safe_tool("login")
    assert not service.is_safe_tool("submit_order")
    assert not service.is_safe_tool("pay_ticket")


def test_railway_date_normalization():
    """常见中文日期应转换为 12306 更容易接受的日期格式。"""
    service = McpRailwayService()

    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", service.normalize_date("明天"))
    assert service.normalize_date("2026-05-01") == "2026-05-01"
    assert service.normalize_date("2026/05/01") == "2026-05-01"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", service.normalize_date("待确认日期"))


@pytest.mark.asyncio
async def test_railway_query_fallback_when_live_disabled(monkeypatch: pytest.MonkeyPatch):
    """默认不启动外部 MCP，铁路查询应返回稳定兜底结构。"""
    monkeypatch.setattr(settings, "mcp_12306_allow_live", False)
    result = await McpRailwayService().query_trains("杭州", "南京", "明天")

    assert result["fallback"] is True
    assert result["origin"] == "杭州"
    assert result["destination"] == "南京"
    assert result["trains"]
    assert "购票" in result["notice"]


def test_railway_status_does_not_expose_secret():
    """MCP 诊断信息不能泄露 token 或 key。"""
    status = McpRailwayService().config_status()

    assert "MODELSCOPE_TOKEN" not in str(status)
    assert "api_key" not in str(status).lower()


def test_railway_extracts_structured_train_rows():
    """真实 MCP 返回 JSON 文本时，应保留前端需要的车次字段。"""
    service = McpRailwayService()
    payload = {
        "type": "text",
        "text": json.dumps(
            {
                "success": True,
                "trains": [
                    {
                        "train_no": "G1862",
                        "from_station": "杭州东",
                        "to_station": "南京南",
                        "start_time": "09:10",
                        "arrive_time": "10:45",
                        "duration": "01:35",
                        "seats": {"second_class": "有"},
                    }
                ],
            },
            ensure_ascii=False,
        ),
    }

    rows = service._extract_train_rows(json.dumps(payload, ensure_ascii=False))

    assert rows == [
        {
            "train_no": "G1862",
            "from_station": "杭州东",
            "to_station": "南京南",
            "start_time": "09:10",
            "arrive_time": "10:45",
            "duration": "01:35",
            "seats": {"second_class": "有"},
        }
    ]
