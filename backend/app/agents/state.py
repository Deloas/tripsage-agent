from typing import TypedDict


class TripAgentState(TypedDict, total=False):
    """LangGraph 状态草案；当前骨架服务也沿用这组字段。"""

    conversation_id: str
    user_message: str
    context: dict
    search_mode: str
    persist_session: bool
    db: object
    intent: str
    confidence: float
    slots: dict
    missing_slots: list[str]
    retrieved_guides: list[dict]
    guide_items: list
    web_items: list
    railway_results: list[dict]
    railway_result: dict
    weather_results: list[dict]
    weather_result: dict
    map_results: list[dict]
    route_result: dict
    tool_calls: list[dict]
    tool_calls_view: list
    itinerary: list
    cards: list
    sources: list
    decision_modules: list
    final_answer: str
    warnings: list[str]
