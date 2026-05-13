import re
import time

from langgraph.graph import END, StateGraph
from pydantic import ValidationError

from app.agents.prompts import INTENT_AND_SLOT_PROMPT, PLANNER_PROMPT, PLANNER_TEXT_PROMPT
from app.agents.state import TripAgentState
from app.schemas.chat import (
    DecisionModule,
    ItineraryBlock,
    RenderPlan,
    RenderPlanBlock,
    RenderPlanDay,
    RenderPlanOverview,
    StructuredAgendaItem,
    StructuredPlaceBrief,
    StructuredPlanDay,
    StructuredTravelPlan,
    TravelPlanBudgetItem,
    TravelPlanBudgetView,
    TravelPlanDayView,
    TravelPlanMapMarker,
    TravelPlanMapSchedule,
    TravelPlanOverview,
    TravelPlanPoiCard,
    TravelPlanSupplement,
    TravelPlanView,
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
DESTINATION_CAPTURE_PATTERNS = [
    re.compile(r"(?:鎯冲幓|鎯冲埌|鍑嗗鍘?|璁″垝鍘?|浠嶵[一-龥]{2,8}鍘?|鍘?|鍒?)\s*(?P<name>[一-龥]{2,8})(?:鐜?|鏃呮父|鏃呰|閫涢€?])?"),
    re.compile(r"(?P<name>[一-龥]{2,8})(?:涓€澶╀竴澶?涓ゅぉ涓€澶?涓ゆ棩娓?涓夋棩娓?鍛ㄦ湯娓?citywalk|鏃呮父鏀荤暐|鏃呰鏀荤暐|娓哥帺鏀荤暐|鏀荤暐|鏃呰鏂规|琛岀▼瑙勫垝)"),
]
GENERIC_DESTINATION_TOKENS = {
    "鎴戞兂",
    "棰勭畻",
    "楂橀搧",
    "鐏溅",
    "缇庨",
    "澶滄櫙",
    "鍘嗗彶",
    "鏃呮父",
    "鏃呰",
    "鏀荤暐",
    "鏂规",
    "琛岀▼",
}
TIME_SLOT_CANDIDATES = ["鏃╀笂", "涓婂崍", "涓崍", "涓嬪崍", "鍌嶆櫄", "鏅氫笂", "澶滈噷"]


def build_logger(state: TripAgentState) -> ToolLogger:
    """根据当前会话模式创建工具日志器。"""
    return ToolLogger(
        state["db"],
        state.get("conversation_id"),
        enabled=state.get("persist_session", True),
        memory_buffer=state.setdefault("tool_calls", []),
    )


def infer_intent_by_rules(message: str) -> str:
    """?????????????????????????????"""
    if any(word in message for word in ["\u9ad8\u94c1", "12306", "\u5217\u8f66", "\u8f66\u6b21", "\u4f59\u7968", "\u706b\u8f66"]):
        return "railway_query"
    if any(word in message for word in ["\u5929\u6c14", "\u4e0b\u96e8", "\u6e29\u5ea6", "\u51b7\u5417", "\u70ed\u5417"]):
        return "weather_advice"
    if any(word in message for word in ["\u6dfb\u52a0\u653b\u7565", "\u5bfc\u5165\u653b\u7565", "\u5165\u5e93", "\u65b0\u589e\u653b\u7565"]):
        return "add_guide"
    if any(word in message for word in ["\u884c\u7a0b", "\u8def\u7ebf", "\u51e0\u5929", "\u4e24\u5929", "\u4e09\u5929", "\u653b\u7565", "citywalk"]):
        return "itinerary_planning"
    if any(word in message for word in ["\u63a8\u8350", "\u53bb\u54ea", "\u54ea\u91cc", "\u76ee\u7684\u5730"]):
        return "destination_recommendation"
    return "general_qa"


def extract_slots_by_rules(message: str, context: dict) -> dict:
    """????????????????????????????????"""
    cities = [city for city in CITY_WORDS if city in message]
    origin = context.get("home_city")
    destination = None
    if len(cities) >= 2:
        origin, destination = cities[0], cities[1]
    elif len(cities) == 1:
        destination = cities[0]
    if not destination:
        destination = _infer_destination_from_message(message)

    budget_match = re.search(r"(?:\u9884\u7b97|\u4eba\u5747)\s*([0-9]{2,6})|([0-9]{2,6})\s*(?:\u5143|\u5757)", message)
    days_match = re.search(r"([\u4e00\u4e8c\u4e24\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u53410-9]+)\s*(?:\u5929|\u65e5)", message)
    if not days_match:
        days_match = re.search(r"([\u4e00\u4e8c\u4e24\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u53410-9]+)\s*\u5929\s*[\u4e00\u4e8c\u4e24\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u53410-9]+\s*\u591c", message)
    date = "\u660e\u5929" if "\u660e\u5929" in message else ("\u5468\u672b" if "\u5468\u672b" in message else context.get("date"))
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


def _clean_destination_candidate(value: object) -> str:
    text = _normalize_text(value)
    text = re.sub(r"^[\u53bb\u5230\u73a9\u901b]+", "", text)
    text = re.sub(r"(?:\u73a9)?(?:[\u4e00\u4e8c\u4e24\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u53410-9]+(?:\u5929|\u65e5))(?:\u6e38)?$", "", text)
    text = re.sub(r"(?:\u65c5\u884c|\u65c5\u6e38|\u653b\u7565|\u65b9\u6848|\u884c\u7a0b|\u5468\u672b\u6e38|citywalk|\u81ea\u7531\u884c)$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[\u4e00\u5929\u4e00\u591c\u4e24\u5929\u4e00\u591c]+$", "", text)
    text = re.sub(r"[，。；：,.!！?？\s]+", "", text)
    return text[:12]


def _is_valid_destination_candidate(value: str) -> bool:
    text = _clean_destination_candidate(value)
    if len(text) < 2 or len(text) > 8:
        return False
    if any(char.isdigit() for char in text):
        return False
    invalid_tokens = {"\u6211\u60f3", "\u9884\u7b97", "\u9ad8\u94c1", "\u7f8e\u98df", "\u591c\u666f", "\u65c5\u884c", "\u653b\u7565", "\u65b9\u6848", "\u884c\u7a0b"}
    return text not in invalid_tokens


def _infer_destination_from_message(message: str) -> str | None:
    """?????????????????????????????????????"""
    patterns = [
        re.compile(r"(?:\u60f3\u53bb|\u60f3\u5230|\u51c6\u5907\u53bb|\u8ba1\u5212\u53bb|\u4ece[\u4e00-\u9fff]{2,8}\u53bb|\u53bb|\u5230)(?P<name>[\u4e00-\u9fff]{2,8})(?:\u73a9|\u65c5\u6e38|\u65c5\u884c|\u901b)?"),
        re.compile(r"(?P<name>[\u4e00-\u9fff]{2,8})(?:\u4e00\u5929\u4e00\u591c|\u4e24\u5929\u4e00\u591c|\u4e24\u65e5\u6e38|\u4e09\u65e5\u6e38|\u5468\u672b\u6e38|citywalk|\u65c5\u6e38\u653b\u7565|\u65c5\u884c\u653b\u7565|\u6e38\u73a9\u653b\u7565|\u653b\u7565|\u65c5\u884c\u65b9\u6848|\u884c\u7a0b\u89c4\u5212)"),
    ]
    for pattern in patterns:
        for match in pattern.finditer(message):
            candidate = _clean_destination_candidate(match.group("name"))
            if _is_valid_destination_candidate(candidate):
                return candidate
    return None


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
    return any(
        word in text
        for word in [
            "预算",
            "建议",
            "分钟",
            "打车",
            "地铁",
            "高铁",
            "车次",
            "返程",
            "抵达",
            "这里是",
            "这是一处",
            "参观完",
            "逛了",
            "十点多",
            "注意",
            "推荐",
            "附近的",
            "如果你",
            "可以买",
        ]
    )


def _looks_fragmented_place(value: str) -> bool:
    """中文注释：过滤掉像句子片段而不是正式地点名的候选，避免兜底路线被长句污染。"""
    text = _normalize_text(value)
    if not text:
        return True
    if any(mark in text for mark in ["，", "。", "！", "？", "；"]):
        return True
    if len(text) > 18:
        return True
    reject_keywords = [
        "这里",
        "这是",
        "如果",
        "注意",
        "推荐",
        "方便",
        "参观完",
        "逛了",
        "到的时候",
        "选择去",
        "可以买",
        "最繁华",
        "免费开放",
        "看完",
    ]
    return any(keyword in text for keyword in reject_keywords)


def _clean_route_style_place_name(value: str) -> str:
    """中文注释：清洗攻略长文里抽出的路线节点，尽量保留可被地图识别的正式名称。"""
    text = _normalize_text(value)
    if not text:
        return ""
    text = text.replace("【", "").replace("】", "").replace("[", "").replace("]", "")
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"^[0-9]+[.)、]\s*", "", text)
    text = re.sub(r"^(?:第[一二三四五六七八九十0-9]+天)?(?:路线|主线|行程|夜游|午餐|晚餐|早餐)[:：]?\s*", "", text)
    text = re.sub(r"^(?:去|到|逛|看|住在|入住|前往)\s*", "", text)
    text = re.sub(r"(?:附近|一带|区域|商圈)$", "", text).strip()
    text = re.sub(r"\(([^()/]+?)/[^()]+\)", r"(\1)", text)
    text = re.sub(r"/.*$", "", text).strip()
    text = re.sub(r"\s+", " ", text).strip()
    if _looks_generic_place(text) or _looks_fragmented_place(text):
        return ""
    return text[:40]


def _extract_route_style_places(text: str) -> list[str]:
    """中文注释：优先从“路线/第X天【...】/A-B-C”这类结构里提取正式地点，减少句子片段误命中。"""
    if not text:
        return []
    result: list[str] = []
    patterns = [
        re.compile(r"第[一二三四五六七八九十0-9]+天\s*[【\[](.*?)[】\]]"),
        re.compile(r"(?:路线|主线|行程)[:：]\s*(.+)"),
    ]
    raw_segments: list[str] = []
    for pattern in patterns:
        raw_segments.extend(match.group(1) for match in pattern.finditer(text))

    for segment in raw_segments:
        for item in re.split(r"\s*(?:->|=>|>|→|－|—|-|&|＆|/|｜|\||、|，|,|；|;)\s*", segment):
            cleaned = _clean_route_style_place_name(item)
            if cleaned and cleaned not in result:
                result.append(cleaned)
    return result[:16]


def _extract_place_names(text: str) -> list[str]:
    if not text:
        return []
    names: list[str] = _extract_route_style_places(text)
    for pattern in (PLACE_SUFFIX_PATTERN, PLACE_EN_PATTERN):
        for match in pattern.findall(text):
            name = _normalize_text(match)
            if (
                name
                and not _looks_generic_place(name)
                and not _looks_fragmented_place(name)
                and name not in names
            ):
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
        candidates = _extract_route_style_places(merged)
        if len(candidates) < 3:
            candidates.extend(_extract_place_names(merged))
        for name in candidates:
            key = _normalize_compact(name)
            if key in seen or _looks_fragmented_place(name):
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


def _compress_guide_for_planner(guide: dict) -> dict:
    """中文注释：给规划提示词喂更短的攻略摘要，避免长 OCR 原文把模型输出长度和稳定性一起拖垮。"""
    source = guide.get("source") or {}
    return {
        "title": _normalize_text(guide.get("title"))[:80],
        "city": _normalize_text(guide.get("city"))[:24],
        "score": guide.get("score"),
        "source_title": _normalize_text(source.get("title") or source.get("url"))[:80],
        "content_excerpt": _normalize_text(guide.get("content"))[:420],
    }


def _build_planner_prompt(state: TripAgentState) -> str:
    """中文注释：把多源上下文压缩后喂给大模型，减少无关噪声对结构化输出的污染。"""
    context = state.get("context", {})
    return PLANNER_PROMPT.format(
        message=state["user_message"],
        intent=state.get("intent"),
        slots=state.get("slots"),
        guides=[_compress_guide_for_planner(item) for item in state.get("retrieved_guides", [])[:4]],
        selected_guides=(context.get("selected_guides") or [])[:2],
        web_items=[item.__dict__ for item in state.get("web_items", [])[:4]],
        weather=state.get("weather_result"),
        railway=state.get("railway_result"),
        route=state.get("route_result"),
        edited_plan=context.get("edited_plan"),
        preference_profile=context.get("preference_profile"),
        planning_place_pool=state.get("planning_place_pool") or [],
    ) + _planner_product_contract()


def _build_planner_text_prompt(state: TripAgentState) -> str:
    """中文注释：当直接出 JSON 不稳定时，先让模型输出一版完整文案，再做结构抽取。"""
    context = state.get("context", {})
    return PLANNER_TEXT_PROMPT.format(
        message=state["user_message"],
        intent=state.get("intent"),
        slots=state.get("slots"),
        guides=[_compress_guide_for_planner(item) for item in state.get("retrieved_guides", [])[:4]],
        selected_guides=(context.get("selected_guides") or [])[:2],
        web_items=[item.__dict__ for item in state.get("web_items", [])[:4]],
        weather=state.get("weather_result"),
        railway=state.get("railway_result"),
        route=state.get("route_result"),
        edited_plan=context.get("edited_plan"),
        preference_profile=context.get("preference_profile"),
        planning_place_pool=state.get("planning_place_pool") or [],
    ) + _planner_text_product_contract()


def _planner_product_contract() -> str:
    """中文注释：追加稳定的产品级 JSON 契约，避免改动旧提示词主体时受编码影响。"""
    return """

产品级结构化输出补充契约：
- 每个 days[] 必须包含 agenda、places、route_nodes、food_plan、transport_plan、budget_plan、pace_level、weather_backup、risk_notes。
- route_nodes 是地图工作台的唯一主线依据，必须覆盖当天 agenda 中出现的每一个真实景点、街区、商圈、餐饮区域、车站或码头；不要放“午餐”“预算”“地铁”等非地点词。
- places 负责地点卡片展示，route_nodes 负责地图路线；二者顺序应与当天实际游玩顺序一致，缺一不可。
- food_plan 至少写 lunch、dinner，并补充 recommendations；transport_plan.segments 必须按相邻 route_nodes 写 origin、destination、mode、hint。
- budget_plan.summary 要说明当天主要花费；pace_level 用“轻松/适中/偏满”表达强度；weather_backup 和 risk_notes 必须是数组。
- 自然语言攻略可以详细、有温度，但 JSON 必须严谨，地图节点不得靠长文本猜测。
"""


def _planner_text_product_contract() -> str:
    """中文注释：追加自然语言输出契约，保证正文详细且不牺牲地图结构。"""
    return """

自然语言正文补充要求：
- 每天正文必须同时包含：详细日程、美食安排、交通方式、预算与强度、雨天备选、风险提醒。
- 每天结尾必须保留“当天地点清单”和“当天地点简介”，地点名称要与结构化 route_nodes 完全一致，便于地图工作台联动。
- 不要把回答压缩成只有景点列表；应给出为什么这么排、怎么走、在哪里吃、预算如何控制、哪些地方需要预约或错峰。
"""


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
            name, aliases = _normalize_place_payload_fields(name, aliases)
            places.append(
                {
                    "name": name[:80],
                    "aliases": aliases[:4],
                    "intro": str(raw_place.get("intro") or "").strip()[:240],
                    "category": str(raw_place.get("category") or "").strip()[:40] or None,
                    "stay_minutes": _coerce_int(raw_place.get("stay_minutes")),
                    "transport_hint": str(raw_place.get("transport_hint") or "").strip()[:120] or None,
                    "order": _coerce_int(raw_place.get("order")) or place_index,
                    "map_required": bool(raw_place.get("map_required", True)),
                    "source_agenda_title": str(raw_place.get("source_agenda_title") or "").strip()[:120] or None,
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
            place_name = _canonicalize_place_name(str(raw_item.get("place_name") or "").strip()) or _canonicalize_place_name(title) or str(raw_item.get("place_name") or "").strip() or title
            title = _canonicalize_place_name(title) or title
            agenda.append(
                {
                    "time": str(raw_item.get("time") or "").strip()[:40],
                    "title": title[:120],
                    "detail": detail[:600],
                    "place_name": place_name[:80] or None,
                    "transport_hint": str(raw_item.get("transport_hint") or "").strip()[:120] or None,
                }
            )

        if not places and agenda:
            places = _derive_places_from_agenda(agenda)
        route_nodes = _normalize_route_nodes(raw_day, agenda, places)
        if not places and route_nodes:
            places = route_nodes
        elif route_nodes:
            places = _merge_place_lists(places, route_nodes)[:10]

        normalized_days.append(
            {
                "day": _coerce_int(raw_day.get("day")) or index,
                "title": str(raw_day.get("title") or f"Day {index} 行程").strip()[:120],
                "summary": str(raw_day.get("summary") or "").strip()[:240],
                "route_digest": str(raw_day.get("route_digest") or "").strip()[:240],
                "agenda": agenda[:10],
                "places": places[:10],
                "route_nodes": route_nodes[:12],
                "food_plan": _normalize_food_plan(raw_day),
                "transport_plan": _normalize_transport_plan(raw_day, route_nodes or places),
                "budget_plan": _normalize_day_budget_plan(raw_day, state),
                "pace_level": _normalize_text(raw_day.get("pace_level"))[:60] or _infer_day_pace(raw_day, len(route_nodes or places)),
                "weather_backup": _normalize_text_list(raw_day.get("weather_backup"), 5, 160) or _default_weather_backup(payload, raw_day),
                "risk_notes": _normalize_text_list(raw_day.get("risk_notes"), 5, 160) or _default_risk_notes(payload, raw_day),
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
        raw_name = str(item.get("place_name") or item.get("title") or "").strip()
        name, aliases = _normalize_place_payload_fields(raw_name)
        if not name or name in seen or _looks_generic_place(name):
            continue
        seen.add(name)
        places.append(
            {
                "name": name[:80],
                "aliases": aliases[:4],
                "intro": str(item.get("detail") or "").strip()[:180],
                "category": None,
                "stay_minutes": None,
                "transport_hint": str(item.get("transport_hint") or "").strip()[:120] or None,
                "order": index,
            }
        )
    return places


def _normalize_text_list(value: object, limit: int = 5, max_length: int = 160) -> list[str]:
    """中文注释：把模型可能输出的字符串或数组统一成前端可直接渲染的短句数组。"""
    if isinstance(value, str):
        raw_items = re.split(r"[；;\n]", value)
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []
    result: list[str] = []
    for item in raw_items:
        text = _normalize_text(item)
        if text and text not in result:
            result.append(text[:max_length])
        if len(result) >= limit:
            break
    return result


def _merge_place_lists(primary: list[dict], secondary: list[dict]) -> list[dict]:
    """中文注释：合并地点与地图节点，避免地图漏掉日程里出现的真实地点。"""
    result: list[dict] = []
    seen: set[str] = set()
    for item in [*primary, *secondary]:
        name = _normalize_text(item.get("name"))
        key = _normalize_compact(name)
        if not name or not key or key in seen or _looks_generic_place(name):
            continue
        seen.add(key)
        result.append(item)
    return result


def _coerce_place_payload(raw_place: dict, place_index: int, source_title: str | None = None) -> dict | None:
    raw_name = _normalize_text(raw_place.get("name") or raw_place.get("title") or raw_place.get("place_name"))
    raw_aliases = [
        _normalize_text(item)
        for item in (raw_place.get("aliases") or [])
        if _normalize_text(item) and _normalize_text(item) != raw_name and not _looks_generic_place(_normalize_text(item))
    ]
    name, aliases = _normalize_place_payload_fields(raw_name, raw_aliases)
    if not name or _looks_generic_place(name):
        return None
    return {
        "name": name[:80],
        "aliases": aliases[:4],
        "intro": _normalize_text(raw_place.get("intro") or raw_place.get("detail"))[:240],
        "category": _normalize_text(raw_place.get("category") or raw_place.get("type"))[:40] or None,
        "stay_minutes": _coerce_int(raw_place.get("stay_minutes")),
        "transport_hint": _normalize_text(raw_place.get("transport_hint"))[:120] or None,
        "order": _coerce_int(raw_place.get("order")) or place_index,
        "map_required": bool(raw_place.get("map_required", True)),
        "source_agenda_title": _normalize_text(raw_place.get("source_agenda_title") or source_title)[:120] or None,
    }


def _normalize_route_nodes(raw_day: dict, agenda: list[dict], places: list[dict]) -> list[dict]:
    """中文注释：地图主线节点优先来自 route_nodes，并自动补齐 agenda/places 中出现的真实地点。"""
    nodes: list[dict] = []
    for index, raw_node in enumerate(raw_day.get("route_nodes") or [], start=1):
        if isinstance(raw_node, str):
            raw_node = {"name": raw_node, "order": index}
        if not isinstance(raw_node, dict):
            continue
        node = _coerce_place_payload(raw_node, index)
        if node:
            nodes.append(node)

    for place in places:
        node = _coerce_place_payload(place, _coerce_int(place.get("order")) or len(nodes) + 1)
        if node:
            nodes.append(node)

    for item in agenda:
        raw_name = _normalize_text(item.get("place_name") or item.get("title"))
        name, aliases = _normalize_place_payload_fields(raw_name)
        if not name or _looks_generic_place(name):
            continue
        nodes.append(
            {
                "name": name[:80],
                "aliases": aliases[:4],
                "intro": _normalize_text(item.get("detail"))[:240],
                "category": None,
                "stay_minutes": None,
                "transport_hint": _normalize_text(item.get("transport_hint"))[:120] or None,
                "order": len(nodes) + 1,
                "map_required": True,
                "source_agenda_title": _normalize_text(item.get("title"))[:120] or None,
            }
        )
    repaired = _merge_place_lists([], nodes)
    for index, node in enumerate(repaired, start=1):
        node["order"] = index
    return repaired


def _normalize_food_plan(raw_day: dict) -> dict:
    food = raw_day.get("food_plan") if isinstance(raw_day.get("food_plan"), dict) else {}
    recommendations = _normalize_text_list(food.get("recommendations") or raw_day.get("food_recommendations"), 6, 120)
    snacks = _normalize_text_list(food.get("snacks") or raw_day.get("snacks"), 6, 120)
    if not any([food.get("breakfast"), food.get("lunch"), food.get("dinner"), snacks, recommendations]):
        return {
            "breakfast": "按住宿位置就近安排，减少早晨折返。",
            "lunch": "优先选择当日主线附近的本地餐馆或小吃街。",
            "dinner": "结合夜景或商圈安排晚餐，避免晚间跨城折返。",
            "snacks": [],
            "recommendations": [],
        }
    return {
        "breakfast": _normalize_text(food.get("breakfast"))[:160],
        "lunch": _normalize_text(food.get("lunch"))[:160],
        "dinner": _normalize_text(food.get("dinner"))[:160],
        "snacks": snacks,
        "recommendations": recommendations,
    }


def _normalize_transport_plan(raw_day: dict, route_nodes: list[dict]) -> dict:
    transport = raw_day.get("transport_plan") if isinstance(raw_day.get("transport_plan"), dict) else {}
    segments: list[dict] = []
    for index, raw_segment in enumerate(transport.get("segments") or [], start=1):
        if not isinstance(raw_segment, dict):
            continue
        origin = _canonicalize_place_name(_normalize_text(raw_segment.get("origin"))) or _normalize_text(raw_segment.get("origin"))
        destination = _canonicalize_place_name(_normalize_text(raw_segment.get("destination"))) or _normalize_text(raw_segment.get("destination"))
        segments.append(
            {
                "origin": origin[:80],
                "destination": destination[:80],
                "mode": _normalize_text(raw_segment.get("mode"))[:40],
                "hint": _normalize_text(raw_segment.get("hint"))[:160],
            }
        )
    if not segments and len(route_nodes) >= 2:
        for origin, destination in zip(route_nodes, route_nodes[1:]):
            segments.append(
                {
                    "origin": origin["name"],
                    "destination": destination["name"],
                    "mode": "地铁/步行/短途打车",
                    "hint": destination.get("transport_hint") or "以地图工作台实时路径为准，优先减少折返。",
                }
            )
    return {
        "arrival": _normalize_text(transport.get("arrival"))[:160],
        "city_transport": _normalize_text(transport.get("city_transport") or raw_day.get("transit_hint"))[:200],
        "segments": segments[:10],
    }


def _normalize_day_budget_plan(raw_day: dict, state: TripAgentState) -> dict:
    budget = raw_day.get("budget_plan") if isinstance(raw_day.get("budget_plan"), dict) else {}
    items = budget.get("items") if isinstance(budget.get("items"), list) else []
    normalized_items: list[dict] = []
    for item in items[:6]:
        if not isinstance(item, dict):
            continue
        normalized_items.append(
            {
                "name": _normalize_text(item.get("name"))[:40],
                "amount": _normalize_text(item.get("amount"))[:60],
                "note": _normalize_text(item.get("note"))[:120],
                "ratio": item.get("ratio") if isinstance(item.get("ratio"), (int, float)) else None,
            }
        )
    summary = _normalize_text(budget.get("summary") or raw_day.get("budget_hint"))[:200]
    if not summary:
        budget_value = _parse_budget_value((state.get("slots") or {}).get("budget"))
        summary = f"按总预算约 {budget_value} 元控制单日消费，优先保证交通、住宿与核心体验。" if budget_value else "单日预算待结合住宿和门票继续细化。"
    return {"summary": summary, "items": normalized_items}


def _infer_day_pace(raw_day: dict, node_count: int) -> str:
    if node_count <= 2:
        return "轻松"
    if node_count <= 4:
        return "适中"
    return "偏满，建议保留机动时间"


def _default_weather_backup(payload: dict, raw_day: dict) -> list[str]:
    hint = _normalize_text(raw_day.get("rainy_day_hint") or payload.get("rainy_day_hint"))
    return [hint] if hint else ["遇到降雨时优先切换到室内馆区、商圈、茶馆或展览空间。"]


def _default_risk_notes(payload: dict, raw_day: dict) -> list[str]:
    hint = _normalize_text(raw_day.get("risk_hint") or payload.get("risk_hint"))
    return [hint] if hint else ["热门点位建议提前预约，并在地图工作台确认实时交通时间。"]


def _coerce_int(value: object) -> int | None:
    try:
        parsed = int(str(value).strip())
        return parsed if parsed >= 0 else None
    except (TypeError, ValueError):
        return None


def _coerce_day_number(value: object) -> int | None:
    text = _normalize_text(value)
    if not text:
        return None
    mapping = {
        "\u4e00": 1,
        "\u4e8c": 2,
        "\u4e24": 2,
        "\u4e09": 3,
        "\u56db": 4,
        "\u4e94": 5,
        "\u516d": 6,
        "\u4e03": 7,
    }
    if text.isdigit():
        return int(text)
    for key, number in mapping.items():
        if key in text:
            return number
    return None


def _planner_time_slots() -> list[str]:
    return [
        "\u65e9\u4e0a",
        "\u4e0a\u5348",
        "\u4e2d\u5348",
        "\u4e0b\u5348",
        "\u508d\u665a",
        "\u665a\u4e0a",
        "\u591c\u91cc",
    ]


def _split_route_points(text: str) -> list[str]:
    cleaned = _normalize_text(text)
    cleaned = re.sub(
        r"^(?:\*{0,2})?(?:Day\s*\d+\s*)?(?:\u5f53\u5929\u5730\u70b9\u6e05\u5355|\u8def\u7ebf\u6458\u8981|\u884c\u7a0b\u4e3b\u7ebf)(?:\*{0,2})?[：:]\s*",
        "",
        cleaned,
    )
    parts = [
        item.strip(" -*0123456789.()[]")
        for item in re.split(r"\s*(?:->|=>|>|\\u2192|\\uff5c|\\||\\u3001|\\uff0c|,|\\uff1b|;)\s*", cleaned)
        if item.strip()
    ]
    result: list[str] = []
    for part in parts:
        if _looks_generic_place(part):
            continue
        if part not in result:
            result.append(part[:80])
    return result


def _pick_sentence_for_place(section: str, place_name: str) -> str:
    slot_pattern = "|".join(_planner_time_slots())
    for raw_line in section.splitlines():
        line = _normalize_text(raw_line.strip("-* "))
        if place_name not in line:
            continue
        line = line.replace("**", "")
        line = re.sub(rf"^[0-9]+[.)、]?\s*{re.escape(place_name)}\s*[：:｜-]?\s*", "", line)
        line = re.sub(rf"^(?:{slot_pattern})\s*[：:｜-]?\s*", "", line)
        if line:
            return line[:180]
    return ""


def _extract_named_list_section(section: str, marker: str) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    capture = False
    for raw_line in section.splitlines():
        line = _normalize_text(raw_line)
        if not line:
            if capture:
                break
            continue
        plain = line.replace("**", "")
        if marker in plain:
            capture = True
            continue
        if capture and plain.startswith("###"):
            break
        if not capture:
            continue
        match = re.match(r"^(?:[-*]|\d+[.)、]?)\s*(?P<name>[^：:\n]{2,40})\s*[：:]\s*(?P<intro>.+)$", plain)
        if not match:
            break
        name = _normalize_text(match.group("name"))
        intro = _normalize_text(match.group("intro"))
        if name and not _looks_generic_place(name):
            result.append((name[:80], intro[:180]))
    return result


def _extract_section_hint(answer: str, headings: list[str]) -> str:
    for heading in headings:
        pattern = re.compile(rf"(?ms)^###?\s*{re.escape(heading)}\s*\n(?P<body>.*?)(?=^###?\s*\S|\Z)")
        match = pattern.search(answer)
        if not match:
            continue
        body_lines = [_normalize_text(item.replace("**", "")) for item in match.group("body").splitlines() if _normalize_text(item)]
        if body_lines:
            return body_lines[0][:200]
    return ""


def _build_structured_plan_from_sections(answer: str, state: TripAgentState) -> StructuredTravelPlan | None:
    """?????????????????????????????????????????????"""
    text = _normalize_text(answer)
    if not text:
        return None

    time_slots = _planner_time_slots()
    day_pattern = re.compile(
        r"(?ms)^###?\s*(?:Day\s*(?P<digit>\d+)|\u7b2c\s*(?P<cn>[\u4e00-\u9fff0-9]+)\s*\u5929)(?:\s*[|｜:：-]\s*(?P<title>[^\n]+))?\n(?P<body>.*?)(?=^###?\s*(?:Day\s*\d+|\u7b2c\s*[\u4e00-\u9fff0-9]+\s*\u5929|\u9884\u7b97\u63d0\u793a|\u4ea4\u901a\u5efa\u8bae|\u96e8\u5929\u5907\u9009|\u98ce\u9669\u63d0\u9192|\u51fa\u884c\u63d0\u9192)|\Z)"
    )
    days_payload: list[dict] = []
    for index, match in enumerate(day_pattern.finditer(answer), start=1):
        day_number = _coerce_day_number(match.group("digit") or match.group("cn")) or index
        title = _normalize_text(match.group("title") or f"Day {day_number} \u884c\u7a0b")
        body = match.group("body").strip()
        lines = [_normalize_text(item) for item in body.splitlines() if _normalize_text(item)]

        summary = ""
        for line in lines:
            plain = line.replace("**", "")
            if plain.startswith(("-", "*")) or "\u5f53\u5929\u5730\u70b9\u6e05\u5355" in plain or "\u5f53\u5929\u5730\u70b9\u7b80\u4ecb" in plain or "\u5730\u70b9\u6e05\u5355" in plain or "\u5730\u70b9\u7b80\u4ecb" in plain:
                continue
            if re.match(r"^(?:[0-9]+[.)?]?|(?:%s))" % "|".join(time_slots), plain):
                continue
            summary = plain[:240]
            break

        explicit_route: list[str] = []
        for line in lines:
            plain = line.replace("**", "")
            if "\u5f53\u5929\u5730\u70b9\u6e05\u5355" in plain or "\u5730\u70b9\u6e05\u5355" in plain or "\u8def\u7ebf\u6458\u8981" in plain:
                explicit_route = _split_route_points(plain)
                if explicit_route:
                    break

        intro_pairs = _extract_named_list_section(body, "\u5f53\u5929\u5730\u70b9\u7b80\u4ecb") or _extract_named_list_section(body, "\u5730\u70b9\u7b80\u4ecb")
        seen_places: set[str] = set()
        places_payload: list[dict] = []
        route_candidates = explicit_route or [name for name, _intro in intro_pairs] or _extract_place_names(body)
        for place_index, place_name in enumerate(route_candidates[:8], start=1):
            normalized_name = _normalize_text(place_name)
            if not normalized_name or _looks_generic_place(normalized_name):
                continue
            key = _normalize_compact(normalized_name)
            if key in seen_places:
                continue
            seen_places.add(key)
            intro = next((item_intro for item_name, item_intro in intro_pairs if _normalize_compact(item_name) == key), "")
            if not intro:
                intro = _pick_sentence_for_place(body, normalized_name)
            places_payload.append(
                {
                    "name": normalized_name[:80],
                    "aliases": [],
                    "intro": intro[:180],
                    "category": None,
                    "stay_minutes": None,
                    "transport_hint": None,
                    "order": place_index,
                }
            )

        agenda_payload: list[dict] = []
        for raw_line in lines:
            plain = raw_line.replace("**", "").strip("-* ")
            time_match = re.match(
                r"^(?P<time>%s)\s*[|｜:：-]?\s*(?P<title>[^：:\n]{2,40})(?:[：:]\s*(?P<detail>.+))?$" % "|".join(time_slots),
                plain,
            )
            if not time_match:
                continue
            agenda_payload.append(
                {
                    "time": time_match.group("time"),
                    "title": _normalize_text(time_match.group("title"))[:120],
                    "detail": _normalize_text(time_match.group("detail"))[:600],
                    "place_name": _normalize_text(time_match.group("title"))[:80],
                    "transport_hint": None,
                }
            )
        if not agenda_payload and places_payload:
            for place_index, place in enumerate(places_payload[:4], start=1):
                agenda_payload.append(
                    {
                        "time": time_slots[min(place_index - 1, len(time_slots) - 1)],
                        "title": place["name"],
                        "detail": place["intro"] or "\u53ef\u5728\u8fd9\u4e00\u65f6\u6bb5\u7ee7\u7eed\u7ec6\u5316\u505c\u7559\u65b9\u5f0f\u3002",
                        "place_name": place["name"],
                        "transport_hint": None,
                    }
                )

        if agenda_payload or places_payload:
            days_payload.append(
                {
                    "day": day_number,
                    "title": title[:120],
                    "summary": summary[:240],
                    "route_digest": " -> ".join([place["name"] for place in places_payload[:6]]),
                    "agenda": agenda_payload[:10],
                    "places": places_payload[:10],
                }
            )

    budget_hint = _extract_section_hint(answer, ["\u9884\u7b97\u63d0\u793a"])
    transport_hint = _extract_section_hint(answer, ["\u4ea4\u901a\u5efa\u8bae"])
    rainy_day_hint = _extract_section_hint(answer, ["\u96e8\u5929\u5907\u9009"])
    risk_hint = _extract_section_hint(answer, ["\u98ce\u9669\u63d0\u9192", "\u51fa\u884c\u63d0\u9192"])
    city = _normalize_text((state.get("slots") or {}).get("destination")) or _infer_destination_from_message(state.get("user_message", ""))
    if not city:
        city = _infer_destination_from_message(answer[:120])

    if not days_payload:
        derived_places = _extract_place_names(answer)
        if derived_places:
            fallback_state = {
                **state,
                "planning_place_pool": [{"name": name, "reason": "\u6765\u81ea\u8be6\u7ec6\u653b\u7565\u6b63\u6587"} for name in derived_places],
            }
            return _build_structured_plan_fallback(fallback_state)
        return None

    summary_candidates = [line.strip() for line in answer.splitlines() if line.strip() and not line.strip().startswith("#")]
    trip_summary = summary_candidates[0][:400] if summary_candidates else f"\u5148\u4e3a\u4f60\u6574\u7406\u4e86\u4e00\u7248 {city or '\u76ee\u7684\u5730'} \u53ef\u6267\u884c\u7684\u8be6\u7ec6\u653b\u7565\u3002"
    payload = {
        "city": city,
        "trip_summary": trip_summary,
        "planning_style": _extract_section_hint(answer, ["\u89c4\u5212\u6982\u89c8"]) or "\u8be6\u7ec6\u53ef\u6267\u884c\u65b9\u6848",
        "budget_hint": budget_hint,
        "transport_hint": transport_hint,
        "rainy_day_hint": rainy_day_hint,
        "risk_hint": risk_hint,
        "days": days_payload,
    }
    return _normalize_structured_plan(payload, state)


def _normalize_rich_answer(answer: str) -> str:
    """中文注释：把大模型 Markdown 正文做轻量清洗，便于稳定识别标题、时间段和地点清单。"""
    text = _normalize_text(answer)
    text = text.replace("\u200b", "")
    text = text.replace("**", "")
    text = text.replace("__", "")
    text = text.replace("—", "-")
    text = re.sub(r"\n-{3,}\n", "\n", text)
    return text


def _rich_heading_label(line: str) -> str:
    plain = _normalize_text(line)
    plain = plain.lstrip("#").strip()
    plain = re.sub(r"^[>*-]\s*", "", plain)
    plain = re.sub(r"[:：]\s*$", "", plain)
    return plain


def _split_rich_day_sections(answer: str) -> list[dict]:
    """中文注释：按 Day 标题切分正文，兼容粗体、中文冒号和多级 Markdown 标题。"""
    day_header_pattern = re.compile(
        r"^#{2,6}\s*(?:Day\s*(?P<digit>\d+)(?:[（(][^）)]*[）)])?|第\s*(?P<cn>[\u4e00-\u9fff0-9]+)\s*天)\s*(?:(?:[|｜:：-]\s*|\s+)(?P<title>.+))?$",
        re.IGNORECASE,
    )
    sections: list[dict] = []
    current: dict | None = None
    for raw_line in _normalize_rich_answer(answer).splitlines():
        line = raw_line.rstrip()
        match = day_header_pattern.match(line.strip())
        if match:
            if current and current.get("lines"):
                sections.append(current)
            current = {
                "day": _coerce_day_number(match.group("digit") or match.group("cn")) or len(sections) + 1,
                "title": _normalize_text(match.group("title") or ""),
                "lines": [],
            }
            continue
        if current is not None:
            current["lines"].append(line)
    if current and current.get("lines"):
        sections.append(current)
    return sections


def _extract_rich_section_lines(lines: list[str], headings: list[str]) -> list[str]:
    """中文注释：从 Day 正文中抽取某个子栏目下的正文行，支持项目符号和加粗小标题。"""
    target_labels = {_rich_heading_label(heading) for heading in headings}
    known_labels = {
        "当天地点清单",
        "地点清单",
        "当天地点简介",
        "地点简介",
        "美食安排",
        "交通方式",
        "预算与强度",
        "预算提示",
        "雨天备选",
        "风险提醒",
        "出行提醒",
        "规划概览",
    }
    result: list[str] = []
    capture = False
    for raw_line in lines:
        plain = _normalize_text(raw_line)
        if not plain:
            if capture and result:
                break
            continue
        label = _rich_heading_label(plain)
        if label in target_labels:
            capture = True
            continue
        if capture and (label in known_labels or plain.lstrip().startswith("##")):
            break
        if not capture:
            continue
        cleaned = _normalize_text(re.sub(r"^[>*-]\s*", "", plain))
        if cleaned:
            result.append(cleaned)
    return result


def _extract_overview_lines(answer: str) -> list[str]:
    return _extract_rich_section_lines(_normalize_rich_answer(answer).splitlines(), ["规划概览"])


def _first_line_by_keywords(lines: list[str], keywords: list[str]) -> str:
    for line in lines:
        if all(keyword in line for keyword in keywords):
            return line[:200]
    for line in lines:
        if any(keyword in line for keyword in keywords):
            return line[:200]
    return ""


def _parse_rich_time_blocks(lines: list[str]) -> list[dict]:
    """中文注释：识别“上午/下午/晚上”这类时间块，供攻略正文和地图节点对齐。"""
    time_pattern = re.compile(
        r"^(?P<time>早上|上午|中午|下午|傍晚至夜晚|傍晚|晚上|夜间|全天|午后|午间)(?:\s*[（(][^）)]*[）)])?\s*[:：|｜-]?\s*(?P<title>.*)$"
    )
    known_labels = {
        "当天地点清单",
        "地点清单",
        "当天地点简介",
        "地点简介",
        "美食安排",
        "交通方式",
        "预算与强度",
        "预算提示",
        "雨天备选",
        "风险提醒",
        "出行提醒",
    }
    blocks: list[dict] = []
    current: dict | None = None
    for raw_line in lines:
        plain = _normalize_text(raw_line)
        if not plain:
            continue
        if _rich_heading_label(plain) in known_labels:
            if current and (current.get("title") or current.get("details")):
                blocks.append(current)
            current = None
            continue
        match = time_pattern.match(re.sub(r"^[>*-]\s*", "", plain))
        if match:
            if current and (current.get("title") or current.get("details")):
                blocks.append(current)
            current = {
                "time": _normalize_text(match.group("time")),
                "title": _normalize_text(match.group("title")),
                "details": [],
            }
            continue
        if current is not None:
            current["details"].append(re.sub(r"^[>*-]\s*", "", plain))
    if current and (current.get("title") or current.get("details")):
        blocks.append(current)
    return blocks


def _build_places_from_rich_route(route_candidates: list[str], intro_pairs: list[tuple[str, str]], body: str) -> list[dict]:
    seen_places: set[str] = set()
    places_payload: list[dict] = []
    for place_index, place_name in enumerate(route_candidates[:8], start=1):
        raw_name = _clean_route_style_place_name(place_name) or _normalize_text(place_name)
        normalized_name, aliases = _normalize_place_payload_fields(raw_name)
        if not normalized_name or _looks_generic_place(normalized_name) or _looks_fragmented_place(normalized_name):
            continue
        key = _normalize_compact(normalized_name)
        if key in seen_places:
            continue
        seen_places.add(key)
        intro = next((item_intro for item_name, item_intro in intro_pairs if _normalize_compact(item_name) == key), "")
        if not intro:
            intro = _pick_sentence_for_place(body, normalized_name)
        places_payload.append(
            {
                "name": normalized_name[:80],
                "aliases": aliases[:4],
                "intro": intro[:180],
                "category": None,
                "stay_minutes": None,
                "transport_hint": None,
                "order": place_index,
            }
        )
    return places_payload


def _build_rich_agenda(time_blocks: list[dict], places_payload: list[dict]) -> list[dict]:
    agenda_payload: list[dict] = []
    candidate_names = [item["name"] for item in places_payload]
    consumed_names: set[str] = set()
    for block in time_blocks:
        title_text = _canonicalize_place_name(_normalize_text(block.get("title"))) or _normalize_text(block.get("title"))
        detail = _normalize_text(" ".join(block.get("details") or []))[:600]
        source_text = " ".join([title_text, detail])
        matched_place = next((name for name in candidate_names if name and name in source_text), "")
        if not matched_place and title_text and not _looks_generic_place(title_text) and not _looks_fragmented_place(title_text):
            matched_place = title_text
        if not matched_place:
            remaining = [name for name in candidate_names if name not in consumed_names]
            matched_place = remaining[0] if remaining else ""
        if not matched_place:
            continue
        consumed_names.add(matched_place)
        agenda_payload.append(
            {
                "time": _normalize_text(block.get("time"))[:40],
                "title": matched_place[:120],
                "detail": detail or next((item["intro"] for item in places_payload if item["name"] == matched_place), ""),
                "place_name": (_canonicalize_place_name(matched_place) or matched_place)[:80],
                "transport_hint": "",
            }
        )
    return agenda_payload


PLACE_NOISE_NOTE_PATTERN = re.compile(
    r"(?:\u4e0d\u767b\u5854|\u4e0d\u4e0a\u5854|\u5916\u89c2|\u6253\u5361|\u62cd\u7167\u70b9|\u62cd\u7167\u4f4d|\u89c2\u666f\u4f4d|\u591c\u666f\u6bb5|\u591c\u6e38\u6bb5|\u53ef\u9009|\u5907\u9009|\u6709\u9910\u996e(?:\u7684\u5e97)?|\u987a\u8def|\u9644\u8fd1|\u5468\u8fb9|\u4e00\u5e26|\u7247\u533a|\u533a\u57df|\u5546\u5708|\u5165\u53e3|\u51fa\u53e3|\u96c6\u5408\u70b9|\u7ec8\u70b9|\u8d77\u70b9)",
    re.IGNORECASE,
)
PLACE_BRANCH_NOTE_PATTERN = re.compile(
    r"(?:\u603b\u5e97|\u65d7\u8230\u5e97|\u95e8\u5e97|\u5e97|\u9986|\u7ad9|\u7801\u5934|\u56ed\u533a|\u666f\u533a|\u5e7f\u573a|\u56ed|Loft|LOFT|Park|Mall|K11|in\d+|IN\d+)",
    re.IGNORECASE,
)
PLACE_VERB_PREFIX_PATTERN = re.compile(
    r"^(?:\u524d\u5f80|\u53bb|\u5230|\u62b5\u8fbe|\u5165\u4f4f|\u56de\u5230|\u8fd4\u56de|\u6253\u5361|\u6e38\u89c8|\u901b|\u6f2b\u6b65|\u7ecf\u8fc7|\u987a\u8def\u53bb|\u5148\u53bb|\u518d\u53bb)\s*"
)


def _strip_list_prefix(text: str) -> str:
    """中文注释：清理列表前缀，避免项目符号影响后续抽取。"""
    return re.sub(r"^(?:[>*-]|\d+[.)、])\s*", "", _normalize_text(text))


def _clean_food_sentence(text: str) -> str:
    """中文注释：把美食条目中的标签前缀去掉，保留适合渲染的正文。"""
    sentence = _strip_list_prefix(text)
    sentence = re.sub(
        r"^(?:\u65e9\u9910|\u65e9\u996d|\u5348\u9910|\u5348\u996d|\u4e2d\u9910|\u665a\u9910|\u665a\u996d|\u591c\u5bb5|\u5c0f\u5403|\u52a0\u9910|\u7f8e\u98df\u63a8\u8350|\u9910\u996e\u5efa\u8bae|\u63a8\u8350)\s*[:：-]\s*",
        "",
        sentence,
    )
    return sentence[:160]


def _is_generic_food_sentence(text: str) -> bool:
    plain = _normalize_text(text)
    if not plain:
        return True
    generic_tokens = [
        "\u6309\u4f4f\u5bbf\u4f4d\u7f6e\u5c31\u8fd1\u5b89\u6392",
        "\u4f18\u5148\u9009\u62e9\u5f53\u65e5\u4e3b\u7ebf\u9644\u8fd1",
        "\u7ed3\u5408\u5f53\u5929\u8def\u7ebf\u5c31\u8fd1\u5b89\u6392",
        "\u907f\u514d\u665a\u95f4\u8de8\u57ce\u6298\u8fd4",
        "\u672c\u5730\u9910\u996e",
        "\u7ee7\u7eed\u7ec6\u5316",
    ]
    return any(token in plain for token in generic_tokens)


def _is_generic_transport_sentence(text: str) -> bool:
    plain = _normalize_text(text)
    if not plain:
        return True
    generic_tokens = [
        "\u4ee5\u5730\u56fe\u5de5\u4f5c\u53f0\u5b9e\u65f6\u8def\u7ebf\u4e3a\u51c6",
        "\u4f18\u5148\u51cf\u5c11\u6298\u8fd4",
        "\u4f18\u5148\u4fdd\u6301\u987a\u8def\u52a8\u7ebf",
        "\u5730\u94c1/\u6b65\u884c/\u77ed\u9014\u6253\u8f66",
        "\u4fdd\u6301\u987a\u8def",
    ]
    return any(token in plain for token in generic_tokens)


def _canonicalize_place_name(value: str) -> str:
    """中文注释：去掉地点名里的策略噪音，保留更适合地图识别的主名称。"""
    text = _normalize_text(value)
    if not text:
        return ""
    text = _strip_list_prefix(text)
    text = PLACE_VERB_PREFIX_PATTERN.sub("", text)
    # 中文注释：英文景点名需要保留单词间空格，中文景点名则继续压缩无意义空白。
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[()（）])", "", text)
    text = re.sub(r"(?<=[()（）])\s+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"[|｜].*$", "", text).strip()
    text = re.sub(r"/.*$", "", text).strip()
    parenthetical_notes = re.findall(r"[（(]([^()（）]{1,24})[)）]", text)
    text = re.sub(
        r"[（(]([^()（）]{1,24})[)）]",
        lambda match: "" if PLACE_NOISE_NOTE_PATTERN.search(match.group(1)) else match.group(0),
        text,
    )
    text = re.sub(r"(?:\u9644\u8fd1|\u5468\u8fb9|\u4e00\u5e26|\u7247\u533a|\u533a\u57df)$", "", text).strip()
    text = re.sub(r"(?:\u5165\u53e3|\u51fa\u53e3|\u96c6\u5408\u70b9|\u7ec8\u70b9|\u8d77\u70b9)$", "", text).strip()
    text = re.sub(r"\(([^()/]+?)/[^()]+\)", r"(\1)", text)
    text = text.strip("，。；;、:- ")
    if PLACE_NOISE_NOTE_PATTERN.search(text):
        text = re.sub(r"[（(][^()（）]{1,24}[)）]", "", text).strip()
        text = re.sub(PLACE_NOISE_NOTE_PATTERN, "", text).strip("，。；;、:- ")
    if len(text) <= 2 and parenthetical_notes:
        for note in parenthetical_notes:
            if PLACE_BRANCH_NOTE_PATTERN.search(note) and len(note) >= 2:
                text = note.strip()
                break
    if _looks_generic_place(text) or _looks_fragmented_place(text):
        return ""
    return text[:80]


def _build_place_aliases(name: str, extra_aliases: list[str] | None = None) -> list[str]:
    """中文注释：补充中英别名与括号别名，提高地图与检索命中率。"""
    raw_name = _normalize_text(name)
    candidates = list(extra_aliases or [])
    candidates.extend(re.findall(r"[（(]([^()（）]{1,24})[)）]", raw_name))
    compact = re.sub(r"[（(][^()（）]{1,24}[)）]", "", raw_name).strip()
    if compact and compact != raw_name:
        candidates.append(compact)
    if re.search(r"[A-Za-z]", raw_name):
        candidates.extend(re.findall(r"[A-Za-z][A-Za-z0-9-]{1,24}", raw_name))
    chinese_only = re.sub(r"[A-Za-z0-9\s()（）-]+", "", raw_name).strip()
    if chinese_only and chinese_only != raw_name:
        candidates.append(chinese_only)
    unique: list[str] = []
    for item in candidates:
        alias = _normalize_text(item)
        alias = PLACE_VERB_PREFIX_PATTERN.sub("", alias)
        alias = alias.strip("，。；;、:- ")
        if not alias or alias == name or alias == raw_name:
            continue
        if PLACE_NOISE_NOTE_PATTERN.search(alias) and not PLACE_BRANCH_NOTE_PATTERN.search(alias):
            continue
        if _looks_generic_place(alias) or _looks_fragmented_place(alias):
            continue
        if alias not in unique:
            unique.append(alias[:80])
    return unique[:6]


def _normalize_place_payload_fields(name: str, aliases: list[str] | None = None) -> tuple[str, list[str]]:
    """中文注释：统一地点主名和别名的归一化规则。"""
    canonical = _canonicalize_place_name(name) or _normalize_text(name)
    merged_aliases = _build_place_aliases(name, aliases)
    if canonical in merged_aliases:
        merged_aliases = [item for item in merged_aliases if item != canonical]
    return canonical[:80], merged_aliases[:6]


def _build_food_plan_from_lines(lines: list[str]) -> dict:
    if not lines:
        return {}
    lunch = _first_line_by_keywords(lines, ["午餐"])
    dinner = _first_line_by_keywords(lines, ["晚餐"])
    breakfast = _first_line_by_keywords(lines, ["早餐"])
    recommendations = [line[:120] for line in lines[:6]]
    return {
        "breakfast": breakfast,
        "lunch": lunch,
        "dinner": dinner,
        "recommendations": recommendations,
    }


def _build_food_plan_from_lines(lines: list[str]) -> dict:
    """中文注释：增强版美食段解析，优先拿到早餐/午餐/晚餐和小吃推荐。"""
    if not lines:
        return {}
    breakfast = ""
    lunch = ""
    dinner = ""
    snacks: list[str] = []
    recommendations: list[str] = []
    meal_rules = [
        (re.compile(r"(?:\u65e9\u9910|\u65e9\u996d)"), "breakfast"),
        (re.compile(r"(?:\u5348\u9910|\u5348\u996d|\u4e2d\u9910)"), "lunch"),
        (re.compile(r"(?:\u665a\u9910|\u665a\u996d)"), "dinner"),
        (re.compile(r"(?:\u591c\u5bb5|\u5c0f\u5403|\u52a0\u9910)"), "snacks"),
    ]

    for raw_line in lines:
        line = _strip_list_prefix(raw_line)
        if not line:
            continue
        cleaned = _clean_food_sentence(line)
        matched_label = None
        for pattern, label in meal_rules:
            if pattern.search(line):
                matched_label = label
                break
        if matched_label == "breakfast" and cleaned:
            breakfast = breakfast or cleaned
        elif matched_label == "lunch" and cleaned:
            lunch = lunch or cleaned
        elif matched_label == "dinner" and cleaned:
            dinner = dinner or cleaned
        elif matched_label == "snacks" and cleaned and cleaned not in snacks:
            snacks.append(cleaned)
        if cleaned and cleaned not in recommendations:
            recommendations.append(cleaned[:120])

    if not lunch:
        lunch = _clean_food_sentence(_first_line_by_keywords(lines, ["\u5348\u9910"]) or _first_line_by_keywords(lines, ["\u5348\u996d"]) or "")
    if not dinner:
        dinner = _clean_food_sentence(_first_line_by_keywords(lines, ["\u665a\u9910"]) or _first_line_by_keywords(lines, ["\u665a\u996d"]) or "")
    if not breakfast:
        breakfast = _clean_food_sentence(_first_line_by_keywords(lines, ["\u65e9\u9910"]) or _first_line_by_keywords(lines, ["\u65e9\u996d"]) or "")
    return {
        "breakfast": breakfast,
        "lunch": lunch,
        "dinner": dinner,
        "snacks": snacks[:4],
        "recommendations": recommendations[:6],
    }


def _build_transport_plan_from_lines(lines: list[str], route_nodes: list[dict] | None = None) -> dict:
    """中文注释：增强版交通段解析，补出往返交通和市内串联建议。"""
    route_nodes = route_nodes or []
    arrival = ""
    city_transport = ""
    segments: list[dict] = []
    route_names = [str(item.get("name") or "").strip() for item in route_nodes if str(item.get("name") or "").strip()]

    for raw_line in lines:
        line = _strip_list_prefix(raw_line)
        if not line:
            continue
        cleaned = re.sub(
            r"^(?:\u4ea4\u901a\u65b9\u5f0f|\u4ea4\u901a\u5efa\u8bae|\u4ea4\u901a\u7ec4\u7ec7|\u5e02\u5185\u4ea4\u901a|\u5f80\u8fd4\u4ea4\u901a)\s*[:：-]\s*",
            "",
            line,
        )[:200]
        if not cleaned:
            continue
        if not arrival and any(token in cleaned for token in ["\u9ad8\u94c1", "\u706b\u8f66", "\u62b5\u8fbe", "\u5230\u8fbe", "\u8fd4\u7a0b", "\u51fa\u53d1"]):
            arrival = cleaned
        if any(token in cleaned for token in ["\u5730\u94c1", "\u6b65\u884c", "\u6253\u8f66", "\u516c\u4ea4", "\u9a91\u884c", "\u8f6e\u6e21", "\u8239", "\u9ad8\u94c1"]):
            if not city_transport or _is_generic_transport_sentence(city_transport):
                city_transport = cleaned
        if any(connector in cleaned for connector in ["->", "\u2192", "\u81f3", "\u5230", "\u524d\u5f80"]):
            matched_names = [name for name in route_names if name and name in cleaned]
            if len(matched_names) >= 2:
                segments.append(
                    {
                        "origin": matched_names[0][:80],
                        "destination": matched_names[1][:80],
                        "mode": "\u5730\u94c1/\u6b65\u884c",
                        "hint": cleaned[:160],
                    }
                )

    if not segments and len(route_nodes) >= 2:
        for origin, destination in zip(route_nodes, route_nodes[1:]):
            origin_name = _normalize_text(origin.get("name"))
            destination_name = _normalize_text(destination.get("name"))
            if not origin_name or not destination_name:
                continue
            hint = _normalize_text(destination.get("transport_hint") or city_transport)
            segments.append(
                {
                    "origin": origin_name[:80],
                    "destination": destination_name[:80],
                    "mode": "\u5730\u94c1/\u6b65\u884c/\u77ed\u9014\u6253\u8f66",
                    "hint": hint[:160] if hint else "\u4f18\u5148\u6309\u987a\u8def\u52a8\u7ebf\u8854\u63a5\uff0c\u5b9e\u65f6\u8def\u7ebf\u4ee5\u5730\u56fe\u5de5\u4f5c\u53f0\u4e3a\u51c6\u3002",
                }
            )
    return {
        "arrival": arrival[:160],
        "city_transport": city_transport[:200],
        "segments": segments[:10],
    }


def _extract_section_hint(answer: str, headings: list[str]) -> str:
    normalized = _normalize_rich_answer(answer)
    body_lines = _extract_rich_section_lines(normalized.splitlines(), headings)
    if body_lines:
        return body_lines[0][:200]
    return ""


def _build_structured_plan_from_sections(answer: str, state: TripAgentState) -> StructuredTravelPlan | None:
    """中文注释：把 DeepSeek 详细攻略正文重新抽成稳定结构，保证聊天、地图和工作台共用同一份计划骨架。"""
    text = _normalize_rich_answer(answer)
    if not text:
        return None

    time_slots = _planner_time_slots()
    days_payload: list[dict] = []
    for index, section in enumerate(_split_rich_day_sections(text), start=1):
        day_number = _coerce_day_number(section.get("day")) or index
        title = _normalize_text(section.get("title") or f"Day {day_number} 行程")
        lines = [_normalize_text(item) for item in (section.get("lines") or []) if _normalize_text(item)]
        body = "\n".join(lines)
        if not body:
            continue

        summary = ""
        ignored_labels = {
            "当天地点清单",
            "地点清单",
            "当天地点简介",
            "地点简介",
            "美食安排",
            "交通方式",
            "预算与强度",
            "预算提示",
            "雨天备选",
            "风险提醒",
            "出行提醒",
        }
        for line in lines:
            plain = line.replace("**", "")
            if _rich_heading_label(plain) in ignored_labels:
                continue
            if re.match(r"^(?:[0-9]+[.)、]?|(?:%s))" % "|".join(time_slots), plain):
                continue
            summary = plain[:240]
            break

        route_lines = _extract_rich_section_lines(lines, ["当天地点清单", "地点清单"])
        explicit_route = [
            cleaned
            for line in route_lines
            for cleaned in [_clean_route_style_place_name(line)]
            if cleaned
        ]
        intro_pairs = _extract_named_list_section(body, "当天地点简介") or _extract_named_list_section(body, "地点简介")
        route_candidates = explicit_route or [name for name, _intro in intro_pairs] or _extract_place_names(body)
        places_payload = _build_places_from_rich_route(route_candidates, intro_pairs, body)

        time_blocks = _parse_rich_time_blocks(lines)
        agenda_payload = _build_rich_agenda(time_blocks, places_payload)
        if not agenda_payload and places_payload:
            for place_index, place in enumerate(places_payload[:4], start=1):
                agenda_payload.append(
                    {
                        "time": time_slots[min(place_index - 1, len(time_slots) - 1)],
                        "title": place["name"],
                        "detail": place["intro"] or "可在这一时段继续细化停留方式。",
                        "place_name": place["name"],
                        "transport_hint": None,
                    }
                )

        food_lines = _extract_rich_section_lines(lines, ["美食安排"])
        transport_lines = _extract_rich_section_lines(lines, ["交通方式"])
        budget_lines = _extract_rich_section_lines(lines, ["预算与强度", "预算提示"])
        weather_lines = _extract_rich_section_lines(lines, ["雨天备选"])
        risk_lines = _extract_rich_section_lines(lines, ["风险提醒", "出行提醒"])
        food_plan = _build_food_plan_from_lines(food_lines)
        transport_summary = _first_line_by_keywords(transport_lines, ["交通"]) or (transport_lines[0] if transport_lines else "")
        budget_summary = budget_lines[0][:200] if budget_lines else ""
        pace_level = _first_line_by_keywords(budget_lines, ["强度"])
        if not pace_level:
            pace_level = "轻松" if any(word in body for word in ["轻松", "不想太赶", "休闲", "慢游"]) else ""

        if agenda_payload or places_payload:
            days_payload.append(
                {
                    "day": day_number,
                    "title": title[:120],
                    "summary": summary[:240],
                    "route_digest": " -> ".join([place["name"] for place in places_payload[:6]]),
                    "agenda": agenda_payload[:10],
                    "places": places_payload[:10],
                    "route_nodes": places_payload[:10],
                    "food_plan": food_plan,
                    "transport_plan": {"city_transport": transport_summary},
                    "budget_plan": {"summary": budget_summary},
                    "pace_level": pace_level,
                    "weather_backup": weather_lines[:4],
                    "risk_notes": risk_lines[:4],
                }
            )

    overview_lines = _extract_overview_lines(text)
    budget_hint = _extract_section_hint(text, ["预算提示"]) or _first_line_by_keywords(overview_lines, ["预算"]) or next(
        (day.get("budget_plan", {}).get("summary", "") for day in days_payload if day.get("budget_plan", {}).get("summary")),
        "",
    )
    transport_hint = _extract_section_hint(text, ["交通建议"]) or _first_line_by_keywords(overview_lines, ["交通"]) or next(
        (day.get("transport_plan", {}).get("city_transport", "") for day in days_payload if day.get("transport_plan", {}).get("city_transport")),
        "",
    )
    rainy_day_hint = _extract_section_hint(text, ["雨天备选"]) or next(
        ("；".join(day.get("weather_backup", [])[:2]) for day in days_payload if day.get("weather_backup")),
        "",
    )
    risk_hint = _extract_section_hint(text, ["风险提醒", "出行提醒"]) or next(
        ("；".join(day.get("risk_notes", [])[:2]) for day in days_payload if day.get("risk_notes")),
        "",
    )
    city = _normalize_text((state.get("slots") or {}).get("destination")) or _infer_destination_from_message(state.get("user_message", ""))
    if not city:
        city = _infer_destination_from_message(text[:120])

    if not days_payload:
        derived_places = _extract_place_names(text)
        if derived_places:
            fallback_state = {
                **state,
                "planning_place_pool": [{"name": name, "reason": "来自详细攻略正文"} for name in derived_places],
            }
            return _build_structured_plan_fallback(fallback_state)
        return None

    summary_candidates = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
    trip_summary = summary_candidates[0][:400] if summary_candidates else f"先为你整理了一版 {city or '目的地'} 可执行的详细攻略。"
    payload = {
        "city": city,
        "trip_summary": trip_summary,
        "planning_style": _first_line_by_keywords(overview_lines, ["节奏"]) or _extract_section_hint(text, ["规划概览"]) or "详细可执行方案",
        "budget_hint": budget_hint,
        "transport_hint": transport_hint,
        "rainy_day_hint": rainy_day_hint,
        "risk_hint": risk_hint,
        "days": days_payload,
    }
    return _normalize_structured_plan(payload, state)


def _looks_like_rich_planning_answer(answer: str | None) -> bool:
    text = _normalize_text(answer)
    if len(text) < 420:
        return False
    day_hits = len(re.findall(r"(?i)day\s*\d+|\u7b2c\s*[\u4e00-\u9fff0-9]+\s*\u5929", text))
    if day_hits < 1:
        return False
    return any(
        section in text
        for section in ["\u5f53\u5929\u5730\u70b9\u6e05\u5355", "\u5f53\u5929\u5730\u70b9\u7b80\u4ecb", "\u9884\u7b97\u63d0\u793a", "\u4ea4\u901a\u5efa\u8bae"]
    )


def _rich_answer_has_empty_place_sections(answer: str) -> bool:
    """中文注释：识别“地点清单/地点简介”标题存在但正文为空的坏答案，避免前端出现空白模块。"""
    lines = [_normalize_text(line) for line in answer.splitlines()]
    section_break_pattern = re.compile(
        r"^(?:Day\s*\d+|第\s*[\u4e00-\u9fff0-9]+\s*天|预算提示|交通建议|雨天备选|风险提醒|出行提醒|上午|中午|下午|傍晚|晚上|夜间|全天|早上|午后|午间|(?:[01]?\d|2[0-3]):[0-5]\d)",
        re.IGNORECASE,
    )
    place_heading_pattern = re.compile(r"^(?:当天地点清单|地点清单|当天地点简介|地点简介|景点清单|景点简介)\s*[:：]?\s*$")

    for index, raw_line in enumerate(lines):
        plain = raw_line.replace("**", "").strip("-* ").strip()
        if not plain or not place_heading_pattern.match(plain):
            continue
        next_line = ""
        for candidate in lines[index + 1:]:
            candidate_plain = candidate.replace("**", "").strip("-* ").strip()
            if candidate_plain:
                next_line = candidate_plain
                break
        if not next_line:
            return True
        if place_heading_pattern.match(next_line) or section_break_pattern.match(next_line):
            return True
    return False


def _should_keep_rich_answer(answer: str | None, plan: StructuredTravelPlan, state: TripAgentState) -> bool:
    """中文注释：只有当富文本答案结构完整时才直接采用，否则回退到稳定结构化渲染。"""
    if not _looks_like_rich_planning_answer(answer):
        return False

    normalized = _normalize_text(answer)
    if _rich_answer_has_empty_place_sections(normalized):
        return False
    if not all(section in normalized for section in ["美食安排", "交通方式"]):
        return False

    section_plan = _build_structured_plan_from_sections(normalized, state)
    if not section_plan or not section_plan.days:
        return False

    expected_day_count = len(plan.days)
    candidate_days = section_plan.days[:expected_day_count] if expected_day_count else section_plan.days
    if expected_day_count and len(candidate_days) < expected_day_count:
        return False

    complete_days = sum(1 for day in candidate_days if day.agenda and day.places)
    if complete_days < len(candidate_days):
        return False
    return True


def _compose_planner_answer(plan: StructuredTravelPlan, state: TripAgentState, rich_answer: str | None = None) -> str:
    """????????????????????????????????????"""
    if _should_keep_rich_answer(rich_answer, plan, state):
        return _normalize_text(rich_answer)
    return _render_structured_answer(plan, state)


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
    """???????????????????????????????????????"""
    city = plan.city or str((state.get("slots") or {}).get("destination") or "\u76ee\u7684\u5730")
    lines: list[str] = [f"## {city}\u65c5\u884c\u65b9\u6848"]
    time_slots = _planner_time_slots()

    if plan.trip_summary:
        lines.append(plan.trip_summary)

    overview_lines = [item for item in [plan.planning_style, plan.budget_hint, plan.transport_hint] if item]
    if overview_lines:
        lines.append("")
        lines.append("### \u89c4\u5212\u6982\u89c8")
        for item in overview_lines:
            lines.append(f"- {item}")

    for day in plan.days:
        lines.append("")
        lines.append(f"### Day {day.day} | {day.title}")
        if day.summary:
            lines.append(day.summary)

        agenda = day.agenda or []
        if not agenda and day.places:
            agenda = [
                StructuredAgendaItem(
                    time=time_slots[min(index, len(time_slots) - 1)],
                    title=place.name,
                    detail=place.intro or "\u53ef\u7ee7\u7eed\u7ec6\u5316\u8fd9\u4e00\u65f6\u6bb5\u7684\u505c\u7559\u65b9\u5f0f\u3002",
                    place_name=place.name,
                    transport_hint=place.transport_hint,
                )
                for index, place in enumerate(day.places[:6])
            ]
        for item in agenda[:10]:
            title = item.title or item.place_name or "\u5f85\u8865\u5145\u5b89\u6392"
            detail = item.detail or item.transport_hint or "\u53ef\u7ee7\u7eed\u8865\u5145\u8fd9\u4e00\u65f6\u6bb5\u7684\u5b89\u6392\u7ec6\u8282\u3002"
            if item.time:
                lines.append(f"- **{item.time} | {title}**: {detail}")
            else:
                lines.append(f"- **{title}**: {detail}")

        if day.places:
            lines.append("")
            lines.append(f"**Day {day.day} \u5730\u70b9\u6e05\u5355**")
            lines.append(" -> ".join(place.name for place in day.places[:8]))
            lines.append("")
            lines.append(f"**Day {day.day} \u5730\u70b9\u7b80\u4ecb**")
            for index, place in enumerate(day.places[:8], start=1):
                intro = place.intro or "\u9002\u5408\u4f5c\u4e3a\u8fd9\u4e00\u5929\u7684\u4e3b\u7ebf\u5730\u70b9\u7ee7\u7eed\u5c55\u5f00\u3002"
                suffix = f" ({place.transport_hint})" if place.transport_hint else ""
                lines.append(f"{index}. {place.name}: {intro}{suffix}")

        day_food_items = [
            item
            for item in [day.food_plan.breakfast, day.food_plan.lunch, day.food_plan.dinner, *day.food_plan.recommendations[:3]]
            if item
        ]
        if day_food_items:
            lines.append("")
            lines.append(f"**Day {day.day} 美食安排**")
            for item in day_food_items:
                lines.append(f"- {item}")

        transport_segments = day.transport_plan.segments[:5]
        if day.transport_plan.city_transport or transport_segments:
            lines.append("")
            lines.append(f"**Day {day.day} 交通方式**")
            if day.transport_plan.city_transport:
                lines.append(f"- {day.transport_plan.city_transport}")
            for segment in transport_segments:
                label = " -> ".join([part for part in [segment.origin, segment.destination] if part])
                hint = segment.hint or segment.mode
                if label and hint:
                    lines.append(f"- {label}: {hint}")

        if day.budget_plan.summary or day.pace_level or day.weather_backup or day.risk_notes:
            lines.append("")
            lines.append(f"**Day {day.day} 预算、强度与备选**")
            if day.budget_plan.summary:
                lines.append(f"- 预算: {day.budget_plan.summary}")
            if day.pace_level:
                lines.append(f"- 强度: {day.pace_level}")
            for item in day.weather_backup[:2]:
                lines.append(f"- 雨天备选: {item}")
            for item in day.risk_notes[:2]:
                lines.append(f"- 风险提醒: {item}")

    hint_sections = [
        ("\u9884\u7b97\u63d0\u793a", plan.budget_hint),
        ("\u4ea4\u901a\u5efa\u8bae", plan.transport_hint),
        ("\u96e8\u5929\u5907\u9009", plan.rainy_day_hint),
        ("\u98ce\u9669\u63d0\u9192", plan.risk_hint),
    ]
    available_hints = [(title, content) for title, content in hint_sections if content]
    if available_hints:
        lines.append("")
        lines.append("### \u51fa\u884c\u63d0\u9192")
        for title, content in available_hints:
            lines.append(f"- **{title}**: {content}")

    return "\n".join(lines).strip()


def _parse_budget_value(value: object) -> int | None:
    """中文注释：从预算槽位里提取数值，便于前端做预算分布可视化。"""
    text = _normalize_text(value)
    match = re.search(r"([1-9][0-9]{2,5})", text)
    if not match:
        return None
    return int(match.group(1))


def _build_budget_view(plan: StructuredTravelPlan, state: TripAgentState) -> TravelPlanBudgetView:
    """中文注释：把预算提示整理成卡片化结构，前端不再依赖长文本自行拆分。"""
    budget_value = _parse_budget_value((state.get("slots") or {}).get("budget"))
    days_count = max(1, len(plan.days) or _coerce_days_count((state.get("slots") or {}).get("days"), default=2))
    if budget_value:
        lodging_ratio = 0.34 if days_count <= 2 else 0.38
        transport_ratio = 0.28
        food_ratio = 0.24
        flexible_ratio = max(0.08, 1 - lodging_ratio - transport_ratio - food_ratio)
        items = [
            ("交通", transport_ratio, "优先高铁与地铁，减少临时打车波动"),
            ("住宿", lodging_ratio, f"按 {days_count - 1 if days_count > 1 else 1} 晚舒适型标准预估"),
            ("餐饮", food_ratio, "保留地方美食与夜间加餐弹性"),
            ("机动", flexible_ratio, "给门票、排队和临时调整留余量"),
        ]
        return TravelPlanBudgetView(
            summary=plan.budget_hint or f"按总预算 {budget_value} 元估算，这版方案可以维持舒适但不过度堆叠的节奏。",
            total_hint=f"约 {budget_value} 元",
            items=[
                TravelPlanBudgetItem(
                    name=name,
                    amount=f"{round(budget_value * ratio)} 元",
                    note=note,
                    ratio=round(ratio, 4),
                )
                for name, ratio, note in items
            ],
        )

    fallback_items = [
        TravelPlanBudgetItem(name="交通", amount="待确认", note="可结合铁路工作台锁定主交通成本"),
        TravelPlanBudgetItem(name="住宿", amount="待确认", note="建议先确定酒店带宽，再细化总预算"),
        TravelPlanBudgetItem(name="餐饮", amount="待确认", note="根据美食密度和商圈等级再做浮动"),
    ]
    return TravelPlanBudgetView(
        summary=plan.budget_hint or "当前尚未识别出明确预算，建议先确认总预算或人均带宽。",
        total_hint="待补充",
        items=fallback_items,
    )


def _collect_supplements(plan: StructuredTravelPlan, state: TripAgentState) -> list[TravelPlanSupplement]:
    """中文注释：把玩法补充拆成主题卡片，避免全部挤进主回复正文。"""
    guide_count = len(state.get("retrieved_guides", []))
    web_count = len(state.get("web_items", []))
    modules = state.get("decision_modules") or []
    result: list[TravelPlanSupplement] = []

    result.append(
        TravelPlanSupplement(
            title="出行策略",
            summary=plan.transport_hint or "优先串联主交通和核心景点，降低折返成本。",
            bullets=[
                plan.transport_hint or "优先高铁/地铁主链路，站点周边短距离再用步行或打车。",
                "地图工作台应以结构化地点为准，不再反向解析整段长文。",
                "铁路结果建议先锁定时段，再反推每日景点先后。",
            ],
            tone="info",
        )
    )

    result.append(
        TravelPlanSupplement(
            title="雨天与风险",
            summary=plan.rainy_day_hint or plan.risk_hint or "保持一条室内替代链路，避免天气导致整体失真。",
            bullets=[
                item
                for item in [
                    plan.rainy_day_hint,
                    plan.risk_hint,
                    "热门城市节假日人流和排队波动较大，建议前置预约与错峰。",
                ]
                if item
            ],
            tone="warn",
        )
    )

    result.append(
        TravelPlanSupplement(
            title="检索与证据",
            summary=f"本轮方案已结合 {guide_count} 条本地攻略片段与 {web_count} 条联网来源做交叉参考。",
            bullets=[
                "地图、铁路、天气属于工具真相层，优先级高于自然语言长文。",
                "本地攻略负责风格与玩法参考，联网搜索负责补齐新近变化信息。",
                f"当前决策模块数：{len(modules)}，可继续在决策区做接受、忽略和再优化。",
            ],
            tone="good",
        )
    )
    return result


def _join_non_empty(parts: list[str], limit: int = 240) -> str:
    """中文注释：把多个短句稳定拼成面向前端的单句，避免空字段和重复分隔。"""
    cleaned = [_normalize_text(part) for part in parts]
    unique_parts = list(dict.fromkeys([part for part in cleaned if part]))
    return "；".join(unique_parts)[:limit]


def _build_render_plan(plan: StructuredTravelPlan | None, state: TripAgentState) -> RenderPlan | None:
    """中文注释：基于 structured_plan 生成适合前端正文阅读的 render_plan。"""
    if not plan or not plan.days:
        return None

    city = plan.city or _normalize_text((state.get("slots") or {}).get("destination")) or "目的地"
    best_for = _normalize_text_list(
        [
            plan.planning_style,
            plan.transport_hint,
            plan.budget_hint,
            plan.rainy_day_hint,
        ],
        limit=4,
        max_length=80,
    )

    days: list[RenderPlanDay] = []
    for day in plan.days:
        blocks: list[RenderPlanBlock] = []
        agenda_items = day.agenda[:6]
        for index, item in enumerate(agenda_items, start=1):
            linked_place = next(
                (
                    place
                    for place in (day.route_nodes or day.places)
                    if _normalize_compact(place.name) == _normalize_compact(item.place_name or item.title)
                ),
                None,
            )
            blocks.append(
                RenderPlanBlock(
                    period=_normalize_text(item.time) or f"时段 {index}",
                    title=_normalize_text(item.title) or _normalize_text(item.place_name) or f"Day {day.day} 节点 {index}",
                    description=_normalize_text(item.detail) or (linked_place.intro if linked_place else "") or "建议围绕这一段主线灵活展开。",
                    why_here=(linked_place.intro if linked_place else "") or _normalize_text(day.summary) or _normalize_text(day.route_digest),
                    food_hint=_join_non_empty(
                        [
                            day.food_plan.breakfast if index == 1 else "",
                            day.food_plan.lunch if index <= max(1, len(agenda_items) // 2) else "",
                            day.food_plan.dinner if index == len(agenda_items) else "",
                            *(day.food_plan.recommendations[:1] if not day.food_plan.lunch and not day.food_plan.dinner else []),
                        ],
                        limit=120,
                    ),
                    transport_hint=_normalize_text(item.transport_hint)
                    or (linked_place.transport_hint if linked_place else "")
                    or _normalize_text(day.transport_plan.city_transport)
                    or _normalize_text(day.transport_plan.arrival),
                )
            )

        if not blocks:
            for index, place in enumerate((day.route_nodes or day.places)[:4], start=1):
                blocks.append(
                    RenderPlanBlock(
                        period=f"节点 {index}",
                        title=place.name,
                        description=place.intro or "建议围绕这个地点安排停留与拍照时间。",
                        why_here=_normalize_text(day.summary) or _normalize_text(day.route_digest),
                        food_hint=_join_non_empty(day.food_plan.recommendations[:1], limit=120),
                        transport_hint=_normalize_text(place.transport_hint) or _normalize_text(day.transport_plan.city_transport),
                    )
                )

        photo_tip = ""
        for place in (day.route_nodes or day.places):
            if place.name:
                photo_tip = f"{place.name} 更适合留出一点停留时间拍照和观察城市氛围。"
                break

        reservation_tip = ""
        if day.risk_notes:
            reservation_tip = day.risk_notes[0]
        elif plan.risk_hint:
            reservation_tip = plan.risk_hint

        days.append(
            RenderPlanDay(
                day=day.day,
                title=day.title or f"{city} 第 {day.day} 天",
                positioning=_normalize_text(day.pace_level) or _normalize_text(plan.planning_style) or "轻松游逛",
                route_reason=_normalize_text(day.route_digest) or _normalize_text(day.summary) or "按更顺路的城市动线展开。",
                summary=_join_non_empty(
                    [
                        day.summary,
                        day.route_digest,
                        day.transport_plan.city_transport,
                    ],
                    limit=320,
                ),
                blocks=blocks,
                food_story=_join_non_empty(
                    [
                        day.food_plan.breakfast,
                        day.food_plan.lunch,
                        day.food_plan.dinner,
                        *day.food_plan.recommendations[:2],
                    ],
                    limit=240,
                ),
                photo_tip=photo_tip,
                reservation_tip=_normalize_text(reservation_tip),
                avoidance_tip=_normalize_text(day.risk_notes[1] if len(day.risk_notes) > 1 else "") or _normalize_text(plan.risk_hint),
                fallback_plan=_join_non_empty(day.weather_backup[:2], limit=200) or _normalize_text(plan.rainy_day_hint),
            )
        )

    closing_tips = _normalize_text_list(
        [
            plan.transport_hint,
            plan.budget_hint,
            plan.rainy_day_hint,
            plan.risk_hint,
            *((state.get("guide_coverage") or {}).get("reasons") or []),
        ],
        limit=6,
        max_length=120,
    )

    overview = RenderPlanOverview(
        title=f"{city}{len(plan.days)}日行程攻略",
        positioning=_normalize_text(plan.planning_style) or "可执行旅行方案",
        summary=_normalize_text(plan.trip_summary) or f"这是一版围绕 {city} 展开的可执行攻略，兼顾路线、节奏和落地体验。",
        route_strategy=_join_non_empty(
            [
                plan.transport_hint,
                plan.rainy_day_hint,
                plan.risk_hint,
            ],
            limit=240,
        ),
        best_for=best_for,
    )
    return RenderPlan(overview=overview, days=days, closing_tips=closing_tips)


def _build_render_plan(plan: StructuredTravelPlan | None, state: TripAgentState) -> RenderPlan | None:
    """中文注释：重写 render_plan 生成器，统一对长文本字段做截断，避免富文本计划进入前端时触发校验失败。"""
    if not plan or not plan.days:
        return None

    city = plan.city or _normalize_text((state.get("slots") or {}).get("destination")) or "目的地"
    best_for = _normalize_text_list(
        [plan.planning_style, plan.transport_hint, plan.budget_hint, plan.rainy_day_hint],
        limit=4,
        max_length=80,
    )
    time_slots = _planner_time_slots()
    days: list[RenderPlanDay] = []

    for day in plan.days:
        agenda_items = day.agenda[:6]
        blocks: list[RenderPlanBlock] = []
        for index, item in enumerate(agenda_items, start=1):
            linked_place = next(
                (
                    place
                    for place in (day.route_nodes or day.places)
                    if _normalize_compact(place.name) == _normalize_compact(item.place_name or item.title)
                ),
                None,
            )
            description = _normalize_text(item.detail) or (linked_place.intro if linked_place else "") or "建议围绕这一段主线灵活展开。"
            why_here = (linked_place.intro if linked_place else "") or _normalize_text(day.summary) or _normalize_text(day.route_digest)
            food_hint = _join_non_empty(
                [
                    day.food_plan.breakfast if index == 1 else "",
                    day.food_plan.lunch if index <= max(1, len(agenda_items) // 2) else "",
                    day.food_plan.dinner if index == len(agenda_items) else "",
                    *(day.food_plan.recommendations[:1] if not day.food_plan.lunch and not day.food_plan.dinner else []),
                ],
                limit=160,
            )
            transport_hint = (
                _normalize_text(item.transport_hint)
                or (linked_place.transport_hint if linked_place else "")
                or _normalize_text(day.transport_plan.city_transport)
                or _normalize_text(day.transport_plan.arrival)
            )
            blocks.append(
                RenderPlanBlock(
                    period=(_normalize_text(item.time) or f"时段 {index}")[:40],
                    title=(_normalize_text(item.title) or _normalize_text(item.place_name) or f"Day {day.day} 节点 {index}")[:120],
                    description=description[:320],
                    why_here=why_here[:200],
                    food_hint=food_hint[:160],
                    transport_hint=transport_hint[:160],
                )
            )

        if not blocks:
            for index, place in enumerate((day.route_nodes or day.places)[:4], start=1):
                blocks.append(
                    RenderPlanBlock(
                        period=f"节点 {index}",
                        title=place.name[:120],
                        description=(place.intro or "建议围绕这个地点安排停留与拍照时间。")[:320],
                        why_here=(_normalize_text(day.summary) or _normalize_text(day.route_digest))[:200],
                        food_hint=_join_non_empty(day.food_plan.recommendations[:1], limit=160)[:160],
                        transport_hint=(_normalize_text(place.transport_hint) or _normalize_text(day.transport_plan.city_transport))[:160],
                    )
                )

        photo_tip = ""
        for place in (day.route_nodes or day.places):
            if place.name:
                photo_tip = f"{place.name} 更适合留出一点停留时间拍照和观察城市氛围。"
                break

        reservation_tip = _normalize_text(day.risk_notes[0] if day.risk_notes else "") or _normalize_text(plan.risk_hint)
        days.append(
            RenderPlanDay(
                day=day.day,
                title=(day.title or f"{city} 第 {day.day} 天")[:120],
                positioning=(_normalize_text(day.pace_level) or _normalize_text(plan.planning_style) or "轻松游逛")[:120],
                route_reason=(_normalize_text(day.route_digest) or _normalize_text(day.summary) or "按更顺路的城市动线展开。")[:240],
                summary=_join_non_empty([day.summary, day.route_digest, day.transport_plan.city_transport], limit=320)[:320],
                blocks=blocks,
                food_story=_join_non_empty(
                    [day.food_plan.breakfast, day.food_plan.lunch, day.food_plan.dinner, *day.food_plan.recommendations[:2]],
                    limit=240,
                )[:240],
                photo_tip=photo_tip[:160],
                reservation_tip=reservation_tip[:160],
                avoidance_tip=(_normalize_text(day.risk_notes[1] if len(day.risk_notes) > 1 else "") or _normalize_text(plan.risk_hint))[:160],
                fallback_plan=(_join_non_empty(day.weather_backup[:2], limit=200) or _normalize_text(plan.rainy_day_hint))[:200],
            )
        )

    overview = RenderPlanOverview(
        title=f"{city}{len(plan.days)}日行程攻略"[:120],
        positioning=(_normalize_text(plan.planning_style) or "可执行旅行方案")[:120],
        summary=(_normalize_text(plan.trip_summary) or f"这是围绕 {city} 展开的可执行攻略。")[:400],
        route_strategy=_join_non_empty([plan.transport_hint, plan.rainy_day_hint, plan.risk_hint], limit=240)[:240],
        best_for=best_for,
    )
    closing_tips = _normalize_text_list(
        [
            plan.transport_hint,
            plan.budget_hint,
            plan.rainy_day_hint,
            plan.risk_hint,
            *((state.get("guide_coverage") or {}).get("reasons") or []),
        ],
        limit=6,
        max_length=120,
    )
    return RenderPlan(overview=overview, days=days, closing_tips=closing_tips)


def _build_travel_plan_view(plan: StructuredTravelPlan | None, state: TripAgentState) -> TravelPlanView | None:
    """中文注释：从结构化方案生成页面渲染层，让前端直接渲染成攻略工作台。"""
    if not plan or not plan.days:
        return None

    city = plan.city or _normalize_text((state.get("slots") or {}).get("destination")) or "目的地"
    day_views: list[TravelPlanDayView] = []
    markers: list[TravelPlanMapMarker] = []
    for day in plan.days:
        pois: list[TravelPlanPoiCard] = []
        day_nodes = day.route_nodes or day.places
        route_points = [place.name for place in day_nodes[:12]]
        transport_hints: list[str] = []
        for place in day_nodes[:12]:
            stay_text = f"{place.stay_minutes} 分钟" if place.stay_minutes else ""
            tags = [item for item in [place.category, stay_text] if item]
            if place.transport_hint:
                transport_hints.append(place.transport_hint)
            pois.append(
                TravelPlanPoiCard(
                    name=place.name,
                    intro=place.intro or "适合作为这一天的主线节点继续展开。",
                    category=place.category,
                    stay_text=stay_text,
                    transport_hint=place.transport_hint or "",
                    tags=tags,
                    order=place.order,
                )
            )
            markers.append(
                TravelPlanMapMarker(
                    day=day.day,
                    order=place.order,
                    title=place.name,
                    address=place.transport_hint or "",
                    intro=place.intro or "",
                )
            )

        if not pois and day.agenda:
            for item_index, item in enumerate(day.agenda[:8], start=1):
                place_name = item.place_name or item.title or f"Day {day.day} 节点 {item_index}"
                if item.transport_hint:
                    transport_hints.append(item.transport_hint)
                pois.append(
                    TravelPlanPoiCard(
                        name=place_name,
                        intro=item.detail or "可继续补充这一时段的地点说明。",
                        transport_hint=item.transport_hint or "",
                        tags=[item.time] if item.time else [],
                        order=item_index,
                    )
                )
                markers.append(
                    TravelPlanMapMarker(
                        day=day.day,
                        order=item_index,
                        title=place_name,
                        address=item.transport_hint or "",
                        intro=item.detail or "",
                    )
                )

        transit_hint = "；".join(dict.fromkeys([item for item in transport_hints if item]))[:160]
        strategy = day.summary or day.route_digest or f"Day {day.day} 以 {city} 的核心体验为主，控制节奏，减少无效折返。"
        if day.transport_plan.city_transport:
            transit_hint = day.transport_plan.city_transport[:160]
        map_required_count = sum(1 for place in day_nodes if place.map_required)
        map_node_count = len([place for place in day_nodes if place.name])
        map_completeness = (
            f"完整：{map_node_count}/{map_required_count or map_node_count} 个地图节点"
            if map_required_count <= map_node_count
            else f"待补齐：{map_node_count}/{map_required_count} 个地图节点"
        )
        day_views.append(
            TravelPlanDayView(
                day=day.day,
                title=day.title or f"{city} 第 {day.day} 天",
                summary=day.summary or "",
                strategy=strategy[:240],
                route_digest=day.route_digest or " -> ".join(route_points[:6]),
                route_points=route_points,
                transit_hint=transit_hint,
                agenda=day.agenda[:10],
                pois=pois,
                food_plan=day.food_plan,
                transport_plan=day.transport_plan,
                budget_plan=day.budget_plan,
                pace_level=day.pace_level,
                weather_backup=day.weather_backup,
                risk_notes=day.risk_notes,
                map_node_count=map_node_count,
                map_required_count=map_required_count,
                map_completeness=map_completeness,
            )
        )

    overview_highlights = [
        item
        for item in [plan.planning_style, plan.budget_hint, plan.transport_hint, plan.rainy_day_hint]
        if item
    ]
    action_hints = [
        "查看地图工作台确认路线顺序",
        "将出发地和日期带入 12306 工作台",
        "在可编辑行程中调整景点、交通和预算后继续二次优化",
    ]
    return TravelPlanView(
        overview=TravelPlanOverview(
            title=f"{city}{len(plan.days)}日旅行方案",
            summary=plan.trip_summary or f"这是一版面向执行的 {city} 多日攻略，已经按日拆分核心地点和交通线索。",
            highlights=overview_highlights[:4],
        ),
        map_schedule=TravelPlanMapSchedule(
            city=plan.city,
            title=f"{city} 行程地图主线",
            markers=markers,
        ),
        days=day_views,
        budget=_build_budget_view(plan, state),
        supplements=_collect_supplements(plan, state),
        action_hints=action_hints,
    )


async def _extract_structured_plan_from_answer(answer: str, state: TripAgentState) -> StructuredTravelPlan | None:
    """????????????????????????????????????? JSON ???"""
    if not answer.strip():
        return None

    section_plan = _build_structured_plan_from_sections(answer, state)
    if section_plan and section_plan.days:
        return section_plan

    llm = LlmService()
    if not llm.configured():
        return section_plan

    prompt = "\n".join(
        [
            "Please convert the following China travel guide into strict JSON.",
            "Return JSON only. No explanation. No Markdown.",
            "Required fields: city, trip_summary, planning_style, budget_hint, transport_hint, rainy_day_hint, risk_hint, days.",
            "Each day must include: day, title, summary, route_digest, agenda, places.",
            "Agenda item fields: time, title, detail, place_name, transport_hint.",
            "Place fields: name, aliases, intro, category, stay_minutes, transport_hint, order.",
            f"Target city: {str((state.get('slots') or {}).get('destination') or '').strip() or 'unknown'}",
            f"Candidate places: {state.get('planning_place_pool') or []}",
            "",
            answer[:5000],
        ]
    )
    payload = await llm.json_chat(prompt)
    normalized = _normalize_structured_plan(payload or {}, state)
    return normalized or section_plan


def _structured_plan_quality_score(plan: StructuredTravelPlan | None) -> int:
    """中文注释：为多份候选计划打一个粗粒度质量分，优先选择地点更真实、天数更完整、信息更饱满的一份。"""
    if not plan or not plan.days:
        return -1
    score = len(plan.days) * 20
    for day in plan.days:
        real_places = [place for place in day.places if place.name and not _looks_fragmented_place(place.name)]
        score += len(real_places) * 4
        if day.food_plan.lunch or day.food_plan.dinner:
            score += 3
        if day.transport_plan.city_transport or day.transport_plan.arrival:
            score += 2
        if day.weather_backup:
            score += 1
        if day.risk_notes:
            score += 1
    return score


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


def _merge_unique_texts(items: list[str], limit: int = 6) -> list[str]:
    """中文注释：合并文本列表时去重并保持顺序。"""
    unique: list[str] = []
    for item in items:
        text = _normalize_text(item)
        if text and text not in unique:
            unique.append(text)
        if len(unique) >= limit:
            break
    return unique


def _build_day_section_lookup(answer: str | None) -> dict[int, dict]:
    """中文注释：把 rich answer 按天索引，供后续二次抛光使用。"""
    if not answer:
        return {}
    lookup: dict[int, dict] = {}
    for section in _split_rich_day_sections(_normalize_rich_answer(answer)):
        day_number = _coerce_day_number(section.get("day"))
        if not day_number:
            continue
        lines = [_normalize_text(item) for item in (section.get("lines") or []) if _normalize_text(item)]
        lookup[day_number] = {
            "lines": lines,
            "body": "\n".join(lines),
        }
    return lookup


def _extract_day_section_lines(lines: list[str], headings: list[str]) -> list[str]:
    """中文注释：按标题抽取单日段落，兼容不同写法。"""
    extracted = _extract_rich_section_lines(lines, headings)
    return [_normalize_text(item) for item in extracted if _normalize_text(item)]


def _normalize_place_collection(raw_places: list[dict]) -> list[dict]:
    """中文注释：合并重复地点并同步别名。"""
    merged: list[dict] = []
    index_by_key: dict[str, int] = {}
    for order, raw_place in enumerate(raw_places, start=1):
        payload = _coerce_place_payload(raw_place, _coerce_int(raw_place.get("order")) or order)
        if not payload:
            continue
        key = _normalize_compact(payload.get("name"))
        if not key:
            continue
        if key in index_by_key:
            target = merged[index_by_key[key]]
            target["aliases"] = _merge_unique_texts([*(target.get("aliases") or []), *(payload.get("aliases") or [])], limit=6)
            if not target.get("intro") and payload.get("intro"):
                target["intro"] = payload.get("intro")
            if not target.get("transport_hint") and payload.get("transport_hint"):
                target["transport_hint"] = payload.get("transport_hint")
            continue
        payload["order"] = len(merged) + 1
        merged.append(payload)
        index_by_key[key] = len(merged) - 1
    return merged[:12]


def _normalize_agenda_collection(raw_agenda: list[dict]) -> list[dict]:
    """中文注释：统一 agenda 内的地点标题，减少聊天区与地图区命名漂移。"""
    normalized: list[dict] = []
    for item in raw_agenda:
        title = _canonicalize_place_name(_normalize_text(item.get("title"))) or _normalize_text(item.get("title"))
        place_name = _canonicalize_place_name(_normalize_text(item.get("place_name") or item.get("title"))) or title
        detail = _normalize_text(item.get("detail"))[:600]
        if not title and not detail:
            continue
        normalized.append(
            {
                "time": _normalize_text(item.get("time"))[:40],
                "title": title[:120],
                "detail": detail,
                "place_name": place_name[:80] or None,
                "transport_hint": _normalize_text(item.get("transport_hint"))[:120] or None,
            }
        )
    return normalized[:10]


def _merge_food_plan_payload(current: dict, extracted: dict) -> dict:
    """中文注释：用 richer 的餐饮信息替换明显兜底的旧文本。"""
    current = {**current}
    for field in ["breakfast", "lunch", "dinner"]:
        candidate = _normalize_text(extracted.get(field))
        existing = _normalize_text(current.get(field))
        if candidate and (not existing or _is_generic_food_sentence(existing)):
            current[field] = candidate[:160]
    current["snacks"] = _merge_unique_texts([*(current.get("snacks") or []), *(extracted.get("snacks") or [])], limit=4)
    current["recommendations"] = _merge_unique_texts(
        [*(current.get("recommendations") or []), *(extracted.get("recommendations") or [])],
        limit=6,
    )
    return current


def _merge_transport_plan_payload(current: dict, extracted: dict, route_nodes: list[dict]) -> dict:
    """中文注释：回填更具体的交通叙述和相邻段路线。"""
    current = {**current}
    current_arrival = _normalize_text(current.get("arrival"))
    current_city_transport = _normalize_text(current.get("city_transport"))
    extracted_arrival = _normalize_text(extracted.get("arrival"))
    extracted_city_transport = _normalize_text(extracted.get("city_transport"))
    if extracted_arrival and (not current_arrival or _is_generic_transport_sentence(current_arrival)):
        current["arrival"] = extracted_arrival[:160]
    if extracted_city_transport and (not current_city_transport or _is_generic_transport_sentence(current_city_transport)):
        current["city_transport"] = extracted_city_transport[:200]

    merged_segments: list[dict] = []
    for segment in [*(current.get("segments") or []), *(extracted.get("segments") or [])]:
        origin = _canonicalize_place_name(_normalize_text(segment.get("origin"))) or _normalize_text(segment.get("origin"))
        destination = _canonicalize_place_name(_normalize_text(segment.get("destination"))) or _normalize_text(segment.get("destination"))
        mode = _normalize_text(segment.get("mode"))[:40]
        hint = _normalize_text(segment.get("hint"))[:160]
        if not origin and not destination:
            continue
        key = f"{_normalize_compact(origin)}->{_normalize_compact(destination)}"
        if any(key == f"{_normalize_compact(item.get('origin'))}->{_normalize_compact(item.get('destination'))}" for item in merged_segments):
            continue
        merged_segments.append(
            {
                "origin": origin[:80],
                "destination": destination[:80],
                "mode": mode,
                "hint": hint,
            }
        )
    if not merged_segments and len(route_nodes) >= 2:
        merged_segments = _build_transport_plan_from_lines([], route_nodes).get("segments", [])
    current["segments"] = merged_segments[:10]
    return current


def _collect_day_route_names(agenda: list[dict], route_nodes: list[dict], places: list[dict]) -> list[str]:
    """中文注释：把单日路线里的地点名汇总成稳定顺序，供预算、交通和文案补足复用。"""
    names: list[str] = []
    for place in [*route_nodes, *places]:
        name = _canonicalize_place_name(_normalize_text(place.get("name"))) or _normalize_text(place.get("name"))
        if name and name not in names:
            names.append(name)
    for item in agenda:
        name = _canonicalize_place_name(_normalize_text(item.get("place_name") or item.get("title"))) or _normalize_text(
            item.get("place_name") or item.get("title")
        )
        if name and name not in names:
            names.append(name)
    return names[:8]


def _infer_polished_pace(route_names: list[str], agenda_count: int) -> str:
    """中文注释：按节点数量和时段密度估算单日强度。"""
    intensity = max(len(route_names), agenda_count)
    if intensity <= 2:
        return "轻松"
    if intensity <= 4:
        return "适中"
    return "偏满"


def _prefer_railway_travel(state: TripAgentState | None) -> bool:
    """中文注释：从用户原始问题中识别是否明确偏好高铁或铁路。"""
    if not state:
        return False
    message = _normalize_text(state.get("user_message"))
    return any(token in message for token in ["高铁", "火车", "铁路", "12306"])


def _build_polished_food_plan(current: dict, route_names: list[str], day_number: int) -> dict:
    """中文注释：当模型只给出粗略餐饮字段时，用路线锚点补成更可执行的版本。"""
    next_food = {
        "breakfast": _normalize_text(current.get("breakfast"))[:160],
        "lunch": _normalize_text(current.get("lunch"))[:160],
        "dinner": _normalize_text(current.get("dinner"))[:160],
        "snacks": _merge_unique_texts(list(current.get("snacks") or []), limit=4),
        "recommendations": _merge_unique_texts(list(current.get("recommendations") or []), limit=6),
    }
    lunch_anchor = route_names[min(1, len(route_names) - 1)] if route_names else ""
    dinner_anchor = route_names[-1] if route_names else lunch_anchor

    if not next_food["breakfast"] and day_number == 1:
        next_food["breakfast"] = "早餐以车站或酒店周边简餐为主，避免空腹赶路后再进主线。"
    if not next_food["lunch"] or _is_generic_food_sentence(next_food["lunch"]):
        next_food["lunch"] = (
            f"午餐放在{lunch_anchor}附近解决，优先选择排队可控、翻台快的本地馆子。"
            if lunch_anchor
            else "午餐尽量落在中段节点附近，减少正午跨区折返。"
        )
    if not next_food["dinner"] or _is_generic_food_sentence(next_food["dinner"]):
        next_food["dinner"] = (
            f"晚餐尽量收在{dinner_anchor}附近，方便夜景或返住时顺路结束当天行程。"
            if dinner_anchor
            else "晚餐建议和夜间路线收在同一片区，避免最后一段再次跨城移动。"
        )

    recommendation_candidates = [
        f"{lunch_anchor}适合安排一顿招牌正餐。" if lunch_anchor else "",
        f"{dinner_anchor}附近可以留一顿夜间加餐或小吃。" if dinner_anchor else "",
        "热门餐馆尽量错开 12 点和 18 点整的排队高峰。",
    ]
    next_food["recommendations"] = _merge_unique_texts(
        [*next_food["recommendations"], *recommendation_candidates],
        limit=6,
    )
    if dinner_anchor:
        next_food["snacks"] = _merge_unique_texts([*next_food["snacks"], f"{dinner_anchor}周边留一档轻量小吃"], limit=4)
    return next_food


def _build_polished_transport_plan(
    current: dict,
    route_names: list[str],
    day_number: int,
    state: TripAgentState | None,
) -> dict:
    """中文注释：把交通描述补成真正可执行的顺路动线。"""
    next_transport = {
        "arrival": _normalize_text(current.get("arrival"))[:160],
        "city_transport": _normalize_text(current.get("city_transport"))[:200],
        "segments": list(current.get("segments") or []),
    }
    slots = (state or {}).get("slots") or {}
    origin = _normalize_text(slots.get("origin"))
    destination = _normalize_text(slots.get("destination"))
    rail_preferred = _prefer_railway_travel(state)

    if day_number == 1 and not next_transport["arrival"]:
        if origin and destination:
            travel_mode = "高铁" if rail_preferred else "城际交通"
            next_transport["arrival"] = f"建议从{origin}先到{destination}，抵达后先寄存行李，再用{travel_mode}衔接后的整段白天主线。"
        elif destination:
            next_transport["arrival"] = f"先在{destination}核心区落脚，再展开当天第一段顺路动线。"

    if not next_transport["city_transport"] or _is_generic_transport_sentence(next_transport["city_transport"]):
        if len(route_names) >= 3:
            next_transport["city_transport"] = (
                f"白天按 {route_names[0]} -> {route_names[1]} -> {route_names[-1]} 顺路串联，优先地铁加步行，跨区再短打车收口。"
            )
        elif len(route_names) == 2:
            next_transport["city_transport"] = f"{route_names[0]} 和 {route_names[1]} 建议放在同一天串联，主打地铁或步行，避免无效折返。"
        elif len(route_names) == 1:
            next_transport["city_transport"] = f"{route_names[0]} 作为当天核心片区，围绕同一街区或商圈展开最稳妥。"

    if not next_transport["segments"] and len(route_names) >= 2:
        next_transport["segments"] = [
            {
                "origin": origin_name[:80],
                "destination": destination_name[:80],
                "mode": "地铁/步行/短途打车",
                "hint": "优先按顺路动线串联，实时通勤以地图工作台结果为准。",
            }
            for origin_name, destination_name in zip(route_names, route_names[1:])
        ][:10]
    return next_transport


def _build_polished_budget_plan(
    current: dict,
    route_names: list[str],
    day_number: int,
    total_days: int,
    state: TripAgentState | None,
) -> dict:
    """中文注释：把预算从抽象提示变成按天可读的消费分配建议。"""
    current_summary = _normalize_text(current.get("summary"))[:200]
    current_items = list(current.get("items") or [])
    slots = (state or {}).get("slots") or {}
    total_budget = _parse_budget_value(slots.get("budget"))
    anchors = "、".join(route_names[:2]) or "主线片区"

    summary = current_summary
    if not summary or "待" in summary or "继续" in summary or len(_normalize_compact(summary)) < 14:
        if total_budget:
            if total_days == 1:
                day_budget = total_budget
            elif total_days == 2:
                day_budget = round(total_budget * (0.56 if day_number == 1 else 0.44))
            else:
                day_budget = round(total_budget / max(total_days, 1))
            summary = f"当天按约 {day_budget} 元控制，主要花在{anchors}一线的交通、餐饮和必要门票，避免临时跨区抬高成本。"
        else:
            summary = f"当天支出以{anchors}沿线交通、餐饮和必要门票为主，住宿与大额项目尽量提前锁定。"

    items = current_items[:]
    if not items:
        if total_budget:
            if total_days == 1:
                day_budget = total_budget
            elif total_days == 2:
                day_budget = round(total_budget * (0.56 if day_number == 1 else 0.44))
            else:
                day_budget = round(total_budget / max(total_days, 1))
            ratios = [("交通", 0.2, "高铁、地铁与必要短打车"), ("餐饮", 0.24, "午晚餐和夜间加餐预留")]
            if day_number < total_days:
                ratios.append(("住宿", 0.34, "按舒适型标准预留当晚房费"))
            ratios.append(("机动", max(0.1, 1 - sum(item[1] for item in ratios)), "给门票、排队和临时调整留余量"))
            items = [
                {
                    "name": name,
                    "amount": f"{round(day_budget * ratio)} 元",
                    "note": note,
                    "ratio": ratio,
                }
                for name, ratio, note in ratios
            ]
        else:
            items = [
                {"name": "交通", "amount": "", "note": "优先保证主通勤和最后一段返程", "ratio": None},
                {"name": "餐饮", "amount": "", "note": "围绕当天主线景点和夜间片区安排", "ratio": None},
                {"name": "机动", "amount": "", "note": "给门票、排队和天气变化留余量", "ratio": None},
            ]
    return {"summary": summary[:200], "items": items[:6]}


def _build_polished_weather_backup(current: list[str], route_names: list[str]) -> list[str]:
    """中文注释：雨天备选至少给出可执行切换方式，而不是只留抽象兜底句。"""
    candidates = _normalize_text_list(current, 4, 160)
    if route_names:
        candidates.extend(
            [
                f"如果下雨，先压缩 {route_names[0]} 的室外停留，把主要体验切到周边室内馆、商场或茶馆。",
                f"{route_names[-1]} 可以保留做傍晚收尾，白天景点按天气灵活前后对调。",
            ]
        )
    else:
        candidates.append("遇到降雨时优先把室外景点压缩到拍照和打卡，把长停留转移到室内场景。")
    return _merge_unique_texts(candidates, limit=4)


def _build_polished_risk_notes(current: list[str], route_names: list[str], day_number: int, total_days: int) -> list[str]:
    """中文注释：风险提醒补上错峰、预约和返程机动时间。"""
    candidates = _normalize_text_list(current, 4, 160)
    if route_names:
        candidates.append(f"{route_names[0]} 到 {route_names[-1]} 这条线尽量错峰出发，热门点位提前预约或先取号。")
    if day_number >= total_days:
        candidates.append("返程前至少预留 30 到 40 分钟机动时间，避免最后一段因为排队或堵车压缩离站时间。")
    else:
        candidates.append("夜间收尾尽量靠近住宿区或主地铁线，避免深夜再做长距离折返。")
    return _merge_unique_texts(candidates, limit=4)


def _build_polished_day_summary(current_summary: str, route_names: list[str], pace_level: str, transport_plan: dict) -> str:
    """中文注释：让单日摘要既说明路线，也解释节奏和动线逻辑。"""
    summary = _normalize_text(current_summary)
    if summary and len(_normalize_compact(summary)) >= 18 and "继续细化" not in summary:
        return summary[:240]
    if not route_names:
        return f"这一天建议以{pace_level or '适中'}节奏展开，优先把主体验集中在一个片区内完成。"
    core_route = " -> ".join(route_names[:3])
    transport_brief = _normalize_text(transport_plan.get("city_transport"))
    if transport_brief:
        return f"这一天围绕 {core_route} 展开，整体节奏{pace_level or '适中'}，动线以顺路串联为主，{transport_brief[:80]}。"
    return f"这一天围绕 {core_route} 展开，整体节奏{pace_level or '适中'}，把主要时间留给核心片区而不是跨区折返。"


def _polish_structured_plan(
    plan: StructuredTravelPlan | None,
    rich_answer: str | None,
    state: TripAgentState | None = None,
) -> StructuredTravelPlan | None:
    """中文注释：在最终落状态前统一地点命名，并补足美食/交通细节。"""
    if not plan or not plan.days:
        return plan

    day_lookup = _build_day_section_lookup(rich_answer)
    polished_days: list[dict] = []
    total_days = max(1, len(plan.days))

    for day in plan.days:
        day_payload = day.model_dump()
        section = day_lookup.get(day.day, {})
        section_lines = section.get("lines") or []

        agenda = _normalize_agenda_collection(day_payload.get("agenda") or [])
        places = _normalize_place_collection(day_payload.get("places") or [])
        route_nodes = _normalize_place_collection(day_payload.get("route_nodes") or places or [])
        if not places and agenda:
            places = _derive_places_from_agenda(agenda)
        if route_nodes:
            places = _merge_place_lists(places, route_nodes)[:10]
        elif places:
            route_nodes = places[:]
        if not route_nodes and agenda:
            route_nodes = _normalize_place_collection(_derive_places_from_agenda(agenda))
        if places and len(places) > len(route_nodes):
            route_nodes = _merge_place_lists(route_nodes, places)[:12]

        food_lines = _extract_day_section_lines(
            section_lines,
            ["\u7f8e\u98df\u5b89\u6392", "\u7f8e\u98df\u63a8\u8350", "\u9910\u996e\u5efa\u8bae", "\u5403\u4ec0\u4e48"],
        )
        transport_lines = _extract_day_section_lines(
            section_lines,
            ["\u4ea4\u901a\u65b9\u5f0f", "\u4ea4\u901a\u5efa\u8bae", "\u4ea4\u901a\u7ec4\u7ec7", "\u5e02\u5185\u4ea4\u901a", "\u5f80\u8fd4\u4ea4\u901a"],
        )
        food_plan = _merge_food_plan_payload(day_payload.get("food_plan") or {}, _build_food_plan_from_lines(food_lines))
        transport_plan = _merge_transport_plan_payload(
            day_payload.get("transport_plan") or {},
            _build_transport_plan_from_lines(transport_lines, route_nodes or places),
            route_nodes or places,
        )

        route_digest = " -> ".join([place.get("name", "") for place in (route_nodes or places)[:6] if place.get("name")])
        if not route_digest:
            route_digest = " -> ".join(
                [
                    _canonicalize_place_name(name) or name
                    for name in _split_route_points(day.route_digest)
                    if _canonicalize_place_name(name) or name
                ][:6]
            )

        route_names = _collect_day_route_names(agenda, route_nodes, places)
        pace_level = _normalize_text(day_payload.get("pace_level")) or _infer_polished_pace(route_names, len(agenda))
        food_plan = _build_polished_food_plan(food_plan, route_names, day.day)
        transport_plan = _build_polished_transport_plan(transport_plan, route_names, day.day, state)
        budget_plan = _build_polished_budget_plan(
            day_payload.get("budget_plan") or {},
            route_names,
            day.day,
            total_days,
            state,
        )
        weather_backup = _build_polished_weather_backup(day_payload.get("weather_backup") or [], route_names)
        risk_notes = _build_polished_risk_notes(day_payload.get("risk_notes") or [], route_names, day.day, total_days)
        summary = _build_polished_day_summary(day_payload.get("summary") or "", route_names, pace_level, transport_plan)

        day_payload.update(
            {
                "agenda": agenda[:10],
                "places": places[:10],
                "route_nodes": route_nodes[:12],
                "route_digest": route_digest[:240],
                "food_plan": food_plan,
                "transport_plan": transport_plan,
                "budget_plan": budget_plan,
                "pace_level": pace_level[:60],
                "weather_backup": weather_backup[:4],
                "risk_notes": risk_notes[:4],
                "summary": summary[:240],
            }
        )
        polished_days.append(day_payload)

    payload = plan.model_dump()
    payload["days"] = polished_days
    slots = (state or {}).get("slots") or {}
    city = _normalize_text(payload.get("city") or slots.get("destination"))
    budget_value = _parse_budget_value(slots.get("budget"))
    payload["transport_hint"] = (
        _normalize_text(payload.get("transport_hint"))
        or next(
            (_normalize_text(day.get("transport_plan", {}).get("city_transport")) for day in polished_days if _normalize_text(day.get("transport_plan", {}).get("city_transport"))),
            "",
        )
    )[:200]
    payload["budget_hint"] = (
        _normalize_text(payload.get("budget_hint"))
        or (f"按总预算 {budget_value} 元估算，建议把钱花在主交通、住宿和真正想停留的核心体验上。" if budget_value else "")
        or next(
            (_normalize_text(day.get("budget_plan", {}).get("summary")) for day in polished_days if _normalize_text(day.get("budget_plan", {}).get("summary"))),
            "",
        )
    )[:200]
    payload["rainy_day_hint"] = (
        _normalize_text(payload.get("rainy_day_hint"))
        or next(
            ("；".join(day.get("weather_backup", [])[:2]) for day in polished_days if day.get("weather_backup")),
            "",
        )
    )[:200]
    payload["risk_hint"] = (
        _normalize_text(payload.get("risk_hint"))
        or next(
            ("；".join(day.get("risk_notes", [])[:2]) for day in polished_days if day.get("risk_notes")),
            "",
        )
    )[:200]
    payload["trip_summary"] = (
        _normalize_text(payload.get("trip_summary"))
        or (
            f"这是一版围绕 {city} 展开的 {total_days} 日可执行方案，重点兼顾顺路动线、餐饮体验和临场机动空间。"
            if city
            else ""
        )
        or next((_normalize_text(day.get("summary")) for day in polished_days if _normalize_text(day.get("summary"))), "")
    )[:240]
    try:
        return StructuredTravelPlan.model_validate(payload)
    except ValidationError:
        return plan


async def planner_node(state: TripAgentState) -> TripAgentState:
    """??????????????????????????????????????"""
    llm = LlmService()
    state["planning_place_pool"] = await _build_planning_place_pool(state)

    structured_plan: StructuredTravelPlan | None = None
    structured_plan_from_json: StructuredTravelPlan | None = None
    structured_plan_from_answer: StructuredTravelPlan | None = None
    rich_answer: str | None = None

    planner_payload = await llm.json_chat(_build_planner_prompt(state)) if llm.configured() else None
    if planner_payload:
        structured_plan_from_json = _normalize_structured_plan(planner_payload, state)

    if llm.configured():
        rich_answer = await llm.plain_chat(_build_planner_text_prompt(state))

    if rich_answer:
        structured_plan_from_answer = await _extract_structured_plan_from_answer(rich_answer, state)

    structured_plan = structured_plan_from_json
    if _structured_plan_quality_score(structured_plan_from_answer) > _structured_plan_quality_score(structured_plan_from_json):
        structured_plan = structured_plan_from_answer

    if not structured_plan:
        structured_plan = _build_structured_plan_fallback(state)
    structured_plan = _polish_structured_plan(structured_plan, rich_answer, state)

    state["structured_plan"] = structured_plan.model_dump() if structured_plan else None
    state["itinerary"] = _build_itinerary_from_structured_plan(structured_plan)
    if structured_plan:
        state["final_answer"] = _compose_planner_answer(structured_plan, state, rich_answer)
    else:
        state["final_answer"] = rich_answer or compose_fallback_answer(state)
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
    try:
        structured_plan = StructuredTravelPlan.model_validate(state["structured_plan"]) if state.get("structured_plan") else None
    except ValidationError:
        structured_plan = None
    state["render_plan"] = _build_render_plan(structured_plan, state)
    state["travel_plan_view"] = _build_travel_plan_view(structured_plan, state)
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
