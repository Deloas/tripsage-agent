from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.core.response import fail, ok
from app.db.session import get_db
from app.schemas.guides import (
    GuideCreateRequest,
    GuideLinkImportConfirmRequest,
    GuideLinkImportRequest,
    GuideSearchRequest,
    GuideUpdateRequest,
)
from app.services.guide_ingest_service import GuideIngestService
from app.services.guide_import_task_service import GuideImportTaskService, run_guide_import_preview_task
from app.services.guide_link_import_service import GuideLinkImportService
from app.services.guide_mobility_service import GuideMobilityService
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
    """攻略列表接口，支持关键词、城市、分类、来源和排序筛选。"""
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


@router.get("/guides/sources")
def list_guide_sources(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """攻略来源列表接口，用于查看已入库、待处理或异常来源。"""
    items, total = RagService(db).list_sources(limit=limit, offset=offset, status=status)
    return ok({"items": items, "total": total, "limit": limit, "offset": offset})


@router.get("/guides/import-records")
def list_guide_import_records(
    limit: int = Query(default=30, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """攻略导入结果历史中心。"""
    items, total = GuideLinkImportService(db).list_import_records(limit=limit, offset=offset)
    return ok({"items": items, "total": total, "limit": limit, "offset": offset})


@router.get("/guides/import-records/{record_id}")
def get_guide_import_record(record_id: int, db: Session = Depends(get_db)):
    """中文注释：返回单条导入记录的完整详情，避免前端只能依赖列表快照。"""
    item = GuideLinkImportService(db).get_import_record(record_id)
    if not item:
        return fail(4040, "未找到对应的导入记录", {"record_id": record_id})
    return ok(item)


@router.delete("/guides/import-records/{record_id}")
def delete_guide_import_record(record_id: int, db: Session = Depends(get_db)):
    """删除单条攻略导入记录；不删除已入库攻略，避免误伤知识库内容。"""
    deleted = GuideLinkImportService(db).delete_import_record(record_id)
    if not deleted:
        return fail(4040, "未找到对应的导入记录", {"record_id": record_id})
    return ok(deleted)


@router.post("/guides")
def create_guide(payload: GuideCreateRequest, db: Session = Depends(get_db)):
    """新增攻略并写入知识库。"""
    try:
        result = GuideIngestService(db).add_guide(payload)
        return ok(result)
    except Exception as exc:  # noqa: BLE001
        return fail(5006, "攻略入库失败，请检查内容后重试", {"error": str(exc)})


@router.post("/guides/import-link")
async def import_guide_link(payload: GuideLinkImportRequest, db: Session = Depends(get_db)):
    """直接导入公开攻略链接。"""
    try:
        result = await GuideLinkImportService(db).import_link(payload)
        return ok(result)
    except Exception as exc:  # noqa: BLE001
        return fail(5006, "攻略链接导入失败，请检查链接后重试", {"error": str(exc)})


@router.post("/guides/import-link/preview")
async def preview_guide_link(payload: GuideLinkImportRequest, db: Session = Depends(get_db)):
    """抓取攻略链接并返回可编辑预览。"""
    try:
        result = await GuideLinkImportService(db).preview_link(payload)
        return ok(result)
    except Exception as exc:  # noqa: BLE001
        return fail(5006, "攻略链接预览失败，请检查链接后重试", {"error": str(exc)})


@router.post("/guides/import-link/tasks")
async def create_guide_import_task(
    payload: GuideLinkImportRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """创建后台导入预览任务，用于长图 OCR、微博渲染等长耗时场景。"""
    try:
        task = GuideImportTaskService(db).create_preview_task(payload)
        background_tasks.add_task(run_guide_import_preview_task, task["id"], payload.model_dump())
        return ok(task)
    except Exception as exc:  # noqa: BLE001
        return fail(5006, "攻略导入任务创建失败，请稍后重试", {"error": str(exc)})


@router.get("/guides/import-link/tasks")
def list_guide_import_tasks(
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """攻略导入任务中心，返回最近后台抓取任务。"""
    items, total = GuideImportTaskService(db).list_tasks(limit=limit, offset=offset)
    return ok({"items": items, "total": total, "limit": limit, "offset": offset})


@router.get("/guides/import-link/tasks/{task_id}")
def get_guide_import_task(task_id: str, db: Session = Depends(get_db)):
    """查询单个攻略导入任务状态。"""
    task = GuideImportTaskService(db).get_task(task_id)
    if not task:
        return fail(4040, "未找到对应的攻略导入任务", {"task_id": task_id})
    return ok(task)


@router.post("/guides/import-link/confirm")
async def confirm_guide_link(payload: GuideLinkImportConfirmRequest, db: Session = Depends(get_db)):
    """确认用户编辑后的导入攻略并写入知识库。"""
    try:
        result = await GuideLinkImportService(db).confirm_import(payload)
        return ok(result)
    except Exception as exc:  # noqa: BLE001
        return fail(5006, "攻略确认入库失败，请检查正文后重试", {"error": str(exc)})


@router.post("/guides/search")
def search_guides(payload: GuideSearchRequest, db: Session = Depends(get_db)):
    """攻略检索接口，供知识库页面和智能体调试使用。"""
    items = RagService(db).search(payload.query, payload.city, payload.top_k)
    return ok({"items": [item.model_dump() for item in items], "total": len(items)})


@router.post("/guides/crawl/weibo")
async def crawl_weibo_guides(db: Session = Depends(get_db)):
    """采集微博公开攻略入口；只保存公开可见链接和正文。"""
    try:
        result = await WeiboCrawlerService(db).crawl_index()
        return ok(result)
    except Exception as exc:  # noqa: BLE001
        return fail(5006, "微博攻略采集失败，请稍后重试或手动添加攻略", {"error": str(exc)})


@router.get("/guides/{guide_id}")
def get_guide_detail(guide_id: int, db: Session = Depends(get_db)):
    """攻略详情接口，返回正文、切片和地点抽取结果。"""
    detail = RagService(db).get_guide_detail(guide_id)
    if not detail:
        return fail(4040, "未找到对应攻略", {"guide_id": guide_id})
    return ok(detail)


@router.get("/guides/{guide_id}/mobility/route-preview")
async def get_guide_route_preview(
    guide_id: int,
    mode: str = Query(default="driving", pattern="^(driving|walking|transit|walk)$"),
    db: Session = Depends(get_db),
):
    """把攻略详情中的地点抽取结果转成地图路线预览。"""
    try:
        result = await GuideMobilityService(db).build_route_preview(guide_id, mode=mode)
    except Exception as exc:  # noqa: BLE001
        return fail(5003, "攻略地图路线预览生成失败", {"error": str(exc), "guide_id": guide_id})
    if not result:
        return fail(4040, "未找到对应攻略", {"guide_id": guide_id})
    return ok(result)


@router.put("/guides/{guide_id}")
def update_guide(guide_id: int, payload: GuideUpdateRequest, db: Session = Depends(get_db)):
    """更新已入库攻略，并重新生成结构化信息、切片和向量索引。"""
    try:
        result = GuideIngestService(db).update_guide(guide_id, payload)
        if not result:
            return fail(4040, "未找到对应攻略", {"guide_id": guide_id})
        detail = RagService(db).get_guide_detail(guide_id)
        return ok({"result": result, "guide": detail})
    except Exception as exc:  # noqa: BLE001
        return fail(5006, "攻略更新失败，请检查正文和结构化信息后重试", {"error": str(exc)})
