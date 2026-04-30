from dataclasses import asdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.response import fail, ok
from app.db.session import get_db
from app.schemas.tools import (
    GeocodeRequest,
    PoiRequest,
    RailwayRequest,
    RouteRequest,
    WeatherRequest,
    WebSearchRequest,
)
from app.services.amap_service import AmapService
from app.services.mcp_railway_service import McpRailwayService
from app.services.web_search_service import WebSearchService

router = APIRouter()


@router.post("/tools/weather")
async def weather(payload: WeatherRequest):
    """直接查询天气工具，主要用于前端调试和答辩展示。"""
    try:
        result = await AmapService().get_weather(payload.city, payload.date)
        return ok(result)
    except Exception as exc:  # noqa: BLE001
        return fail(5002, "天气服务暂时不可用", {"error": str(exc)})


@router.post("/tools/map/poi")
async def poi(payload: PoiRequest):
    """直接查询 POI 工具。"""
    try:
        result = await AmapService().search_poi(payload.keyword, payload.city)
        return ok(result)
    except Exception as exc:  # noqa: BLE001
        return fail(5003, "地图地点服务暂时不可用", {"error": str(exc)})


@router.post("/tools/map/geocode")
async def geocode(payload: GeocodeRequest):
    """直接查询地理编码工具。"""
    try:
        result = await AmapService().geocode(payload.address, payload.city)
        return ok(result)
    except Exception as exc:  # noqa: BLE001
        return fail(5003, "地图地理编码服务暂时不可用", {"error": str(exc)})


@router.post("/tools/map/route")
async def route(payload: RouteRequest):
    """直接查询路线工具。"""
    try:
        result = await AmapService().route(payload.origin, payload.destination, payload.city, payload.mode)
        return ok(result)
    except Exception as exc:  # noqa: BLE001
        return fail(5003, "地图路线服务暂时不可用", {"error": str(exc)})


@router.post("/tools/railway")
async def railway(payload: RailwayRequest):
    """直接查询铁路工具。"""
    try:
        result = await McpRailwayService().query_trains(payload.origin, payload.destination, payload.date)
        return ok(result)
    except Exception as exc:  # noqa: BLE001
        return fail(5004, "12306 MCP 服务暂时不可用", {"error": str(exc)})


@router.post("/tools/web-search")
async def web_search(payload: WebSearchRequest, db: Session = Depends(get_db)):
    """直接查询联网搜索工具，供前端调试和智能体效果验收。"""
    try:
        results = await WebSearchService(db).search(payload.query, payload.top_k)
        return ok({"items": [asdict(item) for item in results], "total": len(results)})
    except Exception as exc:  # noqa: BLE001
        return fail(5007, "联网搜索服务暂时不可用", {"error": str(exc)})


@router.get("/railway/ping")
async def railway_ping():
    """主动检查 12306 MCP 配置和安全查询工具。"""
    return ok(await McpRailwayService().ping())


@router.get("/amap/ping")
async def amap_ping():
    """主动检查高德天气和地图接口配置。"""
    return ok(await AmapService().ping())


@router.get("/web-search/ping")
async def web_search_ping(db: Session = Depends(get_db)):
    """主动检查联网搜索配置和网络可用性。"""
    return ok(await WebSearchService(db).ping())
