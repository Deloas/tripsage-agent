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
    map_required: bool = True
    source_agenda_title: str | None = Field(default=None, max_length=120)


class StructuredTransportSegment(BaseModel):
    """中文注释：单日内相邻地点之间的交通建议。"""

    origin: str = Field(default="", max_length=80)
    destination: str = Field(default="", max_length=80)
    mode: str = Field(default="", max_length=40)
    hint: str = Field(default="", max_length=160)


class StructuredDayTransportPlan(BaseModel):
    """中文注释：单日交通方案，给前端和地图工作台直接消费。"""

    arrival: str = Field(default="", max_length=160)
    city_transport: str = Field(default="", max_length=200)
    segments: list[StructuredTransportSegment] = Field(default_factory=list)


class StructuredFoodPlan(BaseModel):
    """中文注释：单日美食安排，避免攻略只剩景点。"""

    breakfast: str = Field(default="", max_length=160)
    lunch: str = Field(default="", max_length=160)
    dinner: str = Field(default="", max_length=160)
    snacks: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class StructuredBudgetPlan(BaseModel):
    """中文注释：单日预算拆分，便于前端显示成本判断。"""

    summary: str = Field(default="", max_length=200)
    items: list[dict] = Field(default_factory=list)


class StructuredPlanDay(BaseModel):
    """中文注释：一天的结构化方案，同时包含详细安排和精简地点清单。"""

    day: int = Field(ge=1, le=30)
    title: str = Field(default="", max_length=120)
    summary: str = Field(default="", max_length=240)
    route_digest: str = Field(default="", max_length=240)
    agenda: list[StructuredAgendaItem] = Field(default_factory=list)
    places: list[StructuredPlaceBrief] = Field(default_factory=list)
    route_nodes: list[StructuredPlaceBrief] = Field(default_factory=list)
    food_plan: StructuredFoodPlan = Field(default_factory=StructuredFoodPlan)
    transport_plan: StructuredDayTransportPlan = Field(default_factory=StructuredDayTransportPlan)
    budget_plan: StructuredBudgetPlan = Field(default_factory=StructuredBudgetPlan)
    pace_level: str = Field(default="", max_length=60)
    weather_backup: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)


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


class TravelPlanOverview(BaseModel):
    """中文注释：攻略详情页顶部总览模块。"""

    title: str = Field(default="", max_length=120)
    summary: str = Field(default="", max_length=400)
    highlights: list[str] = Field(default_factory=list)


class TravelPlanMapMarker(BaseModel):
    """中文注释：地图工作台和攻略详情页共用的地点锚点。"""

    day: int = Field(ge=1, le=30)
    order: int | None = Field(default=None, ge=1, le=20)
    title: str = Field(default="", max_length=80)
    address: str = Field(default="", max_length=160)
    intro: str = Field(default="", max_length=240)


class TravelPlanMapSchedule(BaseModel):
    """中文注释：页面渲染层消费的轻量地图计划。"""

    city: str | None = Field(default=None, max_length=80)
    title: str = Field(default="", max_length=120)
    markers: list[TravelPlanMapMarker] = Field(default_factory=list)


class TravelPlanPoiCard(BaseModel):
    """中文注释：前端按地点渲染的景点卡片数据。"""

    name: str = Field(default="", max_length=80)
    intro: str = Field(default="", max_length=240)
    category: str | None = Field(default=None, max_length=40)
    stay_text: str = Field(default="", max_length=60)
    transport_hint: str = Field(default="", max_length=120)
    tags: list[str] = Field(default_factory=list)
    order: int | None = Field(default=None, ge=1, le=20)


class TravelPlanDayView(BaseModel):
    """中文注释：攻略详情页的单日视图模型。"""

    day: int = Field(ge=1, le=30)
    title: str = Field(default="", max_length=120)
    summary: str = Field(default="", max_length=240)
    strategy: str = Field(default="", max_length=240)
    route_digest: str = Field(default="", max_length=240)
    route_points: list[str] = Field(default_factory=list)
    transit_hint: str = Field(default="", max_length=160)
    agenda: list[StructuredAgendaItem] = Field(default_factory=list)
    pois: list[TravelPlanPoiCard] = Field(default_factory=list)
    food_plan: StructuredFoodPlan = Field(default_factory=StructuredFoodPlan)
    transport_plan: StructuredDayTransportPlan = Field(default_factory=StructuredDayTransportPlan)
    budget_plan: StructuredBudgetPlan = Field(default_factory=StructuredBudgetPlan)
    pace_level: str = Field(default="", max_length=60)
    weather_backup: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    map_node_count: int = Field(default=0, ge=0, le=50)
    map_required_count: int = Field(default=0, ge=0, le=50)
    map_completeness: str = Field(default="", max_length=80)


class TravelPlanBudgetItem(BaseModel):
    """中文注释：预算卡片中的单项条目。"""

    name: str = Field(default="", max_length=40)
    amount: str = Field(default="", max_length=60)
    note: str = Field(default="", max_length=120)
    ratio: float | None = Field(default=None, ge=0, le=1)


class TravelPlanBudgetView(BaseModel):
    """中文注释：攻略详情页预算模块。"""

    summary: str = Field(default="", max_length=240)
    total_hint: str = Field(default="", max_length=80)
    items: list[TravelPlanBudgetItem] = Field(default_factory=list)


class TravelPlanSupplement(BaseModel):
    """中文注释：补充信息模块，承载雨天、风险、玩法等补充提示。"""

    title: str = Field(default="", max_length=60)
    summary: str = Field(default="", max_length=240)
    bullets: list[str] = Field(default_factory=list)
    tone: str = Field(default="info", max_length=20)


class TravelPlanView(BaseModel):
    """中文注释：给前端详情页使用的页面级攻略渲染数据。"""

    overview: TravelPlanOverview
    map_schedule: TravelPlanMapSchedule | None = None
    days: list[TravelPlanDayView] = Field(default_factory=list)
    budget: TravelPlanBudgetView | None = None
    supplements: list[TravelPlanSupplement] = Field(default_factory=list)
    action_hints: list[str] = Field(default_factory=list)


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
    travel_plan_view: TravelPlanView | None = None
    tool_calls: list[ToolCallView] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    decision_modules: list[DecisionModule] = Field(default_factory=list)
