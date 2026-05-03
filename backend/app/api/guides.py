from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.response import fail, ok
from app.db.session import get_db
from app.schemas.guides import GuideCreateRequest, GuideSearchRequest
from app.services.guide_ingest_service import GuideIngestService
from app.services.rag_service import RagService
from app.services.weibo_crawler_service import WeiboCrawlerService

router = APIRouter()


@router.get("/guides")
def list_guides(
    keyword: str | None = Query(default=None),
    city: str | None = Query(default=None),
    category: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    sort_by: str = Query(default="latest", pattern="^(latest|oldest|city_hot|source_priority)$"),
    limit: int = Query(default=30, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """攻略列表接口。"""
    items, total, facets = RagService(db).list_guides(
        city=city,
        category=category,
        source_type=source_type,
        keyword=keyword,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
    )
    return ok(
        {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
            "filters": facets,
            "sort_by": sort_by,
        }
    )


@router.get("/guides/{guide_id}")
def get_guide_detail(guide_id: int, db: Session = Depends(get_db)):
    """攻略详情接口，返回正文、切片和地点抽取结果。"""

    detail = RagService(db).get_guide_detail(guide_id)
    if not detail:
        return fail(4040, "未找到对应攻略", {"guide_id": guide_id})
    return ok(detail)


@router.get("/guides/sources")
def list_guide_sources(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """攻略来源列表接口，可查看微博采集到的待处理入口。"""
    items, total = RagService(db).list_sources(limit=limit, offset=offset, status=status)
    return ok({"items": items, "total": total, "limit": limit, "offset": offset})


@router.post("/guides")
def create_guide(payload: GuideCreateRequest, db: Session = Depends(get_db)):
    """新增攻略并写入知识库。"""
    try:
        result = GuideIngestService(db).add_guide(payload)
        return ok(result)
    except Exception as exc:  # noqa: BLE001
        return fail(5006, "攻略入库失败，请检查内容后重试", {"error": str(exc)})


@router.post("/guides/search")
def search_guides(payload: GuideSearchRequest, db: Session = Depends(get_db)):
    """攻略检索接口，供前端知识库页和智能体调试使用。"""
    items = RagService(db).search(payload.query, payload.city, payload.top_k)
    return ok({"items": [item.model_dump() for item in items], "total": len(items)})


@router.post("/guides/crawl/weibo")
async def crawl_weibo_guides(db: Session = Depends(get_db)):
    """采集微博公开攻略入口；不登录、不绕过风控，只保存公开可见链接。"""
    try:
        result = await WeiboCrawlerService(db).crawl_index()
        return ok(result)
    except Exception as exc:  # noqa: BLE001
        return fail(5006, "微博攻略采集失败，请稍后重试或手动添加攻略", {"error": str(exc)})
