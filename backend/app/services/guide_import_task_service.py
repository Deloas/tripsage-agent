import json
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import GuideImportTask, utc_now
from app.db.session import SessionLocal
from app.schemas.guides import GuideLinkImportRequest
from app.services.guide_link_import_service import GuideLinkImportService


class GuideImportTaskService:
    """攻略导入异步任务服务，避免长图 OCR 和浏览器抓取阻塞前端请求。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_preview_task(self, payload: GuideLinkImportRequest) -> dict[str, Any]:
        """创建一个可轮询的链接预览任务。"""
        task = GuideImportTask(
            id=f"guide-import-{uuid4().hex[:16]}",
            url=payload.url,
            category=payload.category,
            force_reimport=payload.force_reimport,
            mode="preview",
            status="queued",
            stage="queued",
            progress=5,
            message="任务已创建，等待后台抓取。",
        )
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return self._task_to_dict(task)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """查询单个导入任务。"""
        task = self.db.get(GuideImportTask, task_id)
        return self._task_to_dict(task) if task else None

    def list_tasks(self, limit: int = 30, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        """返回最近导入任务，供前端任务中心展示。"""
        total = self.db.execute(select(func.count()).select_from(GuideImportTask)).scalar_one()
        tasks = (
            self.db.execute(
                select(GuideImportTask)
                .order_by(GuideImportTask.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return [self._task_to_dict(task) for task in tasks], int(total or 0)

    def mark_running(self, task_id: str, *, stage: str, progress: int, message: str) -> None:
        """更新任务进度。"""
        self._update_task(task_id, status="running", stage=stage, progress=progress, message=message)

    def mark_succeeded(self, task_id: str, result: dict[str, Any]) -> None:
        """把后台抓取结果写回任务。"""
        self._update_task(
            task_id,
            status="succeeded",
            stage="done",
            progress=100,
            title=str(result.get("title") or "")[:200] or None,
            message=str(result.get("message") or "任务已完成，可编辑预览。")[:1000],
            result_json=json.dumps(result, ensure_ascii=False),
            error_message=None,
            finished_at=utc_now(),
        )

    def mark_failed(self, task_id: str, error: Exception) -> None:
        """记录失败原因，前端可据此展示重试入口。"""
        self._update_task(
            task_id,
            status="failed",
            stage="failed",
            progress=100,
            message="任务失败，请稍后重试或改用手动补录。",
            error_message=str(error)[:2000],
            finished_at=utc_now(),
        )

    def _update_task(self, task_id: str, **fields: Any) -> None:
        task = self.db.get(GuideImportTask, task_id)
        if not task:
            return
        for key, value in fields.items():
            setattr(task, key, value)
        task.updated_at = utc_now()
        self.db.commit()

    def _task_to_dict(self, task: GuideImportTask) -> dict[str, Any]:
        return {
            "id": task.id,
            "url": task.url,
            "category": task.category,
            "force_reimport": bool(task.force_reimport),
            "mode": task.mode,
            "status": task.status,
            "stage": task.stage,
            "progress": task.progress,
            "title": task.title,
            "message": task.message,
            "result": self._loads_json(task.result_json),
            "error_message": task.error_message,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        }

    def _loads_json(self, value: str | None) -> Any:
        if not value:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None


async def run_guide_import_preview_task(task_id: str, payload_data: dict[str, Any]) -> None:
    """FastAPI BackgroundTasks 入口：使用独立数据库会话执行长耗时导入。"""
    db = SessionLocal()
    task_service = GuideImportTaskService(db)
    try:
        payload = GuideLinkImportRequest(**payload_data)
        task_service.mark_running(task_id, stage="fetching", progress=18, message="正在打开链接并抓取公开正文。")
        task_service.mark_running(task_id, stage="extracting", progress=38, message="正在解析页面、图片与可见文本。")
        result = await GuideLinkImportService(db).preview_link(payload)
        task_service.mark_running(task_id, stage="finalizing", progress=88, message="正在生成结构化预览和诊断信息。")
        task_service.mark_succeeded(task_id, result)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        task_service.mark_failed(task_id, exc)
    finally:
        db.close()
