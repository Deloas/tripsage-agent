from pydantic import BaseModel, Field

from app.schemas.common import SourceRef


class GuideCreateRequest(BaseModel):
    """新增攻略请求。"""

    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=20, max_length=30000)
    source_url: str | None = None
    source_type: str = "manual"
    category: str | None = None
    raw_url: str | None = None
    resolved_url: str | None = None
    crawl_status: str = "indexed"


class GuideItem(BaseModel):
    """攻略列表项。"""

    id: int
    title: str
    city: str
    summary: str
    source_url: str | None = None
    source_type: str | None = None
    category: str | None = None
    crawl_status: str | None = None


class GuideSourceItem(BaseModel):
    """攻略来源列表项，包含待处理的微博入口。"""

    id: int
    title: str
    source_type: str
    source_url: str | None = None
    raw_url: str | None = None
    category: str | None = None
    crawl_status: str


class GuideCreateResponse(BaseModel):
    """新增攻略响应。"""

    guide_id: int
    city: str
    chunks: int
    indexed: bool
    extracted: dict


class GuideSearchRequest(BaseModel):
    """攻略搜索请求。"""

    query: str = Field(min_length=1, max_length=1000)
    city: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class GuideSearchItem(BaseModel):
    """攻略检索命中的片段。"""

    guide_id: int
    chunk_id: str
    title: str
    city: str
    content: str
    score: float
    source: SourceRef
