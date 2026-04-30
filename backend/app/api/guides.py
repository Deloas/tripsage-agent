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
def list_guides(city: str | None = Query(default=None), db: Session = Depends(get_db)):
    """攻略列表接口。"""
    items = RagService(db).list_guides(city=city)
    return ok({"items": items, "total": len(items)})


@router.get("/guides/sources")
def list_guide_sources(
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """攻略来源列表接口，可查看微博采集到的待处理入口。"""
    items = RagService(db).list_sources(status=status)
    return ok({"items": items, "total": len(items)})


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
