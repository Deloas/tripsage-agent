from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.core.response import fail, ok
from app.db.session import get_db
from app.schemas.plans import PlanExportRequest, PlanVersionCreate, SharedPlanCreate
from app.services.auth_service import AuthService
from app.services.plan_version_service import PlanVersionService

router = APIRouter()


def _parse_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def _require_user_id(db: Session, authorization: str | None) -> int | None:
    token = _parse_bearer_token(authorization)
    if not token:
        return None
    try:
        return AuthService(db).authenticate_access_token(token).user.id
    except Exception:  # noqa: BLE001
        return None


@router.post("/plan-versions")
def save_plan_version(
    payload: PlanVersionCreate,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """保存当前会话下的方案版本。"""
    user_id = _require_user_id(db, authorization)
    if user_id is None:
        return fail(4011, "当前未登录", {"error": "missing_access_token"})
    try:
        version = PlanVersionService(db).save(payload, user_id=user_id)
        return ok(version.model_dump())
    except Exception as exc:  # noqa: BLE001
        return fail(5010, "方案版本保存失败", {"error": str(exc)})


@router.get("/plan-versions")
def list_plan_versions(
    conversation_id: str = Query(min_length=4, max_length=64),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """读取某个会话下的全部方案版本。"""
    user_id = _require_user_id(db, authorization)
    if user_id is None:
        return fail(4011, "当前未登录", {"error": "missing_access_token"})
    try:
        items = PlanVersionService(db).list_by_conversation(conversation_id, user_id=user_id)
        return ok({"items": [item.model_dump() for item in items], "total": len(items)})
    except Exception as exc:  # noqa: BLE001
        return fail(5010, "方案版本读取失败", {"error": str(exc)})


@router.get("/plan-versions/compare")
def compare_plan_versions(
    base_id: str = Query(min_length=4, max_length=80),
    target_id: str = Query(min_length=4, max_length=80),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """比较两个方案版本的结构化差异。"""
    user_id = _require_user_id(db, authorization)
    if user_id is None:
        return fail(4011, "当前未登录", {"error": "missing_access_token"})
    try:
        result = PlanVersionService(db).compare(base_id, target_id, user_id=user_id)
        return ok(result.model_dump())
    except Exception as exc:  # noqa: BLE001
        return fail(5011, "方案版本对比失败", {"error": str(exc)})


@router.post("/plan-versions/export")
def export_plan_version(
    payload: PlanExportRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """导出方案版本为 Markdown 或 HTML。"""
    user_id = _require_user_id(db, authorization)
    if user_id is None:
        return fail(4011, "当前未登录", {"error": "missing_access_token"})
    try:
        result = PlanVersionService(db).export(payload.version_id, payload.format, user_id=user_id)
        return ok(result.model_dump())
    except Exception as exc:  # noqa: BLE001
        return fail(5012, "方案导出失败", {"error": str(exc)})


@router.post("/shared-plans")
def create_shared_plan(
    payload: SharedPlanCreate,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """创建本地只读分享页。"""
    user_id = _require_user_id(db, authorization)
    if user_id is None:
        return fail(4011, "当前未登录", {"error": "missing_access_token"})
    try:
        result = PlanVersionService(db).create_share(payload.version_id, user_id=user_id)
        return ok(result.model_dump())
    except Exception as exc:  # noqa: BLE001
        return fail(5013, "分享页创建失败", {"error": str(exc)})


@router.get("/shared-plans/{share_id}")
def get_shared_plan(share_id: str, db: Session = Depends(get_db)):
    """读取本地只读分享页。"""
    try:
        result = PlanVersionService(db).get_share(share_id)
        return ok(result.model_dump())
    except Exception as exc:  # noqa: BLE001
        return fail(5014, "分享页读取失败", {"error": str(exc)})
