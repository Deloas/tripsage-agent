from pydantic import BaseModel, Field


class PlanVersionCreate(BaseModel):
    """前端保存方案版本的请求体。"""

    id: str = Field(min_length=4, max_length=80)
    conversation_id: str = Field(min_length=4, max_length=64)
    name: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=200)
    response: dict
    created_at: str | None = None


class PlanVersionView(BaseModel):
    """返回给前端的方案版本视图，使用前端友好的 camelCase 字段。"""

    id: str
    conversation_id: str
    name: str
    reason: str
    response: dict
    createdAt: str


class PlanVersionCompareView(BaseModel):
    """两个版本之间的差异摘要。"""

    base_id: str
    target_id: str
    title: str
    summary: str
    metrics: dict = Field(default_factory=dict)
    highlights: list[str] = Field(default_factory=list)


class PlanExportRequest(BaseModel):
    """方案导出请求。"""

    version_id: str = Field(min_length=4, max_length=80)
    format: str = Field(default="markdown", pattern="^(markdown|html)$")


class PlanExportView(BaseModel):
    """方案导出结果。"""

    filename: str
    mime_type: str
    content: str


class SharedPlanCreate(BaseModel):
    """创建只读分享页的请求。"""

    version_id: str = Field(min_length=4, max_length=80)


class SharedPlanView(BaseModel):
    """只读分享页数据。"""

    id: str
    version_id: str
    conversation_id: str
    title: str
    response: dict
    createdAt: str
