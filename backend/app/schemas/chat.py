from pydantic import BaseModel, Field

from app.schemas.common import ResultCard, SourceRef, ToolCallView


class ChatRequest(BaseModel):
    """聊天请求。"""

    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)
    context: dict = Field(default_factory=dict)
    search_mode: str = Field(default="auto", pattern="^(local_only|web_enhanced|auto)$")


class ItineraryBlock(BaseModel):
    """前端时间轴中的单个行程块。"""

    day: int
    title: str
    items: list[dict]


class StructuredAgendaItem(BaseModel):
    """中文注释：给前端详细行程和可编辑草案使用的日程项。"""

    time: str = Field(default="", max_length=40)
    title: str = Field(default="", max_length=120)
    detail: str = Field(default="", max_length=600)
    place_name: str | None = Field(default=None, max_length=80)
    transport_hint: str | None = Field(default=None, max_length=120)


class StructuredPlaceBrief(BaseModel):
    """中文注释：给地图和地点简介使用的标准地点摘要。"""

    name: str = Field(min_length=1, max_length=80)
    aliases: list[str] = Field(default_factory=list)
    intro: str = Field(default="", max_length=240)
    category: str | None = Field(default=None, max_length=40)
    stay_minutes: int | None = Field(default=None, ge=0, le=1440)
    transport_hint: str | None = Field(default=None, max_length=120)
    order: int | None = Field(default=None, ge=1, le=20)


class StructuredPlanDay(BaseModel):
    """中文注释：一天的结构化方案，同时包含详细安排和精简地点清单。"""

    day: int = Field(ge=1, le=30)
    title: str = Field(default="", max_length=120)
    summary: str = Field(default="", max_length=240)
    route_digest: str = Field(default="", max_length=240)
    agenda: list[StructuredAgendaItem] = Field(default_factory=list)
    places: list[StructuredPlaceBrief] = Field(default_factory=list)


class StructuredTravelPlan(BaseModel):
    """中文注释：智能体正式输出的结构化行程，地图与工作台优先消费它。"""

    city: str | None = Field(default=None, max_length=80)
    trip_summary: str = Field(default="", max_length=400)
    planning_style: str = Field(default="", max_length=120)
    budget_hint: str = Field(default="", max_length=200)
    transport_hint: str = Field(default="", max_length=200)
    rainy_day_hint: str = Field(default="", max_length=200)
    risk_hint: str = Field(default="", max_length=200)
    days: list[StructuredPlanDay] = Field(default_factory=list)


class DecisionModule(BaseModel):
    """前端决策工作台模块，用于把长文本规划拆成可视化判断。"""

    type: str
    title: str
    level: str = "info"
    summary: str
    points: list[str] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)


class ChatResponse(BaseModel):
    """聊天响应主体。"""

    conversation_id: str
    answer: str
    intent: str
    cards: list[ResultCard] = Field(default_factory=list)
    itinerary: list[ItineraryBlock] | None = None
    structured_plan: StructuredTravelPlan | None = None
    tool_calls: list[ToolCallView] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    decision_modules: list[DecisionModule] = Field(default_factory=list)
