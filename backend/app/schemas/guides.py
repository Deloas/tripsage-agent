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
    author: str | None = None


class GuideLinkImportRequest(BaseModel):
    """通用攻略链接导入请求。"""

    url: str = Field(min_length=8, max_length=1000)
    category: str | None = Field(default=None, max_length=120)
    force_reimport: bool = False


class GuideLinkImportConfirmRequest(BaseModel):
    """确认入库一条已抓取或用户修订后的链接攻略。"""

    url: str = Field(min_length=8, max_length=1000)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=20, max_length=50000)
    category: str | None = Field(default=None, max_length=120)
    source_type: str = Field(default="link_confirmed", max_length=60)
    resolved_url: str | None = Field(default=None, max_length=1000)
    author: str | None = Field(default=None, max_length=120)
    structured: dict | None = None
    force_reimport: bool = False


class GuideUpdateRequest(BaseModel):
    """更新已入库攻略请求。"""

    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=20, max_length=50000)
    category: str | None = Field(default=None, max_length=120)
    author: str | None = Field(default=None, max_length=120)
    source_url: str | None = Field(default=None, max_length=1000)
    structured: dict | None = None


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


class GuideImportRecordItem(BaseModel):
    """攻略导入历史记录项。"""

    id: int
    url: str
    status: str
    mode: str
    title: str | None = None
    source_type: str | None = None
    guide_id: int | None = None
    source_id: int | None = None
    reason: str | None = None
    message: str | None = None
    quality: dict | None = None
    diagnostics: dict | None = None
    content: str | None = None
    structured: dict | None = None
    category: str | None = None
    resolved_url: str | None = None
    author: str | None = None
    created_at: str | None = None
