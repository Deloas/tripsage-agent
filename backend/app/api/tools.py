import asyncio
import re
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.response import fail, ok
from app.db.session import get_db
from app.schemas.tools import (
    AiMapWorkbenchRequest,
    GeocodeRequest,
    PoiRequest,
    RailwayRequest,
    RouteRequest,
    WeatherRequest,
    WebSearchRequest,
)
from app.services.amap_service import AmapService
from app.services.llm_service import LlmService
from app.services.mcp_railway_service import McpRailwayService
from app.services.web_search_service import WebSearchService

router = APIRouter()

AI_MAP_MAX_POINTS = 10
AI_MAP_CONCURRENCY = 3
AI_MAP_LLM_MAX_POINTS = 8
AI_MAP_MIN_POI_SCORE = 10.0
AI_MAP_MAIN_POINT_LIMIT = 8

PLACE_SUFFIX_PATTERN = re.compile(
    r"(?:海上世界|世界之窗|欢乐海岸|东门老街|华强北商业区|海岸城|购物公园|万象天地|COCO\s*Park|OCT-LOFT|[\u4e00-\u9fa5A-Za-z0-9路]{2,32}(?:博物馆|美术馆|纪念馆|公园|景区|古镇|古城|寺|庙|塔|湾|山|园|街|巷|桥|码头|广场|夜市|市场|商圈|商业区|文化园|车站|机场|火车站|高铁站|步行街|创意园|书店|书城|乐园|天地))"
)
ENGLISH_PLACE_PATTERN = re.compile(r"\b[A-Za-z][A-Za-z0-9 .-]{1,24}(?:Park|LOFT|Loft|World|Mall|City|Bay|Town|Plaza)\b")
PLACE_STOPWORDS = {
    "上午",
    "下午",
    "晚上",
    "中午",
    "早餐",
    "午餐",
    "晚餐",
    "酒店",
    "住宿",
    "步行",
    "地铁",
    "公交",
    "打车",
    "高铁",
    "园林游览",
    "火车站",
    "机场",
    "目的地",
    "出发地",
    "第一天",
    "第二天",
    "第三天",
}
AI_MAP_GENERIC_TITLE_PATTERN = re.compile(
    r"(核心景点|代表性景点|街区漫游|本地美食|返程|夜游|抵达与放行李|抵达|放行李|文艺漫游|晚餐|午餐|早餐|室内核心景点|慢游|深度体验|城市探索|文艺与主题乐园|城市初识)"
)
AI_MAP_CONNECTOR_SPLIT_PATTERN = re.compile(r"\s*(?:、|/|／|→|->|=>|至|到|和|与|及|或)\s*")
AI_MAP_NOISE_LINE_PATTERN = re.compile(r"(微博正文|合集|特种兵|感悟|推荐|碎碎念)")
AI_MAP_TIME_RANGE_PATTERN = re.compile(r"^\s*\d{1,2}[:：]\d{2}\s*[-—~至到]?\s*\d{0,2}[:：]?\d{0,2}")
AI_MAP_DAY_WEATHER_PATTERN = re.compile(r"\d{1,2}月\d{1,2}日|多云|晴|阴|小雨|中雨|大雨|雷阵雨|阵雨|°C|℃")
AI_MAP_BUDGET_PATTERN = re.compile(r"\d+\s*[-~到至]\s*\d+\s*元|\d+\s*元")
AI_MAP_TRANSIT_NOISE_PATTERN = re.compile(r"(地铁\d+号线|\d+号线|[A-Z]?\d+出口|步行\d+分钟|打车\d+分钟|约\d+分钟)")
AI_MAP_NON_POI_PREFIX_PATTERN = re.compile(r"^(推荐|亮点|预算|提示|交通|门票|地址|日期|节奏|选项[A-Z]|⚠️)")
AI_MAP_GENERIC_PLACE_NAME_PATTERN = re.compile(r"^(历史街区|历史街|海岸线|海岸线漫步|古城|古镇|商业区|街区|夜景|文艺漫游|城市探索)$")
AI_MAP_MAIN_POI_SUFFIX_PATTERN = re.compile(
    r"(?:山顶广场|山顶|广场[A-Z]?[区馆座]?|风筝广场|雕像|游客中心|船头广场|观景平台|东门店|广场店|入口|出口|停车场)$"
)
AI_MAP_MAIN_POI_NOISE_PATTERN = re.compile(r"(?:地铁站|公交站|交叉口|出入口|停车场|检票口|进站口)")


@router.post("/tools/weather")
async def weather(payload: WeatherRequest):
    """直接查询天气工具。"""
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


@router.get("/tools/amap/client-config")
async def amap_client_config():
    """返回前端加载高德 JS 地图所需的公开配置。"""
    js_key = settings.amap_js_api_key or settings.amap_api_key
    return ok(
        {
            "provider": "amap",
            "js_api_key": js_key,
            "security_js_code": settings.amap_security_js_code,
            "configured": bool(js_key),
            "web_service_configured": AmapService().configured(),
        }
    )


@router.post("/tools/map/ai-workbench")
async def ai_map_workbench(payload: AiMapWorkbenchRequest):
    """把智能体回答中的地点解析成地图工作台结构。"""
    try:
        service = AmapService()
        candidates = await _build_ai_map_candidates(payload)
        semaphore = asyncio.Semaphore(AI_MAP_CONCURRENCY)

        points = await asyncio.gather(
            *[
                _resolve_ai_map_point(service, candidate, payload.city, semaphore)
                for candidate in candidates[: AI_MAP_MAX_POINTS * 2]
            ]
        )
        raw_points = [item for item in points if item.get("name")]
        raw_points = _filter_resolved_points(raw_points, payload.city, service.configured())
        main_points = _normalize_ai_map_points(raw_points, payload)
        points = main_points[:AI_MAP_MAIN_POINT_LIMIT]

        routes: list[dict[str, Any]] = []
        if len(points) > 1:
            routes = await asyncio.gather(
                *[
                    _resolve_ai_map_route(
                        service,
                        index + 1,
                        points[index],
                        points[index + 1],
                        payload.city,
                        payload.mode,
                        semaphore,
                    )
                    for index in range(len(points) - 1)
                ]
            )

        return ok(
            {
                "city": payload.city,
                "mode": payload.mode,
                "points": points,
                "raw_points": raw_points[:AI_MAP_MAX_POINTS],
                "routes": routes,
                "total_distance_meters": sum(item.get("distance_meters") or 0 for item in routes),
                "total_duration_minutes": sum(item.get("duration_minutes") or 0 for item in routes),
                "fallback": any(item.get("fallback") for item in [*raw_points, *routes]),
                "source": "ai_response",
                "diagnostics": {
                    "candidate_count": len(candidates),
                    "resolved_count": len(raw_points),
                    "main_point_count": len(points),
                    "has_js_key": bool(settings.amap_js_api_key or settings.amap_api_key),
                    "web_service_configured": service.configured(),
                },
            }
        )
    except Exception as exc:  # noqa: BLE001
        return fail(5003, "AI 地图工作台生成失败", {"error": str(exc)})


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
    """直接查询联网搜索工具。"""
    try:
        results = await WebSearchService(db).search(payload.query, payload.top_k)
        return ok({"items": [asdict(item) for item in results], "total": len(results)})
    except Exception as exc:  # noqa: BLE001
        return fail(5007, "联网搜索服务暂时不可用", {"error": str(exc)})


@router.get("/railway/ping")
async def railway_ping():
    """主动检查 12306 MCP。"""
    return ok(await McpRailwayService().ping())


@router.get("/amap/ping")
async def amap_ping():
    """主动检查高德接口。"""
    return ok(await AmapService().ping())


@router.get("/web-search/ping")
async def web_search_ping(db: Session = Depends(get_db)):
    """主动检查联网搜索。"""
    return ok(await WebSearchService(db).ping())


async def _build_ai_map_candidates(payload: AiMapWorkbenchRequest) -> list[dict[str, Any]]:
    """中文注释：优先信任结构化行程，再用大模型和规则补足，彻底降低地图与回答脱节的概率。"""
    render_candidates = _extract_render_plan_map_candidates(payload)
    if len(render_candidates) >= 3:
        return _dedupe_ai_map_candidates(render_candidates)[: AI_MAP_MAX_POINTS * 2]
    structured_candidates = _extract_structured_map_candidates(payload)
    if len(structured_candidates) >= 4:
        return _dedupe_ai_map_candidates(structured_candidates)[: AI_MAP_MAX_POINTS * 2]
    llm_candidates = await _extract_ai_map_candidates_with_llm(payload)
    rule_candidates = _extract_ai_map_candidates(payload)
    return _merge_ai_map_candidates([*render_candidates, *structured_candidates, *rule_candidates], llm_candidates)[
        : AI_MAP_MAX_POINTS * 2
    ]


def _extract_render_plan_map_candidates(payload: AiMapWorkbenchRequest) -> list[dict[str, Any]]:
    """中文注释：优先读取页面渲染层已经整理好的地点顺序，降低地图与攻略正文脱节的概率。"""
    view = payload.travel_plan_view
    if not view:
        return []

    candidates: list[dict[str, Any]] = []
    order = 0

    if view.map_schedule and view.map_schedule.markers:
        for marker in view.map_schedule.markers:
            name = str(marker.title or "").strip()
            if not name:
                continue
            candidates.append(
                {
                    "name": name,
                    "day": marker.day,
                    "source": "travel_plan_view",
                    "priority": 210,
                    "order": order,
                }
            )
            order += 1

    if candidates:
        return _dedupe_ai_map_candidates(candidates)

    for day in view.days:
        for point in day.route_points:
            name = str(point or "").strip()
            if not name:
                continue
            candidates.append(
                {
                    "name": name,
                    "day": day.day,
                    "source": "travel_plan_route_points",
                    "priority": 170,
                    "order": order,
                }
            )
            order += 1
        for poi in day.pois:
            name = str(poi.name or "").strip()
            if not name:
                continue
            candidates.append(
                {
                    "name": name,
                    "day": day.day,
                    "source": "travel_plan_poi",
                    "priority": 160,
                    "order": order,
                }
            )
            order += 1
    return _dedupe_ai_map_candidates(candidates)


def _extract_structured_map_candidates(payload: AiMapWorkbenchRequest) -> list[dict[str, Any]]:
    """中文注释：地图工作台优先读取结构化计划中的地点清单，不再让长文本决定主路线。"""
    plan = payload.structured_plan
    if not plan or not plan.days:
        return []

    candidates: list[dict[str, Any]] = []
    order = 0
    for day in plan.days:
        for place in day.places:
            aliases = place.aliases or []
            variants = [place.name, *aliases[:3]]
            for variant_index, variant in enumerate(variants):
                name = str(variant or "").strip()
                if not name:
                    continue
                candidates.append(
                    {
                        "name": name,
                        "day": day.day,
                        "source": "structured_plan",
                        "priority": 180 if variant_index == 0 else 150,
                        "order": order,
                    }
                )
                order += 1

        if not day.places:
            for agenda_index, agenda in enumerate(day.agenda, start=1):
                name = str(agenda.place_name or agenda.title or "").strip()
                if not name:
                    continue
                candidates.append(
                    {
                        "name": name,
                        "day": day.day,
                        "source": "structured_agenda",
                        "priority": 132,
                        "order": order + agenda_index,
                    }
                )
            order += len(day.agenda)
    return _dedupe_ai_map_candidates(candidates)


def _extract_ai_map_candidates(payload: AiMapWorkbenchRequest) -> list[dict[str, Any]]:
    """中文注释：规则兜底时仍然优先解析回答正文，再谨慎吸收结构化行程，避免把噪声细节带进地图。"""
    candidates: list[dict[str, Any]] = []
    order = 0

    def push(names: list[str], *, day: int | None, source: str, priority: int) -> None:
        nonlocal order
        for name in names:
            candidates.append(
                {
                    "name": name,
                    "day": day,
                    "source": source,
                    "priority": priority,
                    "order": order,
                }
            )
            order += 1

    push(_extract_names_from_text(payload.answer), day=None, source="answer", priority=92)

    for day in payload.itinerary:
        push(_extract_names_from_text(day.title), day=day.day, source="itinerary_day", priority=78)
        for item in day.items:
            push(_extract_names_from_text(item.title), day=day.day, source="itinerary_title", priority=88)
            if not AI_MAP_NOISE_LINE_PATTERN.search(item.detail or ""):
                push(_extract_names_from_text(item.detail), day=day.day, source="itinerary_detail", priority=58)

    return _dedupe_ai_map_candidates(candidates)


async def _extract_ai_map_candidates_with_llm(payload: AiMapWorkbenchRequest) -> list[dict[str, Any]]:
    """中文注释：让大模型只输出真实可搜索 POI，并保持游玩顺序，作为地图候选的主干来源。"""
    llm = LlmService()
    if not llm.configured():
        return []
    if not payload.answer.strip() and not payload.itinerary:
        return []

    itinerary_lines: list[str] = []
    for day in payload.itinerary[:4]:
        itinerary_lines.append(f"Day {day.day} {day.title}")
        for item in day.items[:6]:
            itinerary_lines.append(f"- {item.time} | {item.title}")

    prompt = "\n".join(
        [
            "你是旅游路线地图抽取器。",
            "请从下面攻略里提取 4 到 8 个可以直接在高德地图搜索到的真实地点，按游玩顺序输出。",
            "只保留：景点、公园、博物馆、古城古镇、海滨、步行街、商圈、创意园、书店、码头、口岸、购物中心、主题乐园、火车站/高铁站/机场。",
            "不要输出：日期、天气、预算、地铁几号线、出口编号、分钟数、餐段名称、酒店泛称、提示语、模糊区域。",
            "如果地点写成“华侨城创意文化园（OCT-LOFT）”，优先输出中文正式名“华侨城创意文化园”。",
            "如果一句里有多个地点，请拆开；如果是备选项，也可以保留。",
            '输出严格 JSON：{"items":[{"name":"莲花山公园","day":1,"source":"answer","reason":"上午核心景点"}]}',
            f"目的地城市：{payload.city or '未知'}",
            "",
            "正文：",
            payload.answer[:4200],
            "",
            "结构化行程标题：",
            "\n".join(itinerary_lines)[:1200],
        ]
    )

    data = await llm.json_chat(prompt)
    if not data or not isinstance(data.get("items"), list):
        return []

    candidates: list[dict[str, Any]] = []
    for order, item in enumerate(data.get("items", [])[:AI_MAP_LLM_MAX_POINTS]):
        if not isinstance(item, dict):
            continue
        raw_name = str(item.get("name") or "")
        names = _split_candidate_name(raw_name)
        if not names:
            continue
        day_value = item.get("day")
        day = int(day_value) if isinstance(day_value, int) or str(day_value).isdigit() else None
        for name in names:
            if not name or _looks_like_travel_advice(name):
                continue
            candidates.append(
                {
                    "name": name,
                    "day": day,
                    "source": str(item.get("source") or "llm"),
                    "priority": 110,
                    "order": order,
                }
            )
    return _dedupe_ai_map_candidates(candidates)


def _merge_ai_map_candidates(
    rule_candidates: list[dict[str, Any]],
    llm_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """中文注释：合并时优先保留大模型给出的主线地点，再让规则候选补足漏掉的点。"""
    if any(str(item.get("source")).startswith("structured") for item in rule_candidates):
        return _dedupe_ai_map_candidates([*rule_candidates, *llm_candidates])
    if len(llm_candidates) >= 4:
        return _dedupe_ai_map_candidates(llm_candidates)
    return _dedupe_ai_map_candidates([*llm_candidates, *rule_candidates])


def _dedupe_ai_map_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        candidates,
        key=lambda item: (
            -int(item.get("priority") or 0),
            int(item.get("day") or 999),
            int(item.get("order") or 0),
        ),
    )
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in ordered:
        for raw_name in _split_candidate_name(str(candidate.get("name") or "")):
            name = _clean_place_name(raw_name)
            dedupe_key = _normalize_name_for_compare(name)
            if not name or dedupe_key in seen or name in PLACE_STOPWORDS or _looks_like_travel_advice(name):
                continue
            seen.add(dedupe_key)
            unique.append({**candidate, "name": name})
    return unique


def _normalize_ai_map_points(points: list[dict[str, Any]], payload: AiMapWorkbenchRequest) -> list[dict[str, Any]]:
    """中文注释：把子点、分区和重复 POI 归并成更适合展示与路线规划的主景点。"""
    if not points:
        return []

    anchor_names = _build_structured_anchor_names(payload)
    grouped: dict[tuple[int | None, str], list[dict[str, Any]]] = {}
    for point in points:
        canonical_name = _canonicalize_point_name(point, anchor_names)
        group_key = (point.get("day"), _normalize_name_for_compare(canonical_name))
        grouped.setdefault(group_key, []).append({**point, "canonical_name": canonical_name})

    merged_points: list[dict[str, Any]] = []
    for (_day, _canonical_key), group in grouped.items():
        merged_points.append(_merge_ai_map_point_group(group))

    merged_points.sort(
        key=lambda item: (
            int(item.get("day") or 999),
            int(item.get("candidate_order") or 0),
            -float(item.get("score") or 0),
        )
    )
    return merged_points[:AI_MAP_MAIN_POINT_LIMIT]


def _build_structured_anchor_names(payload: AiMapWorkbenchRequest) -> list[str]:
    plan = payload.structured_plan
    if not plan or not plan.days:
        return []
    anchors: list[str] = []
    for day in plan.days:
        for place in day.places:
            name = _normalize_main_poi_name(str(place.name or ""))
            if name and name not in anchors:
                anchors.append(name)
    return anchors[:24]


def _canonicalize_point_name(point: dict[str, Any], anchor_names: list[str]) -> str:
    query_name = _clean_place_name(str(point.get("query") or ""))
    point_name = _clean_place_name(str(point.get("name") or ""))
    if anchor_names:
        anchor_match = _match_anchor_name(query_name or point_name, point_name, anchor_names)
        if anchor_match:
            return anchor_match

    for base_name in [query_name, point_name]:
        normalized = _normalize_main_poi_name(base_name)
        if normalized and not _looks_like_travel_advice(normalized):
            return normalized
    return query_name or point_name


def _match_anchor_name(query_name: str, point_name: str, anchor_names: list[str]) -> str | None:
    query_core = _normalize_name_for_compare(query_name)
    point_core = _normalize_name_for_compare(point_name)
    for anchor in anchor_names:
        anchor_core = _normalize_name_for_compare(anchor)
        if not anchor_core:
            continue
        if query_core and (query_core == anchor_core or query_core in anchor_core or anchor_core in query_core):
            return anchor
        if point_core and (point_core == anchor_core or point_core.startswith(anchor_core) or anchor_core in point_core):
            return anchor
    return None


def _normalize_main_poi_name(name: str) -> str:
    text = _clean_place_name(name)
    if not text:
        return ""
    text = re.sub(r"[（(].*?[）)]", "", text).strip()
    text = AI_MAP_MAIN_POI_SUFFIX_PATTERN.sub("", text).strip()
    text = re.sub(r"(?:深圳|上海|北京|广州|杭州|苏州|成都|重庆|南京|西安|长沙|武汉)(?:[一-龥]{0,6})店$", "", text).strip()
    text = re.sub(r"(?:广场店|旗舰店|总店|门店)$", "", text).strip()
    text = re.sub(r"(美食城|美食街|步行街|商圈|广场)(?:[一-龥]{1,8})$", r"\1", text).strip()
    text = re.sub(r"(深圳|上海|北京|广州|杭州|苏州|成都|重庆|南京|西安|长沙|武汉)$", "", text).strip()
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text[:40]


def _merge_ai_map_point_group(group: list[dict[str, Any]]) -> dict[str, Any]:
    sorted_group = sorted(group, key=_point_group_sort_key)
    anchor = {**sorted_group[0]}
    merged_names: list[str] = []
    for item in sorted_group:
        name = str(item.get("name") or "").strip()
        if name and name not in merged_names:
            merged_names.append(name)

    anchor["name"] = anchor.get("canonical_name") or anchor.get("name")
    anchor["merged_names"] = merged_names
    anchor["group_size"] = len(merged_names)
    anchor["is_anchor"] = True
    anchor["normalized_reason"] = "grouped_sub_pois" if len(merged_names) > 1 else "single_poi"
    return anchor


def _point_group_sort_key(point: dict[str, Any]) -> tuple[float, float, int]:
    score = float(point.get("score") or 0)
    poi_type = str(point.get("type") or "")
    name = str(point.get("name") or "")
    quality = 0.0
    if any(word in poi_type for word in ["风景名胜", "公园", "步行街", "博物馆", "古城", "古镇", "特色商业街"]):
        quality += 3.2
    if any(word in name for word in ["公园", "海上世界", "步行街", "古城", "博物馆", "创意园", "商圈"]):
        quality += 2.1
    if AI_MAP_MAIN_POI_NOISE_PATTERN.search(name):
        quality -= 6.5
    if AI_MAP_MAIN_POI_SUFFIX_PATTERN.search(name):
        quality -= 1.8
    return (-(score + quality), -float(point.get("candidate_priority") or 0), int(point.get("candidate_order") or 0))


def _filter_resolved_points(points: list[dict[str, Any]], city: str | None, configured: bool) -> list[dict[str, Any]]:
    """中文注释：再做一次结果级过滤，避免把明显错误的地点带到地图工作台。"""
    filtered: list[dict[str, Any]] = []
    target_city = _normalize_name_for_compare(city or "")
    seen: set[str] = set()
    seen_locations: set[str] = set()
    for point in points:
        name = str(point.get("name") or "")
        query = str(point.get("query") or "")
        score = float(point.get("score") or 0)
        location = str(point.get("location") or "")
        if not name or _looks_like_travel_advice(name) or _looks_like_travel_advice(query):
            continue
        if configured and point.get("fallback"):
            continue
        if score and score < AI_MAP_MIN_POI_SCORE:
            continue
        poi_city = _normalize_name_for_compare(str(point.get("city") or ""))
        if target_city and poi_city and poi_city != target_city and score < 12:
            continue
        dedupe_key = _normalize_name_for_compare(name)
        if dedupe_key in seen:
            continue
        if location and location in seen_locations:
            continue
        seen.add(dedupe_key)
        if location:
            seen_locations.add(location)
        filtered.append(point)
    return filtered


async def _resolve_ai_map_point(
    service: AmapService,
    candidate: dict[str, Any],
    city: str | None,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    """中文注释：地点解析会做关键词变体重试，并按目标城市与名称匹配度重新排序。"""
    query = str(candidate.get("name") or "").strip()
    if not query:
        return {}

    async with semaphore:
        query_variants = _build_query_variants(query, city)
        collected_pois: list[dict[str, Any]] = []
        fallback = False
        last_reason: str | None = None
        for query_variant in query_variants[:3]:
            poi_result = await service.search_poi(query_variant, city)
            fallback = fallback or bool(poi_result.get("fallback"))
            last_reason = poi_result.get("reason") or last_reason
            collected_pois.extend(poi_result.get("pois") or [])
            best_preview = _select_best_poi(query, collected_pois, city)
            if best_preview and best_preview.get("_score", 0) >= AI_MAP_MIN_POI_SCORE:
                break

    poi = _select_best_poi(query, collected_pois, city)
    if not poi:
        return {}
    location = poi.get("location") or ""
    lng, lat = _split_location(location)
    return {
        "name": poi.get("name") or query,
        "query": query,
        "day": candidate.get("day"),
        "source": candidate.get("source"),
        "candidate_order": int(candidate.get("order") or 0),
        "candidate_priority": int(candidate.get("priority") or 0),
        "city": poi.get("city") or city,
        "district": poi.get("district"),
        "address": poi.get("address"),
        "type": poi.get("type"),
        "location": location,
        "lng": lng,
        "lat": lat,
        "fallback": fallback,
        "reason": last_reason,
        "score": round(float(poi.get("_score") or 0), 2),
        "confidence": _score_to_confidence(float(poi.get("_score") or 0), fallback),
    }


async def _resolve_ai_map_route(
    service: AmapService,
    index: int,
    origin: dict[str, Any],
    destination: dict[str, Any],
    city: str | None,
    mode: str,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    """中文注释：路线查询同样采用受控并发，兼顾速度与稳定性。"""
    async with semaphore:
        route_result = await service.route(origin["name"], destination["name"], city, mode)

    return {
        "index": index,
        "origin": origin,
        "destination": destination,
        "mode": mode,
        "mode_used": route_result.get("mode_used"),
        "distance_meters": route_result.get("distance_meters") or 0,
        "duration_minutes": route_result.get("duration_minutes") or 0,
        "steps": route_result.get("steps") or [],
        "fallback": route_result.get("fallback", False),
        "reason": route_result.get("reason"),
    }


def _extract_names_from_text(text: str) -> list[str]:
    """中文注释：兼容 Markdown、小标题、路线箭头和多地点串联表达。"""
    values: list[str] = []
    for raw_line in (text or "").splitlines():
        line = _normalize_place_line(raw_line)
        if not line or AI_MAP_NOISE_LINE_PATTERN.search(line):
            continue
        values.extend(_extract_place_chunks_from_line(line))
    return values


def _normalize_place_line(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.replace("**", " ").replace("*", " ").replace("📍", " ").replace("📌", " ").replace("·", " ")
    text = text.replace("“", "\"").replace("”", "\"").replace("‘", "'").replace("’", "'")
    text = AI_MAP_TIME_RANGE_PATTERN.sub("", text)
    text = re.sub(r"^\s*[-•*]\s*", "", text)
    text = re.sub(r"^\|\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_place_chunks_from_line(line: str) -> list[str]:
    values: list[str] = []
    if not line or AI_MAP_GENERIC_TITLE_PATTERN.search(line):
        return values
    if AI_MAP_DAY_WEATHER_PATTERN.search(line) and not PLACE_SUFFIX_PATTERN.search(line):
        return values
    if AI_MAP_NON_POI_PREFIX_PATTERN.search(line) and not PLACE_SUFFIX_PATTERN.search(line):
        return values

    for matched in PLACE_SUFFIX_PATTERN.findall(line):
        values.extend(_split_candidate_name(matched))
    for matched in ENGLISH_PLACE_PATTERN.findall(line):
        values.extend(_split_candidate_name(matched))

    for separator in ["|", "｜", "：", ":"]:
        if separator in line:
            tail = line.split(separator, 1)[1].strip()
            values.extend(_split_candidate_name(tail))

    if _looks_like_explicit_place_line(line):
        values.extend(_split_candidate_name(line))
    return values


def _looks_like_explicit_place_line(line: str) -> bool:
    if PLACE_SUFFIX_PATTERN.search(line) or ENGLISH_PLACE_PATTERN.search(line):
        return True
    return any(keyword in line for keyword in ["海上世界", "世界之窗", "欢乐海岸", "东门老街", "万象天地", "海岸城", "南头古城", "购物公园"])


def _split_candidate_name(value: str) -> list[str]:
    text = _clean_place_name(value)
    if not text:
        return []
    aliases = _extract_alias_names(text)
    plain_text = re.sub(r"[（(].*?[）)]", "", text).strip()
    parts = [item.strip() for item in AI_MAP_CONNECTOR_SPLIT_PATTERN.split(plain_text) if item.strip()]
    parts.extend(aliases)
    if not parts:
        parts = [plain_text or text]
    filtered: list[str] = []
    for item in parts[:6]:
        cleaned = _clean_place_name(item)
        if cleaned and cleaned not in filtered:
            filtered.append(cleaned)
    return filtered


def _clean_place_name(value: str) -> str:
    """中文注释：清洗地点名称中的时间、序号、连接词与说明尾巴。"""
    text = re.sub(r"[#【】[\]（）()]", "", value or "").strip()
    text = re.sub(r"^Day\s*\d+\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(上午|下午|晚上|中午|早上|傍晚|夜间|午后|先去|去|前往|抵达|游览|打卡|入住|到)\s*", "", text)
    text = AI_MAP_TIME_RANGE_PATTERN.sub("", text)
    text = re.sub(r"^\d{1,2}月\d{1,2}日\s*", "", text)
    text = re.sub(r"^\d+\.\s*", "", text)
    text = re.sub(r"^(选项[A-Z][：:]?)", "", text)
    text = re.split(r"(?:提示|交通|预算|亮点|门票|推荐|地址|出口|建议)[:：]", text)[0].strip()
    text = re.split(r"[，。；;]|(?:\s+-\s+)", text)[0].strip()
    text = text.strip("\"' ")
    text = re.sub(r"\s{2,}", " ", text)
    return text[:32]


def _looks_like_travel_advice(value: str) -> bool:
    """中文注释：过滤“建议提前进站”“预算提示”等非地点表达。"""
    if not value:
        return True
    normalized = _normalize_name_for_compare(value)
    if AI_MAP_GENERIC_PLACE_NAME_PATTERN.fullmatch(normalized):
        return True
    if re.fullmatch(r"[0-9:：\-~ ]+", value):
        return True
    if re.search(r"\d+\s*分钟", value):
        return True
    if AI_MAP_DAY_WEATHER_PATTERN.search(value):
        return True
    if AI_MAP_BUDGET_PATTERN.search(value):
        return True
    if AI_MAP_TRANSIT_NOISE_PATTERN.search(value):
        return True
    if AI_MAP_GENERIC_TITLE_PATTERN.search(value):
        return True
    if len(value) <= 1:
        return True
    return any(
        word in value
        for word in [
            "不必",
            "不要",
            "建议",
            "避免",
            "提前",
            "过早",
            "赶站",
            "风险",
            "预算",
            "强度",
            "分钟",
            "进站",
            "出发",
            "抵达",
            "寄存",
            "门票",
            "步行约",
            "打车约",
            "本地特色",
            "选择一家",
            "轻松爬山",
            "购物中心附近",
            "完全不会受天气影响",
            "多云",
            "雷阵雨",
            "口碑好的餐厅",
            "附近用餐",
            "市内推荐",
            "二等座",
            "地铁站",
            "购物公园（COCO Park）或皇庭广场用餐",
            "具有",
            "多年历史",
            "海岸线漫步",
            "历史街区",
            "历史街",
            "用餐",
            "漫步",
            "逛",
            "感受",
            "探索",
        ]
    )


def _select_best_poi(query: str, pois: list[dict[str, Any]], city: str | None) -> dict[str, Any]:
    if not pois:
        return {}
    scored = [{**item, "_score": _score_poi_candidate(query, item, city)} for item in pois]
    return max(scored, key=lambda item: float(item.get("_score") or 0))


def _score_poi_candidate(query: str, poi: dict[str, Any], city: str | None) -> float:
    query_text = str(query or "").strip().lower()
    name = str(poi.get("name") or "").strip().lower()
    address = str(poi.get("address") or "").strip().lower()
    poi_type = str(poi.get("type") or "").strip().lower()
    poi_city = str(poi.get("city") or "").strip().lower()
    target_city = _normalize_name_for_compare(city or "")
    query_core = _normalize_name_for_compare(re.sub(r"[（(].*?[)）]", "", query_text))
    poi_name_core = _normalize_name_for_compare(name)

    score = 0.0
    if query_text == name:
        score += 8.5
    if query_text and query_text in name:
        score += 5.5
    if query_core and poi_name_core == query_core:
        score += 7.0
    elif query_core and (query_core.endswith(poi_name_core) or poi_name_core.endswith(query_core)):
        score += 4.5
    if query_text and query_text in address:
        score += 1.2
    if target_city:
        if _normalize_name_for_compare(poi_city) == target_city:
            score += 9.0
        elif poi_city:
            score -= 10.0
    if any(word in name for word in ["进站口", "检票口", "出入口", "停车场"]):
        score -= 6.0
    if any(word in poi_type for word in ["进站口", "出入口", "地铁站"]):
        score -= 5.5
    if any(word in name for word in ["酒店", "宾馆", "民宿", "公寓"]):
        score -= 7.5
    if any(word in poi_type for word in ["宾馆酒店", "住宿服务"]):
        score -= 7.5
    if any(word in name for word in ["公园", "博物馆", "古城", "古镇", "海上世界", "步行街", "创意园", "广场", "书店", "书城", "购物公园", "乐园"]):
        score += 1.8
    return score


def _split_location(location: str) -> tuple[float | None, float | None]:
    """把高德 location 字符串拆成经纬度。"""
    try:
        lng_text, lat_text = str(location).split(",", 1)
        return float(lng_text), float(lat_text)
    except (ValueError, TypeError):
        return None, None


def _extract_alias_names(text: str) -> list[str]:
    aliases = re.findall(r"[（(]([^()（）]{2,24})[)）]", text)
    results: list[str] = []
    for alias in aliases:
        cleaned = _clean_place_name(alias)
        if cleaned and not _looks_like_travel_advice(cleaned):
            results.append(cleaned)
    return results


def _build_query_variants(query: str, city: str | None) -> list[str]:
    variants: list[str] = []
    main_name = re.sub(r"[（(].*?[)）]", "", query).strip()
    for item in [query, main_name, *(_extract_alias_names(query))]:
        cleaned = _clean_place_name(item)
        if cleaned and cleaned not in variants:
            variants.append(cleaned)
    if city:
        for item in list(variants):
            city_item = f"{city}{item}"
            if city_item not in variants:
                variants.append(city_item)
    return variants


def _normalize_name_for_compare(value: str) -> str:
    text = re.sub(r"\s+|[\"'·\-（）()]", "", str(value or "").lower())
    return re.sub(r"(特别行政区|自治区|自治州|省|市|区|县)$", "", text)


def _score_to_confidence(score: float, fallback: bool) -> float:
    if fallback:
        return 0.35
    if score >= 14:
        return 0.96
    if score >= 10:
        return 0.9
    if score >= AI_MAP_MIN_POI_SCORE:
        return 0.76
    return 0.48
