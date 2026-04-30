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
    tool_calls: list[ToolCallView] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    decision_modules: list[DecisionModule] = Field(default_factory=list)
