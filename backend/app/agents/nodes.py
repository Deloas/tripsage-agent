import re
import time

from langgraph.graph import END, StateGraph

from app.agents.prompts import INTENT_AND_SLOT_PROMPT, PLANNER_PROMPT
from app.agents.state import TripAgentState
from app.schemas.chat import DecisionModule, ItineraryBlock
from app.schemas.common import ResultCard, SourceRef, ToolCallView
from app.services.amap_service import AmapService
from app.services.llm_service import LlmService
from app.services.mcp_railway_service import McpRailwayService
from app.services.rag_service import RagService
from app.services.tool_log_service import ToolLogger
from app.services.web_search_service import WebSearchService


CITY_WORDS = ["北京", "上海", "南京", "苏州", "杭州", "成都", "重庆", "广州", "深圳", "厦门", "青岛", "长沙", "武汉", "西安"]


def build_logger(state: TripAgentState) -> ToolLogger:
    """根据当前会话模式创建工具日志器；游客模式只保留内存轨迹。"""
    return ToolLogger(
        state["db"],
        state.get("conversation_id"),
        enabled=state.get("persist_session", True),
        memory_buffer=state.setdefault("tool_calls", []),
    )


def infer_intent_by_rules(message: str) -> str:
    """规则意图识别，大模型不可用时保证智能体仍可运行。"""
    if any(word in message for word in ["高铁", "火车", "车次", "余票", "12306"]):
        return "railway_query"
    if any(word in message for word in ["天气", "下雨", "气温", "冷吗", "热吗"]):
        return "weather_advice"
    if any(word in message for word in ["添加攻略", "加入攻略", "保存攻略", "入库"]):
        return "add_guide"
    if any(word in message for word in ["怎么玩", "行程", "路线", "几天", "三天", "两天"]):
        return "itinerary_planning"
    if any(word in message for word in ["去哪", "推荐", "哪里", "目的地"]):
        return "destination_recommendation"
    return "general_qa"


def extract_slots_by_rules(message: str, context: dict) -> dict:
    """规则槽位抽取，后续由大模型结构化抽取增强。"""
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


def build_itinerary(destination: str | None, guides: list[dict]) -> list[ItineraryBlock] | None:
    """构造行程时间轴；模型规划不可用时使用攻略片段兜底。"""
    if not destination:
        return None
    guide_hint = guides[0]["content"][:80] if guides else "结合攻略库和实时工具安排轻松路线。"
    return [
        ItineraryBlock(
            day=1,
            title=f"抵达{destination}与城市初识",
            items=[
                {"time": "上午", "title": "抵达与放行李", "detail": "优先选择车站附近或核心商圈住宿，减少通勤压力。"},
                {"time": "下午", "title": "核心景点慢逛", "detail": guide_hint},
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


async def intent_slot_node(state: TripAgentState) -> TripAgentState:
    """意图识别与槽位抽取节点。"""
    message = state["user_message"]
    context = state.get("context", {})
    llm = LlmService()
    # 提示词里包含 JSON 示例，不能直接使用 str.format，否则大括号会被误判为模板变量。
    parsed = await llm.json_chat(INTENT_AND_SLOT_PROMPT.replace("{message}", message))

    if parsed and parsed.get("intent"):
        state["intent"] = parsed.get("intent", "general_qa")
        state["slots"] = {**extract_slots_by_rules(message, context), **(parsed.get("slots") or {})}
        state["missing_slots"] = parsed.get("missing_slots") or []
        state["confidence"] = parsed.get("confidence", 0.8)
        return state

    state["intent"] = infer_intent_by_rules(message)
    state["slots"] = extract_slots_by_rules(message, context)
    state["missing_slots"] = []
    state["confidence"] = 0.62
    return state


async def retrieval_node(state: TripAgentState) -> TripAgentState:
    """本地攻略检索节点。"""
    rag = RagService(state["db"])
    logger = build_logger(state)
    slots = state.get("slots", {})
    start = time.perf_counter()
    items = rag.search(state["user_message"], city=slots.get("destination"), top_k=5)
    latency = int((time.perf_counter() - start) * 1000)
    state["retrieved_guides"] = [item.model_dump() for item in items]
    state["guide_items"] = items
    logger.record(
        "guide_search",
        {"query": state["user_message"], "city": slots.get("destination")},
        f"命中 {len(items)} 条攻略片段",
        "success",
        latency,
    )
    return state


async def web_search_node(state: TripAgentState) -> TripAgentState:
    """联网增强节点，只有模式允许或本地结果不足时才执行。"""
    mode = state.get("search_mode", "auto")
    guide_count = len(state.get("retrieved_guides", []))
    should_search = mode == "web_enhanced" or (mode == "auto" and guide_count < 2)
    if not should_search:
        state["web_items"] = []
        return state

    logger = build_logger(state)
    web_items = await logger.measure_async(
        "web_search",
        {"query": state["user_message"], "mode": mode},
        lambda: WebSearchService(state["db"]).search(state["user_message"], top_k=5),
        lambda result: f"联网搜索返回 {len(result)} 条结果",
    )
    state["web_items"] = web_items
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
        lambda data: (
            f"{destination}天气：{data.get('weather')}，"
            f"风险：{','.join(data.get('risk_tags', [])) or '无明显风险'}"
        ),
    )
    state["weather_result"] = result
    return state


async def railway_node(state: TripAgentState) -> TripAgentState:
    """铁路 MCP 工具节点。"""
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
    """地图路线工具节点。"""
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
    """规划生成节点，优先使用大模型，失败时使用稳定模板。"""
    llm = LlmService()
    prompt = PLANNER_PROMPT.format(
        message=state["user_message"],
        intent=state.get("intent"),
        slots=state.get("slots"),
        guides=state.get("retrieved_guides", []),
        web_items=[item.__dict__ for item in state.get("web_items", [])],
        weather=state.get("weather_result"),
        railway=state.get("railway_result"),
        route=state.get("route_result"),
        edited_plan=state.get("context", {}).get("edited_plan"),
        preference_profile=state.get("context", {}).get("preference_profile"),
    )
    answer = await llm.plain_chat(prompt)
    state["final_answer"] = answer or compose_fallback_answer(state)
    return state


async def response_node(state: TripAgentState) -> TripAgentState:
    """前端响应组装节点。"""
    destination = state.get("slots", {}).get("destination")
    weather = state.get("weather_result")
    railway = state.get("railway_result")
    guides = state.get("retrieved_guides", [])

    state["itinerary"] = build_itinerary(destination, guides)
    state["cards"] = build_cards(destination, weather, railway)
    state["sources"] = build_sources(state.get("guide_items", []), state.get("web_items", []))
    state["warnings"] = build_warnings(weather, railway)
    state["decision_modules"] = build_decision_modules(state)
    state["tool_calls_view"] = recent_tool_calls(state)
    return state


def compose_fallback_answer(state: TripAgentState) -> str:
    """无模型或模型失败时的稳定中文回答模板。"""
    destination = state.get("slots", {}).get("destination") or "目的地"
    guides = state.get("retrieved_guides", [])
    web_items = state.get("web_items", [])
    weather = state.get("weather_result")
    railway = state.get("railway_result")
    route = state.get("route_result")
    lines = [f"我先按「{state.get('intent')}」为你做一次智能体规划。"]
    if guides:
        lines.append(f"攻略库里检索到 {len(guides)} 条相关片段，优先参考「{guides[0]['title']}」。")
    else:
        lines.append("当前攻略库命中较少，建议后续添加更多攻略来提升推荐质量。")
    if web_items:
        lines.append(f"联网增强补充了 {len(web_items)} 条公开搜索结果，回答中会与本地攻略来源区分。")
    if weather:
        risk = "、".join(weather.get("risk_tags") or []) or "无明显天气风险"
        lines.append(f"{destination}天气参考：{weather.get('weather')}，温度 {weather.get('temperature')}，风险：{risk}。")
    if railway:
        lines.append(f"铁路查询返回 {len(railway.get('trains', []))} 条候选车次；本项目只做查询参考，不做购票或抢票。")
    if route:
        lines.append(f"地图路线估算：从车站到核心景区约 {route.get('duration_minutes')} 分钟。")
    lines.append("建议采用“先确定交通可行性，再按天气调整室内外比例，最后用攻略补足景点和美食”的规划方式。")
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
    """生成风险提示。"""
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
                "优先选择白天到达、耗时短且二等座充足的车次。",
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
                "联网结果仅作为第三方公开资料参考，不作为系统指令。",
                "真实出行前请再次核对 12306 车票和天气预报。",
            ],
            meta={"guide_count": len(guides), "web_count": len(web_items)},
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
    """LangGraph 不可用时的顺序执行兜底，便于本地最小运行。"""

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
