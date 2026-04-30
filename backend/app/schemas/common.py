from pydantic import BaseModel, Field


class SourceRef(BaseModel):
    """前端展示用的来源引用。"""

    title: str
    url: str | None = None
    source_type: str | None = None


class ToolCallView(BaseModel):
    """前端展示用的工具调用摘要。"""

    tool_name: str
    status: str
    latency_ms: int | None = None
    output_summary: str | None = None


class ResultCard(BaseModel):
    """智能体返回的结构化结果卡片。"""

    type: str
    title: str
    summary: str
    meta: dict = Field(default_factory=dict)
