import re
import time

from langgraph.graph import END, StateGraph
from pydantic import ValidationError

from app.agents.prompts import INTENT_AND_SLOT_PROMPT, PLANNER_PROMPT, PLANNER_TEXT_PROMPT
from app.agents.state import TripAgentState
from app.schemas.chat import (
    DecisionModule,
    ItineraryBlock,
    StructuredAgendaItem,
    StructuredPlaceBrief,
    StructuredPlanDay,
    StructuredTravelPlan,
)
from app.schemas.common import ResultCard, SourceRef, ToolCallView
from app.services.amap_service import AmapService
from app.services.llm_service import LlmService
from app.services.mcp_railway_service import McpRailwayService
from app.services.rag_service import RagService, tokenize_query
from app.services.tool_log_service import ToolLogger
from app.services.web_search_service import WebSearchService


CITY_WORDS = ["北京", "上海", "南京", "苏州", "杭州", "成都", "重庆", "广州", "深圳", "厦门", "青岛", "长沙", "武汉", "西安"]
PLACE_SUFFIX_PATTERN = re.compile(
    r"[A-Za-z0-9·（）()一-龥]{2,28}(?:公园|博物馆|美术馆|古城|古镇|老街|步行街|创意园|文化园|书城|书店|商圈|商业区|广场|天地|世界之窗|欢乐海岸|海上世界|海岸城|车站|高铁站|机场|码头|沙滩|湿地公园|森林公园)"
)
PLACE_EN_PATTERN = re.compile(r"\b(?:OCT-LOFT|COCO\s*Park|K11|SKY\s*Walk|CityWalk)\b", re.IGNORECASE)
GENERIC_PLACE_WORDS = {
    "抵达与放行李",
    "核心景点慢游",
    "本地美食",
    "代表性景点",
    "街区漫游",
    "返程或夜游",
    "城市初识",
    "深度体验",
    "夜景",
    "美食",
    "古城漫游",
}
SEED_KEYWORDS_BY_STYLE = {
    "夜景": ["夜景", "海上世界", "公园"],
    "美食": ["美食街", "步行街", "商圈"],
    "历史": ["博物馆", "古城", "古镇"],
    "文艺": ["创意园", "书店", "美术馆"],
    "亲子": ["主题乐园", "公园", "海洋馆"],
}


def build_logger(state: TripAgentState) -> ToolLogger:
    """根据当前会话模式创建工具日志器。"""
    return ToolLogger(
        state["db"],
        state.get("conversation_id"),
        enabled=state.get("persist_session", True),
        memory_buffer=state.setdefault("tool_calls", []),
    )


def infer_intent_by_rules(message: str) -> str:
    """规则意图识别，保证模型不可用时也能工作。"""
    if any(word in message for word in ["高铁", "火车", "车次", "余票", "12306"]):
        return "railway_query"
    if any(word in message for word in ["天气", "下雨", "温度", "冷吗", "热吗"]):
        return "weather_advice"
    if any(word in message for word in ["添加攻略", "加入攻略", "保存攻略", "入库"]):
        return "add_guide"
    if any(word in message for word in ["怎么玩", "行程", "路线", "几天", "三天", "两天"]):
        return "itinerary_planning"
    if any(word in message for word in ["去哪", "推荐", "哪里", "目的地"]):
        return "destination_recommendation"
    return "general_qa"


def extract_slots_by_rules(message: str, context: dict) -> dict:
    """规则槽位抽取。"""
    cities = [city for city in CITY_WORDS if city in message]
    origin = context.get("home_city")
    destination = None
    if len(cities) >= 2:
        origin, destination = cities[0], cities[1]
    elif len(cities) == 1:
        destination = cities[0]

    budget_match = re.search(r"预算\s*([0-9]{2,6})|([0-9]{2,6})\s*元", message)
    days_match = re.search(r"([一二两三四五六七八九十0-9]+)\s*(?:天|日)", message)
    date = "明天" if "明天" in message else ("周末" if "周末" in message else context.get("date"))
    budget = (budget_match.group(1) or budget_match.group(2)) if budget_match else context.get("budget")

    return {
        "origin": origin,
        "destination": destination,
        "cities": cities,
        "budget": budget,
        "days": days_match.group(1) if days_match else context.get("days"),
        "date": date,
        "style": context.get("preferred_style") or [],
    }


def build_itinerary(destination: str | None, guides: list[dict], selected_guides: list[dict] | None = None) -> list[ItineraryBlock] | None:
    """在没有模型可用时也能给出稳定的行程骨架。"""
    if not destination:
        return None
    selected_guides = selected_guides or []
    guide_hint = guides[0]["content"][:80] if guides else "结合攻略库和实时工具安排一条轻松可执行的路线。"
    selected_spots = []
    if selected_guides:
        selected_spots = (selected_guides[0].get("structured") or {}).get("scenic_spots") or []
    selected_hint = f"优先吸收你主动加入的攻略线索：{'、'.join(selected_spots[:3])}。" if selected_spots else ""
    return [
        ItineraryBlock(
            day=1,
            title=f"抵达{destination}与城市初识",
            items=[
                {"time": "上午", "title": "抵达与放行李", "detail": "优先选择车站附近或核心商圈住宿，减少通勤压力。"},
                {"time": "下午", "title": "核心景点慢游", "detail": f"{guide_hint}{selected_hint}".strip()},
                {"time": "晚上", "title": "本地美食", "detail": "选择步行可达的餐饮区，避免第一天行程过满。"},
            ],
        ),
        ItineraryBlock(
            day=2,
            title=f"{destination}深度体验",
            items=[
                {"time": "上午", "title": "代表性景点", "detail": "优先安排需要体力或排队的景点。"},
                {"time": "下午", "title": "街区漫游", "detail": "根据天气调整室内外比例。"},
                {"time": "晚上", "title": "返程或夜游", "detail": "若返程，建议预留至少 90 分钟到车站。"},
            ],
        ),
    ]


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _normalize_compact(value: object) -> str:
    return re.sub(r"\s+|[\"'·\-（）()]", "", _normalize_text(value).lower())


def _coerce_days_count(value: object, default: int = 2) -> int:
    mapping = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5}
    text = _normalize_text(value)
    if text.isdigit():
        return max(1, min(int(text), 5))
    for key, number in mapping.items():
        if key in text:
            return number
    return default


def _extract_style_keywords(state: TripAgentState) -> list[str]:
    slots = state.get("slots") or {}
    style_values = [str(item) for item in (slots.get("style") or []) if str(item).strip()]
    message = state.get("user_message", "")
    keywords: list[str] = []
    for style, seed_keywords in SEED_KEYWORDS_BY_STYLE.items():
        if style in message or any(style in value for value in style_values):
            keywords.extend(seed_keywords)
    if "不想太赶" in message or "轻松" in message:
        keywords.append("公园")
    if "不爬山" in message or "别安排太多爬山" in message:
        keywords.extend(["海滨", "步行街"])
    if not keywords:
        keywords.extend(["公园", "博物馆", "步行街"])
    unique: list[str] = []
    for keyword in keywords:
        if keyword not in unique:
            unique.append(keyword)
    return unique[:5]


def _looks_generic_place(value: str) -> bool:
    text = _normalize_text(value)
    if not text:
        return True
    if text in GENERIC_PLACE_WORDS:
        return True
    if len(text) <= 1:
        return True
    return any(word in text for word in ["预算", "建议", "分钟", "打车", "地铁", "高铁", "车次", "返程", "抵达"])


def _extract_place_names(text: str) -> list[str]:
    if not text:
        return []
    names: list[str] = []
    for pattern in (PLACE_SUFFIX_PATTERN, PLACE_EN_PATTERN):
        for match in pattern.findall(text):
            name = _normalize_text(match)
            if name and not _looks_generic_place(name) and name not in names:
                names.append(name[:40])
    return names[:12]


def _normalize_seed_place_name(name: str, keyword: str) -> str:
    text = _normalize_text(name)
    if not text:
        return ""
    if len(keyword) >= 3 and keyword in text and keyword not in {"公园", "夜景", "步行街", "商圈", "美食街", "博物馆"}:
        return keyword
    text = re.sub(r"[-－].*$", "", text).strip()
    text = re.sub(r"(广场[ABCD]?[区座馆]?|风筝广场|雕像|游客中心|船头广场|广场A区|广场B区)$", "", text).strip()
    return text[:40]


def _reject_seed_place_name(name: str) -> bool:
    text = _normalize_text(name)
    return any(word in text for word in ["大厦", "商务", "写字楼", "公寓", "停车场", "出入口", "售票处"])


def _guide_destination_focus_score(item: dict, destination: str | None) -> float:
    if not destination:
        return 0.6
    title = _normalize_text(item.get("title"))
    guide_city = _normalize_text(item.get("city"))
    content = _normalize_text(item.get("content"))[:1200]
    merged = "\n".join([title, guide_city, content])
    destination_hits = merged.count(destination)
    other_cities = [city for city in CITY_WORDS if city != destination and city in merged]

    score = 0.0
    if destination in guide_city:
        score += 0.62
    if destination in title:
        score += 0.26
    if destination_hits >= 3:
        score += 0.24
    elif destination_hits == 2:
        score += 0.16
    elif destination_hits == 1:
        score += 0.08
    if destination not in guide_city and destination not in title and destination_hits <= 1 and len(other_cities) >= 2:
        score -= 0.32
    if any(word in title + content for word in ["中转", "出发", "卧铺", "直飞", "港澳", "合集"]) and destination not in title:
        score -= 0.16
    if destination and any(phrase in title + content for phrase in [f"从{destination}出发", f"坐标{destination}", f"{destination}去", f"{destination}/"]):
        score -= 0.22
    return round(max(0.0, min(1.0, score)), 4)


def _rerank_guides_for_destination(items: list, destination: str | None) -> list:
    if not destination:
        return items
    rescored: list = []
    for item in items:
        payload = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        base_score = float(payload.get("score", 0.0) or 0.0)
        focus_score = _guide_destination_focus_score(payload, destination)
        payload["destination_focus_score"] = focus_score
        combined_score = round(min(1.2, base_score * 0.62 + focus_score * 0.68), 4)
        if hasattr(item, "score"):
            item.score = combined_score
        payload["score"] = combined_score
        payload["focus_gate_passed"] = focus_score >= 0.28 or destination in _normalize_text(payload.get("title"))
        rescored.append((item, payload))

    filtered = [item for item, payload in rescored if payload["focus_gate_passed"]]
    if not filtered:
        filtered = [item for item, _payload in rescored[:2]]
    filtered.sort(key=lambda guide: getattr(guide, "score", 0.0), reverse=True)
    return filtered[:5]


def _extract_places_from_guides(guides: list[dict], destination: str | None) -> list[dict]:
    pool: list[dict] = []
    seen: set[str] = set()
    for guide in guides[:4]:
        if destination and _guide_destination_focus_score(guide, destination) < 0.72:
            continue
        merged = "\n".join(
            [
                _normalize_text(guide.get("title")),
                _normalize_text(guide.get("content"))[:1600],
            ]
        )
        for name in _extract_place_names(merged):
            key = _normalize_compact(name)
            if key in seen:
                continue
            seen.add(key)
            pool.append(
                {
                    "name": name,
                    "source": "guide",
                    "reason": f"来自本地攻略《{_normalize_text(guide.get('title'))[:32]}》",
                    "city": destination,
                }
            )
    return pool


def _extract_places_from_web_items(items: list) -> list[dict]:
    pool: list[dict] = []
    seen: set[str] = set()
    for item in items[:5]:
        title = getattr(item, "title", "") if hasattr(item, "title") else _normalize_text(item.get("title"))
        snippet = getattr(item, "snippet", "") if hasattr(item, "snippet") else _normalize_text(item.get("snippet"))
        merged = f"{title}\n{snippet}"
        for name in _extract_place_names(merged):
            key = _normalize_compact(name)
            if key in seen:
                continue
            seen.add(key)
            pool.append(
                {
                    "name": name,
                    "source": "web_search",
                    "reason": f"来自联网结果《{_normalize_text(title)[:32]}》",
                }
            )
    return pool


async def _build_amap_seed_places(state: TripAgentState) -> list[dict]:
    destination = _normalize_text((state.get("slots") or {}).get("destination"))
    if not destination:
        return []
    service = AmapService()
    if not service.configured():
        return []

    pool: list[dict] = []
    seen: set[str] = set()
    for keyword in _extract_style_keywords(state):
        result = await service.search_poi(keyword, destination)
        added_for_keyword = 0
        for poi in result.get("pois") or []:
            name = _normalize_seed_place_name(_normalize_text(poi.get("name")), keyword)
            key = _normalize_compact(name)
            if not name or key in seen or _looks_generic_place(name) or _reject_seed_place_name(name):
                continue
            seen.add(key)
            pool.append(
                {
                    "name": name,
                    "source": "amap_seed",
                    "reason": f"高德城市候选：{keyword}",
                    "city": poi.get("city") or destination,
                    "district": poi.get("district"),
                    "address": poi.get("address"),
                }
            )
            added_for_keyword += 1
            if added_for_keyword >= 2:
                break
            if len(pool) >= 10:
                return pool
    return pool


def _dedupe_place_pool(pool: list[dict]) -> list[dict]:
    unique: list[dict] = []
    seen: set[str] = set()
    for item in pool:
        name = _normalize_text(item.get("name"))
        key = _normalize_compact(name)
        if not name or key in seen or _looks_generic_place(name):
            continue
        seen.add(key)
        unique.append({**item, "name": name})
    return unique[:12]


async def _build_planning_place_pool(state: TripAgentState) -> list[dict]:
    destination = _normalize_text((state.get("slots") or {}).get("destination"))
    guide_pool = _extract_places_from_guides(state.get("retrieved_guides", []), destination or None)
    web_pool = _extract_places_from_web_items(state.get("web_items", []))
    coverage = state.get("guide_coverage") or {}
    need_amap_seed = not guide_pool or float(coverage.get("destination_focus_score", 0.0) or 0.0) < 0.72
    amap_pool = await _build_amap_seed_places(state) if need_amap_seed else []
    return _dedupe_place_pool([*amap_pool, *web_pool, *guide_pool])


def _build_planner_prompt(state: TripAgentState) -> str:
    """中文注释：把多源上下文压缩后喂给大模型，减少无关噪声对结构化输出的污染。"""
    context = state.get("context", {})
    return PLANNER_PROMPT.format(
        message=state["user_message"],
        intent=state.get("intent"),
        slots=state.get("slots"),
        guides=state.get("retrieved_guides", [])[:4],
        selected_guides=(context.get("selected_guides") or [])[:2],
        web_items=[item.__dict__ for item in state.get("web_items", [])[:4]],
        weather=state.get("weather_result"),
        railway=state.get("railway_result"),
        route=state.get("route_result"),
        edited_plan=context.get("edited_plan"),
        preference_profile=context.get("preference_profile"),
        planning_place_pool=state.get("planning_place_pool") or [],
    )


def _build_planner_text_prompt(state: TripAgentState) -> str:
    """中文注释：当直接出 JSON 不稳定时，先让模型输出一版完整文案，再做结构抽取。"""
    context = state.get("context", {})
    return PLANNER_TEXT_PROMPT.format(
        message=state["user_message"],
        intent=state.get("intent"),
        slots=state.get("slots"),
        guides=state.get("retrieved_guides", [])[:4],
        selected_guides=(context.get("selected_guides") or [])[:2],
        web_items=[item.__dict__ for item in state.get("web_items", [])[:4]],
        weather=state.get("weather_result"),
        railway=state.get("railway_result"),
        route=state.get("route_result"),
        edited_plan=context.get("edited_plan"),
        preference_profile=context.get("preference_profile"),
        planning_place_pool=state.get("planning_place_pool") or [],
    )


def _normalize_structured_plan(payload: dict, state: TripAgentState) -> StructuredTravelPlan | None:
    """中文注释：对模型输出做一次严格归一化，确保后续地图和前端都能稳定消费。"""
    if not isinstance(payload, dict):
        return None

    normalized_days: list[dict] = []
    for index, raw_day in enumerate(payload.get("days") or [], start=1):
        if not isinstance(raw_day, dict):
            continue
        places = []
        for place_index, raw_place in enumerate(raw_day.get("places") or [], start=1):
            if not isinstance(raw_place, dict):
                continue
            name = str(raw_place.get("name") or "").strip()
            if not name or _looks_generic_place(name):
                continue
            aliases = [
                str(item).strip()
                for item in (raw_place.get("aliases") or [])
                if str(item).strip() and str(item).strip() != name and not _looks_generic_place(str(item).strip())
            ]
            places.append(
                {
                    "name": name[:80],
                    "aliases": aliases[:4],
                    "intro": str(raw_place.get("intro") or "").strip()[:240],
                    "category": str(raw_place.get("category") or "").strip()[:40] or None,
                    "stay_minutes": _coerce_int(raw_place.get("stay_minutes")),
                    "transport_hint": str(raw_place.get("transport_hint") or "").strip()[:120] or None,
                    "order": _coerce_int(raw_place.get("order")) or place_index,
                }
            )

        agenda = []
        for raw_item in raw_day.get("agenda") or []:
            if not isinstance(raw_item, dict):
                continue
            title = str(raw_item.get("title") or "").strip()
            detail = str(raw_item.get("detail") or "").strip()
            if not title and not detail:
                continue
            agenda.append(
                {
                    "time": str(raw_item.get("time") or "").strip()[:40],
                    "title": title[:120],
                    "detail": detail[:600],
                    "place_name": str(raw_item.get("place_name") or "").strip()[:80] or None,
                    "transport_hint": str(raw_item.get("transport_hint") or "").strip()[:120] or None,
                }
            )

        if not places and agenda:
            places = _derive_places_from_agenda(agenda)

        normalized_days.append(
            {
                "day": _coerce_int(raw_day.get("day")) or index,
                "title": str(raw_day.get("title") or f"Day {index} 行程").strip()[:120],
                "summary": str(raw_day.get("summary") or "").strip()[:240],
                "route_digest": str(raw_day.get("route_digest") or "").strip()[:240],
                "agenda": agenda[:10],
                "places": places[:10],
            }
        )

    destination = (
        str(payload.get("city") or "").strip()
        or str((state.get("slots") or {}).get("destination") or "").strip()
        or None
    )
    if normalized_days and not any(day.get("places") for day in normalized_days):
        fallback_plan = _build_structured_plan_fallback(state)
        return fallback_plan
    if not normalized_days and destination:
        fallback_plan = _build_structured_plan_fallback(state)
        return fallback_plan

    try:
        return StructuredTravelPlan.model_validate(
            {
                "city": destination,
                "trip_summary": str(payload.get("trip_summary") or "").strip()[:400],
                "planning_style": str(payload.get("planning_style") or "").strip()[:120],
                "budget_hint": str(payload.get("budget_hint") or "").strip()[:200],
                "transport_hint": str(payload.get("transport_hint") or "").strip()[:200],
                "rainy_day_hint": str(payload.get("rainy_day_hint") or "").strip()[:200],
                "risk_hint": str(payload.get("risk_hint") or "").strip()[:200],
                "days": normalized_days[:5],
            }
        )
    except ValidationError:
        return None


def _derive_places_from_agenda(agenda: list[dict]) -> list[dict]:
    """中文注释：当模型没单独给地点清单时，从详细 agenda 里补出一份精简地点表。"""
    seen: set[str] = set()
    places: list[dict] = []
    for index, item in enumerate(agenda, start=1):
        name = str(item.get("place_name") or item.get("title") or "").strip()
        if not name or name in seen or _looks_generic_place(name):
            continue
        seen.add(name)
        places.append(
            {
                "name": name[:80],
                "aliases": [],
                "intro": str(item.get("detail") or "").strip()[:180],
                "category": None,
                "stay_minutes": None,
                "transport_hint": str(item.get("transport_hint") or "").strip()[:120] or None,
                "order": index,
            }
        )
    return places


def _coerce_int(value: object) -> int | None:
    try:
        parsed = int(str(value).strip())
        return parsed if parsed >= 0 else None
    except (TypeError, ValueError):
        return None


def _build_structured_plan_fallback(state: TripAgentState) -> StructuredTravelPlan | None:
    """中文注释：模型 JSON 失败时，用规则行程兜底出一份最小可用结构，避免地图断链。"""
    destination = _normalize_text((state.get("slots") or {}).get("destination"))
    days_count = _coerce_days_count((state.get("slots") or {}).get("days"), default=2)
    place_pool = state.get("planning_place_pool") or []
    unique_places = [_normalize_text(item.get("name")) for item in place_pool if _normalize_text(item.get("name"))]

    if unique_places:
        per_day = max(2, (len(unique_places) + days_count - 1) // days_count)
        days: list[StructuredPlanDay] = []
        time_slots = ["上午", "下午", "晚上"]
        for day_index in range(days_count):
            start = day_index * per_day
            end = start + per_day
            day_places = unique_places[start:end]
            if not day_places:
                continue
            agenda_items: list[StructuredAgendaItem] = []
            places: list[StructuredPlaceBrief] = []
            for place_index, name in enumerate(day_places[:4], start=1):
                source_item = next((item for item in place_pool if _normalize_text(item.get("name")) == name), {})
                detail = _normalize_text(source_item.get("reason")) or "适合作为这一天的主线地点。"
                agenda_items.append(
                    StructuredAgendaItem(
                        time=time_slots[min(place_index - 1, len(time_slots) - 1)],
                        title=name,
                        detail=detail,
                        place_name=name,
                        transport_hint=_normalize_text(source_item.get("district")) or None,
                    )
                )
                places.append(
                    StructuredPlaceBrief(
                        name=name,
                        intro=detail[:180],
                        order=place_index,
                    )
                )
            days.append(
                StructuredPlanDay(
                    day=day_index + 1,
                    title=f"{destination or '目的地'}第 {day_index + 1} 天",
                    summary="根据本地攻略、联网摘要与高德候选点自动拼装的稳定行程草案。",
                    route_digest=" -> ".join(day_places[:5]),
                    agenda=agenda_items,
                    places=places,
                )
            )
        if days:
            return StructuredTravelPlan(
                city=destination or None,
                trip_summary=f"先为你生成一版更贴近真实地点的 {destination or '目的地'} 可执行方案。",
                planning_style="结构化兜底方案",
                budget_hint="如需更准确预算，可继续补充住宿标准和人均期望。",
                transport_hint="优先结合实时铁路和地图结果继续细化。",
                rainy_day_hint="若天气有雨，优先把室内点位前置。",
                risk_hint="当前为兜底结构，请结合实时结果二次确认。",
                days=days,
            )

    itinerary = build_itinerary(
        destination or None,
        state.get("retrieved_guides", []),
        state.get("context", {}).get("selected_guides") or [],
    )
    if not itinerary:
        return None

    days: list[StructuredPlanDay] = []
    for day in itinerary:
        agenda_items = [
            StructuredAgendaItem(
                time=str(item.get("time") or ""),
                title=str(item.get("title") or ""),
                detail=str(item.get("detail") or ""),
                place_name=str(item.get("title") or ""),
            )
            for item in day.items
        ]
        places = [
            StructuredPlaceBrief(
                name=item.title,
                intro=item.detail[:180],
                order=index + 1,
            )
            for index, item in enumerate(agenda_items)
            if item.title
        ]
        days.append(
            StructuredPlanDay(
                day=day.day,
                title=day.title,
                summary="根据当前攻略命中和工具结果生成的兜底方案。",
                route_digest=" -> ".join(place.name for place in places[:5]),
                agenda=agenda_items,
                places=places[:6],
            )
        )

    return StructuredTravelPlan(
        city=destination or None,
        trip_summary=f"先为你生成一版 {destination or '目的地'} 的基础可执行方案。",
        planning_style="基础兜底方案",
        budget_hint="如需更准确预算，可继续补充住宿标准和人均期望。",
        transport_hint="优先结合实时铁路和地图结果继续细化。",
        rainy_day_hint="若天气有雨，优先把室内点位前置。",
        risk_hint="当前为兜底结构，请结合实时结果二次确认。",
        days=days,
    )


def _build_itinerary_from_structured_plan(plan: StructuredTravelPlan | None) -> list[ItineraryBlock] | None:
    """中文注释：把结构化方案同步成前端现有的可编辑 itinerary 视图。"""
    if not plan or not plan.days:
        return None
    result: list[ItineraryBlock] = []
    for day in plan.days:
        agenda = day.agenda or []
        if not agenda and day.places:
            agenda = [
                StructuredAgendaItem(
                    time="弹性",
                    title=place.name,
                    detail=place.intro or "可继续补充该地点的停留安排。",
                    place_name=place.name,
                    transport_hint=place.transport_hint,
                )
                for place in day.places
            ]
        items = [
            {
                "time": item.time or "弹性",
                "title": item.title or item.place_name or "待补充安排",
                "detail": item.detail or item.transport_hint or "可继续补充该时段安排。",
            }
            for item in agenda
        ]
        result.append(ItineraryBlock(day=day.day, title=day.title, items=items[:10]))
    return result


def _render_structured_answer(plan: StructuredTravelPlan, state: TripAgentState) -> str:
    """中文注释：统一把结构化行程渲染成稳定的人类可读回复，避免模型文案漂移影响前端和地图。"""
    lines: list[str] = []
    city = plan.city or str((state.get("slots") or {}).get("destination") or "目的地")
    lines.append(f"## {city}旅行方案")
    if plan.trip_summary:
        lines.append(plan.trip_summary)
    overview_bits = [bit for bit in [plan.planning_style, plan.budget_hint, plan.transport_hint] if bit]
    if overview_bits:
        lines.append("")
        lines.append("### 规划概览")
        lines.extend([f"- {bit}" for bit in overview_bits])

    for day in plan.days:
        lines.append("")
        lines.append(f"### Day {day.day} | {day.title}")
        if day.summary:
            lines.append(day.summary)
        for item in day.agenda[:10]:
            title = item.title or item.place_name or "待补充安排"
            detail = item.detail or item.transport_hint or "可继续补充该时段安排。"
            prefix = f"{item.time} | " if item.time else ""
            lines.append(f"- **{prefix}{title}**：{detail}")
        if day.places:
            lines.append("")
            lines.append(f"**Day {day.day} 地点清单**")
            lines.append(" -> ".join(place.name for place in day.places[:8]))
            lines.append("")
            lines.append(f"**Day {day.day} 地点简介**")
            for index, place in enumerate(day.places[:8], start=1):
                suffix = f"；{place.transport_hint}" if place.transport_hint else ""
                intro = place.intro or "适合纳入这一天的主线安排。"
                lines.append(f"{index}. {place.name}：{intro}{suffix}")

    extra_hints = [
        ("预算提示", plan.budget_hint),
        ("交通建议", plan.transport_hint),
        ("雨天备选", plan.rainy_day_hint),
        ("风险提醒", plan.risk_hint),
    ]
    available_hints = [(title, content) for title, content in extra_hints if content]
    if available_hints:
        lines.append("")
        lines.append("### 出行提醒")
        for title, content in available_hints:
            lines.append(f"- **{title}**：{content}")

    return "\n".join(lines).strip()


async def _extract_structured_plan_from_answer(answer: str, state: TripAgentState) -> StructuredTravelPlan | None:
    """中文注释：把模型生成的自然语言攻略二次压成结构，让地图链路永远优先吃结构化结果。"""
    if not answer.strip():
        return None
    llm = LlmService()
    if not llm.configured():
        return None

    prompt = "\n".join(
        [
            "请把下面这份中国旅行攻略转换为严格 JSON。",
            "只输出 JSON，不要解释，不要 Markdown。",
            "必须输出字段：city、trip_summary、planning_style、budget_hint、transport_hint、rainy_day_hint、risk_hint、days。",
            "days 中每一天必须包含：day、title、summary、route_digest、agenda、places。",
            "agenda 每项字段：time、title、detail、place_name、transport_hint。",
            "places 每项字段：name、aliases、intro、category、stay_minutes、transport_hint、order。",
            "如果当天存在多个真实地点，必须拆开写进 places。",
            "如果地点名是别称或英文缩写，name 用正式中文名，别名放 aliases。",
            f"目标城市提示：{str((state.get('slots') or {}).get('destination') or '').strip() or '未知'}",
            f"候选地点池提示：{state.get('planning_place_pool') or []}",
            "",
            answer[:5000],
        ]
    )
    payload = await llm.json_chat(prompt)
    return _normalize_structured_plan(payload or {}, state)

def _normalize_city_value(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def evaluate_local_guide_coverage(state: TripAgentState) -> dict:
    """综合命中数量、相关性、目的地匹配和来源多样性判断是否需要联网增强。"""
    guides = state.get("retrieved_guides", [])
    destination = _normalize_city_value((state.get("slots") or {}).get("destination"))
    query_tokens = tokenize_query(state.get("user_message", ""))[:10]

    unique_guide_ids = {item.get("guide_id") for item in guides if item.get("guide_id") is not None}
    unique_sources = {
        (item.get("source") or {}).get("url") or (item.get("source") or {}).get("title")
        for item in guides
        if (item.get("source") or {}).get("url") or (item.get("source") or {}).get("title")
    }
    scores = [float(item.get("score", 0.0) or 0.0) for item in guides]
    top_score = max(scores) if scores else 0.0
    top_scores = sorted(scores, reverse=True)[:3]
    avg_top_score = round(sum(top_scores) / len(top_scores), 4) if top_scores else 0.0

    destination_match_count = 0
    long_chunk_count = 0
    token_coverages: list[float] = []
    destination_focus_scores: list[float] = []
    for item in guides[:3]:
        merged_text = "\n".join(
            [
                str(item.get("title", "")),
                str(item.get("city", "")),
                str(item.get("content", "")),
            ]
        )
        focus_score = _guide_destination_focus_score(item, destination)
        destination_focus_scores.append(focus_score)
        if focus_score >= 0.55:
            destination_match_count += 1
        if len(str(item.get("content", ""))) >= 90:
            long_chunk_count += 1
        if query_tokens:
            token_hits = sum(1 for token in query_tokens if token in merged_text)
            token_coverages.append(token_hits / len(query_tokens))

    unique_guide_score = min(1.0, len(unique_guide_ids) / 3)
    relevance_score = max(top_score, avg_top_score)
    destination_focus_score = (
        round(sum(destination_focus_scores) / len(destination_focus_scores), 4) if destination_focus_scores else 0.0
    )
    destination_score = 1.0 if not destination else destination_focus_score
    token_score = round(sum(token_coverages) / len(token_coverages), 4) if token_coverages else 0.0
    source_score = min(1.0, len(unique_sources) / 2)
    chunk_quality_score = min(1.0, long_chunk_count / 2)

    coverage_score = round(
        unique_guide_score * 0.25
        + relevance_score * 0.25
        + destination_score * 0.2
        + token_score * 0.15
        + source_score * 0.1
        + chunk_quality_score * 0.05,
        4,
    )

    reasons: list[str] = []
    if len(unique_guide_ids) < 2:
        reasons.append("本地攻略命中数量偏少")
    if top_score < 0.35:
        reasons.append("头部攻略相关性偏弱")
    if destination and destination_focus_score < 0.6:
        reasons.append("本地攻略对目标城市的聚焦度不足")
    if len(unique_sources) < 2:
        reasons.append("来源多样性不足")
    if token_score < 0.3:
        reasons.append("用户问题关键信息覆盖不足")

    needs_web_search = (
        not guides
        or coverage_score < 0.58
        or top_score < 0.32
        or (destination and destination_focus_score < 0.6)
    )
    if not reasons and not needs_web_search:
        reasons.append("本地攻略覆盖度充足")

    return {
        "coverage_score": coverage_score,
        "unique_guide_count": len(unique_guide_ids),
        "unique_source_count": len(unique_sources),
        "top_score": round(top_score, 4),
        "avg_top_score": avg_top_score,
        "destination": destination,
        "destination_match_count": destination_match_count,
        "destination_focus_score": destination_focus_score,
        "token_score": token_score,
        "chunk_quality_score": chunk_quality_score,
        "needs_web_search": needs_web_search,
        "decision_reason": "；".join(reasons),
    }


async def intent_slot_node(state: TripAgentState) -> TripAgentState:
    """意图识别与槽位抽取节点。"""
    message = state["user_message"]
    context = state.get("context", {})
    llm = LlmService()
    parsed = await llm.json_chat(INTENT_AND_SLOT_PROMPT.replace("{message}", message))
    rule_intent = infer_intent_by_rules(message)
    rule_slots = extract_slots_by_rules(message, context)

    if parsed and parsed.get("intent"):
        parsed_slots = parsed.get("slots") or {}
        merged_slots = {**rule_slots, **parsed_slots}
        parsed_intent = parsed.get("intent", "general_qa")

        # 中文注释：当规则已经明显识别出“已有目的地要做行程规划”时，优先守住这个判断，避免模型轻微跑偏。
        if rule_intent == "itinerary_planning" and parsed_intent in {"destination_recommendation", "general_qa"}:
            parsed_intent = rule_intent
        if rule_slots.get("destination") and not merged_slots.get("destination"):
            merged_slots["destination"] = rule_slots.get("destination")
        if rule_slots.get("origin") and not merged_slots.get("origin"):
            merged_slots["origin"] = rule_slots.get("origin")
        if rule_slots.get("days") and not merged_slots.get("days"):
            merged_slots["days"] = rule_slots.get("days")
        if rule_slots.get("budget") and not merged_slots.get("budget"):
            merged_slots["budget"] = rule_slots.get("budget")

        state["intent"] = parsed_intent
        state["slots"] = merged_slots
        state["missing_slots"] = parsed.get("missing_slots") or []
        state["confidence"] = parsed.get("confidence", 0.8)
        return state

    state["intent"] = rule_intent
    state["slots"] = rule_slots
    state["missing_slots"] = []
    state["confidence"] = 0.62
    return state


async def retrieval_node(state: TripAgentState) -> TripAgentState:
    """本地攻略检索节点。"""
    rag = RagService(state["db"])
    logger = build_logger(state)
    slots = state.get("slots", {})
    start = time.perf_counter()
    raw_items = rag.search(state["user_message"], city=slots.get("destination"), top_k=8)
    items = _rerank_guides_for_destination(raw_items, slots.get("destination"))
    latency = int((time.perf_counter() - start) * 1000)
    state["retrieved_guides"] = [item.model_dump() for item in items]
    state["guide_items"] = items
    state["guide_coverage"] = evaluate_local_guide_coverage(state)
    state["planning_place_pool"] = []
    logger.record(
        "guide_search",
        {"query": state["user_message"], "city": slots.get("destination")},
        f"命中 {len(items)} 条攻略片段，覆盖分 {state['guide_coverage']['coverage_score']}",
        "success",
        latency,
    )
    return state


async def web_search_node(state: TripAgentState) -> TripAgentState:
    """联网增强节点。"""
    mode = state.get("search_mode", "auto")
    coverage = state.get("guide_coverage") or evaluate_local_guide_coverage(state)
    state["guide_coverage"] = coverage

    if mode == "local_only":
        state["web_items"] = []
        state["web_search_reason"] = "已切换为仅本地攻略模式"
        return state

    should_search = mode == "web_enhanced" or coverage.get("needs_web_search", True)
    if not should_search:
        state["web_items"] = []
        state["web_search_reason"] = f"自动模式判定本地已足够：{coverage.get('decision_reason', '本地攻略覆盖度充足')}"
        return state

    logger = build_logger(state)
    reason_prefix = "已开启联网增强模式" if mode == "web_enhanced" else f"自动模式触发联网增强：{coverage.get('decision_reason', '本地命中不足')}"
    web_items = await logger.measure_async(
        "web_search",
        {"query": state["user_message"], "mode": mode, "guide_coverage": coverage},
        lambda: WebSearchService(state["db"]).search(state["user_message"], top_k=5),
        lambda result: f"{reason_prefix}，返回 {len(result)} 条公开结果",
    )
    state["web_items"] = web_items
    state["web_search_reason"] = reason_prefix
    return state


async def weather_node(state: TripAgentState) -> TripAgentState:
    """天气工具节点。"""
    intent = state.get("intent")
    slots = state.get("slots", {})
    destination = slots.get("destination")
    if intent not in {"weather_advice", "itinerary_planning", "destination_recommendation"} or not destination:
        state["weather_result"] = None
        return state

    result = await build_logger(state).measure_async(
        "amap_weather",
        {"city": destination, "date": slots.get("date")},
        lambda: AmapService().get_weather(destination, slots.get("date")),
        lambda data: f"{destination}天气：{data.get('weather')}，风险：{','.join(data.get('risk_tags', [])) or '无明显风险'}",
    )
    state["weather_result"] = result
    return state


async def railway_node(state: TripAgentState) -> TripAgentState:
    """铁路 MCP 节点。"""
    intent = state.get("intent")
    slots = state.get("slots", {})
    destination = slots.get("destination")
    if intent != "railway_query" and not (slots.get("origin") and destination):
        state["railway_result"] = None
        return state

    result = await build_logger(state).measure_async(
        "railway_query",
        {"origin": slots.get("origin"), "destination": destination, "date": slots.get("date")},
        lambda: McpRailwayService().query_trains(
            slots.get("origin") or "出发地",
            destination or "目的地",
            slots.get("date") or "待确认日期",
        ),
        lambda data: f"返回 {len(data.get('trains', []))} 条车次",
    )
    state["railway_result"] = result
    return state


async def route_node(state: TripAgentState) -> TripAgentState:
    """地图路线节点。"""
    slots = state.get("slots", {})
    destination = slots.get("destination")
    if state.get("intent") != "itinerary_planning" or not destination:
        state["route_result"] = None
        return state

    result = await build_logger(state).measure_async(
        "amap_route",
        {"origin": f"{destination}站", "destination": "核心景区", "city": destination},
        lambda: AmapService().route(f"{destination}站", "核心景区", destination),
        lambda data: f"估算通勤 {data.get('duration_minutes')} 分钟",
    )
    state["route_result"] = result
    return state


async def planner_node(state: TripAgentState) -> TripAgentState:
    """规划生成节点。"""
    llm = LlmService()
    state["planning_place_pool"] = await _build_planning_place_pool(state)
    prompt = _build_planner_prompt(state)
    planner_payload = await llm.json_chat(prompt)
    structured_plan = _normalize_structured_plan(planner_payload or {}, state)

    if structured_plan:
        state["structured_plan"] = structured_plan.model_dump()
        state["itinerary"] = _build_itinerary_from_structured_plan(structured_plan)
        state["final_answer"] = _render_structured_answer(structured_plan, state)
        return state

    rich_answer = await llm.plain_chat(_build_planner_text_prompt(state))
    if rich_answer:
        extracted_plan = await _extract_structured_plan_from_answer(rich_answer, state)
        if extracted_plan:
            state["structured_plan"] = extracted_plan.model_dump()
            state["itinerary"] = _build_itinerary_from_structured_plan(extracted_plan)
            state["final_answer"] = _render_structured_answer(extracted_plan, state)
            return state

    fallback_plan = _build_structured_plan_fallback(state)
    state["structured_plan"] = fallback_plan.model_dump() if fallback_plan else None
    state["itinerary"] = _build_itinerary_from_structured_plan(fallback_plan)
    state["final_answer"] = _render_structured_answer(fallback_plan, state) if fallback_plan else (rich_answer or compose_fallback_answer(state))
    return state


async def response_node(state: TripAgentState) -> TripAgentState:
    """前端响应组装节点。"""
    destination = state.get("slots", {}).get("destination")
    weather = state.get("weather_result")
    railway = state.get("railway_result")
    guides = state.get("retrieved_guides", [])
    selected_guides = state.get("context", {}).get("selected_guides") or []

    if not state.get("itinerary"):
        state["itinerary"] = build_itinerary(destination, guides, selected_guides)
    state["cards"] = build_cards(destination, weather, railway)
    state["sources"] = build_sources(state.get("guide_items", []), state.get("web_items", []))
    state["warnings"] = build_warnings(weather, railway)
    state["decision_modules"] = build_decision_modules(state)
    state["tool_calls_view"] = recent_tool_calls(state)
    return state


def compose_fallback_answer(state: TripAgentState) -> str:
    """模型失败时的稳定中文兜底回答。"""
    destination = state.get("slots", {}).get("destination") or "目的地"
    guides = state.get("retrieved_guides", [])
    web_items = state.get("web_items", [])
    weather = state.get("weather_result")
    railway = state.get("railway_result")
    route = state.get("route_result")
    guide_coverage = state.get("guide_coverage") or {}
    selected_guides = state.get("context", {}).get("selected_guides") or []

    lines = [f"我先按“{state.get('intent')}”为你做一次智能体规划。"]
    if guides:
        lines.append(f"本地攻略库检索到 {len(guides)} 条相关片段，优先参考《{guides[0]['title']}》。")
        if guide_coverage:
            lines.append(
                f"本地命中覆盖分 {guide_coverage.get('coverage_score', 0)}，判断依据：{guide_coverage.get('decision_reason', '综合命中情况评估')}。"
            )
    else:
        lines.append("当前攻略库命中较少，建议后续补充更多本地攻略以提升推荐质量。")
    if selected_guides:
        selected_title = selected_guides[0].get("title") or "已选攻略"
        lines.append(f"我已经把你主动加入的攻略《{selected_title}》纳入本轮规划。")
    if web_items:
        lines.append(f"联网增强补充了 {len(web_items)} 条公开搜索结果，回答中会与本地攻略来源区分。")
    if weather:
        risk = "、".join(weather.get("risk_tags") or []) or "无明显天气风险"
        lines.append(f"{destination}天气参考：{weather.get('weather')}，温度 {weather.get('temperature')}，风险：{risk}。")
    if railway:
        lines.append(f"铁路查询返回 {len(railway.get('trains', []))} 条候选车次；本项目只做查询参考，不做购票或抢票。")
    if route:
        lines.append(f"地图路线估算：从车站到核心景区约 {route.get('duration_minutes')} 分钟。")
    lines.append("建议采用“先确认交通可行性，再按天气调整室内外比例，最后用攻略细化景点与美食”的规划方式。")
    return "\n\n".join(lines)


def build_cards(destination: str | None, weather: dict | None, railway: dict | None) -> list[ResultCard]:
    """构造前端展示卡片。"""
    cards: list[ResultCard] = []
    if destination:
        cards.append(ResultCard(type="destination", title=destination, summary="根据攻略、天气和交通综合评估的候选目的地。"))
    if weather:
        cards.append(
            ResultCard(
                type="weather",
                title="天气判断",
                summary=f"{weather.get('weather')}，{weather.get('temperature')}",
                meta={
                    "city": weather.get("city"),
                    "risk_tags": weather.get("risk_tags") or [],
                    "fallback": weather.get("fallback", False),
                },
            )
        )
    if railway:
        trains = railway.get("trains", [])
        cards.append(
            ResultCard(
                type="railway",
                title=f"{railway.get('origin', '')} → {railway.get('destination', '')}".strip(" →"),
                summary=f"{len(trains)} 条车次可供比较",
                meta={
                    "provider": railway.get("provider"),
                    "tool_name": railway.get("tool_name"),
                    "date": railway.get("date"),
                    "fallback": railway.get("fallback", False),
                    "notice": railway.get("notice"),
                    "trains": trains[:8],
                },
            )
        )
    return cards


def build_sources(guide_items: list, web_items: list) -> list[SourceRef]:
    """合并本地攻略来源和联网来源。"""
    seen: set[str] = set()
    sources: list[SourceRef] = []
    for item in guide_items:
        key = f"{item.source.title}|{item.source.url}"
        if key in seen:
            continue
        seen.add(key)
        sources.append(item.source)
    for item in web_items:
        key = f"{item.title}|{item.url}"
        if key in seen:
            continue
        seen.add(key)
        sources.append(SourceRef(title=item.title, url=item.url, source_type=item.source_type))
    return sources


def build_warnings(weather: dict | None, railway: dict | None) -> list[str]:
    """生成风险提醒。"""
    warnings: list[str] = []
    if weather and weather.get("fallback"):
        warnings.append("天气结果为演示或缓存兜底数据，真实出行前请再次确认。")
    if railway and railway.get("fallback"):
        warnings.append("铁路结果为演示或 MCP 兜底数据，真实购票前请以 12306 官方为准。")
    return warnings


def build_decision_modules(state: TripAgentState) -> list[DecisionModule]:
    """把工具结果拆成前端可视化决策模块。"""
    slots = state.get("slots", {})
    weather = state.get("weather_result") or {}
    railway = state.get("railway_result") or {}
    route = state.get("route_result") or {}
    guides = state.get("retrieved_guides", [])
    web_items = state.get("web_items", [])
    guide_coverage = state.get("guide_coverage") or {}
    trains = railway.get("trains") or []
    risk_tags = weather.get("risk_tags") or []
    rainy = any("雨" in tag or "雪" in tag for tag in risk_tags)
    budget = slots.get("budget")
    days = slots.get("days")

    modules = [
        DecisionModule(
            type="transport",
            title="交通建议",
            level="good" if trains else "warn",
            summary=f"已查询到 {len(trains)} 条铁路候选" if trains else "铁路候选不足，需要复核出发地、目的地和日期。",
            points=[
                "优先选择白天抵达、耗时短且二等座充足的车次。",
                "本项目只提供查询参考，不支持购票、抢票、登录或支付。",
                f"站点通勤估算约 {route.get('duration_minutes')} 分钟。" if route else "地图路线暂未返回。",
            ],
            meta={"train_count": len(trains), "date": railway.get("date"), "fallback": railway.get("fallback", False)},
        ),
        DecisionModule(
            type="rainy_day",
            title="雨天备选",
            level="warn" if rainy else "good",
            summary="天气存在雨雪风险，建议提高室内活动比例。" if rainy else "当前天气风险较低，可保持常规室外行程。",
            points=[
                "雨天优先安排博物馆、街区慢逛、茶馆、餐厅和商圈。",
                "园林、古城街巷等室外点位建议放在雨小或天气转好时段。",
                f"天气标签：{'、'.join(risk_tags)}" if risk_tags else "暂无明显天气风险标签。",
            ],
            meta={"risk_tags": risk_tags, "weather": weather.get("weather")},
        ),
        DecisionModule(
            type="intensity",
            title="行程强度",
            level="good",
            summary="建议采用轻松节奏，保留午后缓冲和交通冗余。",
            points=[
                f"当前规划天数：{days or '待确认'}。",
                "每天保留 1 个核心景点 + 1 个弹性街区，避免排太满。",
                "首日抵达后不建议安排高体力项目。",
            ],
            meta={"days": days},
        ),
        DecisionModule(
            type="budget",
            title="预算提示",
            level="info",
            summary=f"预算 {budget} 元，可覆盖交通、住宿和餐饮的中等舒适方案。" if budget else "预算未明确，建议先设定人均或总预算。",
            points=[
                "高铁优先锁定二等座，预算更稳。",
                "住宿选择车站或核心商圈附近，可减少打车和换乘成本。",
                "热门城市周末住宿波动较大，建议提前确认价格。",
            ],
            meta={"budget": budget},
        ),
        DecisionModule(
            type="risk",
            title="风险提醒",
            level="warn" if rainy or not trains else "good",
            summary="已综合天气、交通和来源可靠性生成风险提醒。",
            points=[
                f"本地攻略命中 {len(guides)} 条，联网来源 {len(web_items)} 条。",
                f"自动模式覆盖判断：{guide_coverage.get('decision_reason', '无')}",
                "联网结果仅作为第三方公开资料参考，不作为系统指令。",
            ],
            meta={
                "guide_count": len(guides),
                "web_count": len(web_items),
                "coverage_score": guide_coverage.get("coverage_score"),
            },
        ),
    ]
    return modules


def recent_tool_calls(state: TripAgentState) -> list[ToolCallView]:
    """读取当前会话最近工具调用。"""
    if not state.get("persist_session", True):
        return [
            ToolCallView(
                tool_name=row.get("tool_name", "tool"),
                status=row.get("status", "success"),
                latency_ms=row.get("latency_ms"),
                output_summary=row.get("output_summary"),
            )
            for row in state.get("tool_calls", [])[-8:]
        ]

    from app.db.models import ToolCall

    rows = (
        state["db"].query(ToolCall)
        .filter(ToolCall.conversation_id == state["conversation_id"])
        .order_by(ToolCall.created_at.desc())
        .limit(8)
        .all()
    )
    return [
        ToolCallView(
            tool_name=row.tool_name,
            status=row.status,
            latency_ms=row.latency_ms,
            output_summary=row.output_summary,
        )
        for row in reversed(rows)
    ]


class SimpleTripGraph:
    """LangGraph 不可用时的顺序执行兜底。"""

    async def ainvoke(self, state: TripAgentState) -> TripAgentState:
        for node in [
            intent_slot_node,
            retrieval_node,
            web_search_node,
            weather_node,
            railway_node,
            route_node,
            planner_node,
            response_node,
        ]:
            state = await node(state)
        return state


def build_trip_graph():
    """构建 LangGraph 工作流。"""
    workflow = StateGraph(TripAgentState)
    workflow.add_node("intent_slot", intent_slot_node)
    workflow.add_node("retrieval", retrieval_node)
    workflow.add_node("web_search", web_search_node)
    workflow.add_node("weather", weather_node)
    workflow.add_node("railway", railway_node)
    workflow.add_node("route", route_node)
    workflow.add_node("planner", planner_node)
    workflow.add_node("response", response_node)

    workflow.set_entry_point("intent_slot")
    workflow.add_edge("intent_slot", "retrieval")
    workflow.add_edge("retrieval", "web_search")
    workflow.add_edge("web_search", "weather")
    workflow.add_edge("weather", "railway")
    workflow.add_edge("railway", "route")
    workflow.add_edge("route", "planner")
    workflow.add_edge("planner", "response")
    workflow.add_edge("response", END)
    return workflow.compile()
