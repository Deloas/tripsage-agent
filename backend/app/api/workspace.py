from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.orm import Session

from app.core.response import fail, ok
from app.db.session import get_db
from app.schemas.workspace import (
    AuthLogoutRequest,
    AuthRefreshRequest,
    ConversationUpdateRequest,
    GuestSessionImportRequest,
    PreferenceBehaviorEventRequest,
    PreferenceFeedbackRequest,
    PreferenceTimelineUndoRequest,
    UserCreateRequest,
    UserLoginRequest,
    UserProfileUpdateRequest,
)
from app.services.auth_service import AuthContext, AuthService
from app.services.conversation_service import ConversationService
from app.services.preference_service import PreferenceService
from app.services.user_service import UserService

router = APIRouter()


def _empty_profile_layer_payload() -> dict:
    """构造空画像层，保证游客模式也返回稳定结构。"""

    return {
        "preferred_cities": [],
        "budget_range": None,
        "transport_modes": [],
        "pace_tags": [],
        "interest_tags": [],
        "negative_preferences": [],
        "explicit_preferences": [],
        "inferred_preferences": [],
        "behavior_signals": [],
        "profile_strength": "new",
        "budget_profile": None,
        "recent_evidence": [],
        "recommendation_hint": "",
        "updated_at": None,
    }


def _parse_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def _resolve_auth_context(db: Session, authorization: str | None) -> AuthContext | None:
    token = _parse_bearer_token(authorization)
    if not token:
        return None
    try:
        return AuthService(db).authenticate_access_token(token)
    except Exception:  # noqa: BLE001
        return None


def _guest_profile_payload() -> dict:
    layer = _empty_profile_layer_payload()
    return {
        **layer,
        "recommendation_hint": "游客模式不会保存偏好画像，登录后系统才会自动沉淀你的旅行偏好。",
        "long_term_profile": layer,
        "session_profile": {
            **layer,
            "recommendation_hint": "当前还没有可沉淀的本次偏好。",
        },
        "blacklist_items": [],
        "locked_items": [],
    }


def _empty_preference_audit_payload() -> dict:
    """返回游客模式或空状态下稳定的审计结构。"""

    return {
        "summary": {
            "total_events": 0,
            "explicit_total": 0,
            "inferred_total": 0,
            "behavior_total": 0,
            "session_total": 0,
            "long_term_total": 0,
            "locked_total": 0,
            "blacklist_total": 0,
        },
        "by_dimension": [],
        "by_source": [],
        "by_scope": [],
    }


@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    """读取本地用户列表。"""
    items = UserService(db).list_users()
    return ok({"items": [item.model_dump() for item in items], "total": len(items)})


@router.post("/users")
def create_user(payload: UserCreateRequest, db: Session = Depends(get_db)):
    """创建本地用户。"""
    user = UserService(db).create_user(payload)
    return ok(user.model_dump())


@router.post("/auth/register")
def register_user(
    payload: UserCreateRequest,
    request: Request,
    x_client_name: str | None = Header(default=None, alias="X-Client-Name"),
    db: Session = Depends(get_db),
):
    """注册并直接创建登录会话。"""
    try:
        result = UserService(db).register(
            payload,
            client_name=x_client_name,
            user_agent=request.headers.get("user-agent"),
        )
        return ok(result.model_dump())
    except Exception as exc:  # noqa: BLE001
        return fail(4015, "注册失败", {"error": str(exc)})


@router.post("/auth/login")
def login_user(
    payload: UserLoginRequest,
    request: Request,
    x_client_name: str | None = Header(default=None, alias="X-Client-Name"),
    db: Session = Depends(get_db),
):
    """本地账号登录，返回正式访问令牌与刷新令牌。"""
    try:
        result = UserService(db).login(
            payload,
            client_name=x_client_name,
            user_agent=request.headers.get("user-agent"),
        )
        return ok(result.model_dump())
    except Exception as exc:  # noqa: BLE001
        return fail(4010, "登录失败", {"error": str(exc)})


@router.post("/auth/refresh")
def refresh_auth(
    payload: AuthRefreshRequest,
    request: Request,
    x_client_name: str | None = Header(default=None, alias="X-Client-Name"),
    db: Session = Depends(get_db),
):
    """刷新访问令牌。"""
    try:
        result = AuthService(db).refresh_session(
            payload.refresh_token,
            client_name=x_client_name,
            user_agent=request.headers.get("user-agent"),
        )
        return ok(result.model_dump())
    except Exception as exc:  # noqa: BLE001
        return fail(4012, "刷新登录态失败", {"error": str(exc)})


@router.post("/auth/logout")
def logout_auth(payload: AuthLogoutRequest, db: Session = Depends(get_db)):
    """退出当前登录会话。"""
    try:
        AuthService(db).revoke_session(payload.refresh_token)
        return ok({"success": True})
    except Exception as exc:  # noqa: BLE001
        return fail(4013, "退出登录失败", {"error": str(exc)})


@router.get("/auth/me")
def get_auth_me(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """读取当前登录态。"""
    token = _parse_bearer_token(authorization)
    if not token:
        return fail(4011, "当前未登录", {"error": "missing_access_token"})
    try:
        state = AuthService(db).get_auth_state(token)
        return ok(state.model_dump())
    except Exception as exc:  # noqa: BLE001
        return fail(4011, "当前登录态已失效", {"error": str(exc)})


@router.patch("/users/me")
def update_me(
    payload: UserProfileUpdateRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """更新当前登录用户资料。"""
    auth = _resolve_auth_context(db, authorization)
    if auth is None:
        return fail(4011, "当前未登录", {"error": "missing_access_token"})
    try:
        user = UserService(db).update_profile(auth.user.id, payload)
        return ok(user.model_dump())
    except Exception as exc:  # noqa: BLE001
        return fail(4014, "更新用户资料失败", {"error": str(exc)})


@router.get("/auth/sessions")
def list_auth_sessions(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """列出当前用户的登录会话。"""
    auth = _resolve_auth_context(db, authorization)
    if auth is None:
        return fail(4011, "当前未登录", {"error": "missing_access_token"})
    items = AuthService(db).list_sessions(auth.user.id, current_session_id=auth.session.id)
    return ok({"items": [item.model_dump() for item in items], "total": len(items)})


@router.delete("/auth/sessions/{session_id}")
def revoke_auth_session(
    session_id: str,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """注销指定的其他登录会话。"""
    auth = _resolve_auth_context(db, authorization)
    if auth is None:
        return fail(4011, "当前未登录", {"error": "missing_access_token"})
    try:
        AuthService(db).revoke_session_by_id(
            auth.user.id,
            session_id,
            current_session_id=auth.session.id,
        )
        return ok({"success": True, "session_id": session_id})
    except Exception as exc:  # noqa: BLE001
        return fail(4016, "注销会话失败", {"error": str(exc)})


@router.get("/conversations")
def list_conversations(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """读取当前登录用户的历史会话。"""
    auth = _resolve_auth_context(db, authorization)
    if auth is None:
        return ok({"items": [], "total": 0})
    items = ConversationService(db).list_conversations(user_id=auth.user.id)
    return ok({"items": [item.model_dump() for item in items], "total": len(items)})


@router.post("/conversations/import-guest-session")
def import_guest_session(
    payload: GuestSessionImportRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """把游客临时方案导入当前登录账号。"""
    auth = _resolve_auth_context(db, authorization)
    if auth is None:
        return fail(4011, "当前未登录", {"error": "missing_access_token"})
    try:
        normalized_payload = payload.model_copy(update={"user_id": auth.user.id})
        result = ConversationService(db).import_guest_session(normalized_payload)
        return ok(result.model_dump())
    except Exception as exc:  # noqa: BLE001
        return fail(5018, "游客会话导入失败", {"error": str(exc)})


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """读取历史会话详情。"""
    auth = _resolve_auth_context(db, authorization)
    if auth is None:
        return fail(5015, "游客模式下没有可恢复的历史会话", {"error": "guest_has_no_history"})
    try:
        detail = ConversationService(db).get_conversation(conversation_id, user_id=auth.user.id)
        return ok(detail.model_dump())
    except Exception as exc:  # noqa: BLE001
        return fail(5015, "历史会话读取失败", {"error": str(exc)})


@router.patch("/conversations/{conversation_id}")
def update_conversation(
    conversation_id: str,
    payload: ConversationUpdateRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """更新历史会话元数据。"""
    auth = _resolve_auth_context(db, authorization)
    if auth is None:
        return fail(5016, "游客模式下无法编辑历史会话", {"error": "guest_has_no_history"})
    try:
        item = ConversationService(db).update_conversation(conversation_id, payload, user_id=auth.user.id)
        return ok(item.model_dump())
    except Exception as exc:  # noqa: BLE001
        return fail(5016, "历史会话更新失败", {"error": str(exc)})


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """删除历史会话及其关联数据。"""
    auth = _resolve_auth_context(db, authorization)
    if auth is None:
        return fail(5017, "游客模式下没有可删除的历史会话", {"error": "guest_has_no_history"})
    try:
        result = ConversationService(db).delete_conversation(conversation_id, user_id=auth.user.id)
        return ok(result)
    except Exception as exc:  # noqa: BLE001
        return fail(5017, "历史会话删除失败", {"error": str(exc)})


@router.get("/preference-profile")
def get_preference_profile(
    conversation_id: str | None = Query(default=None, max_length=64),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """读取当前用户的旅行偏好画像。"""
    auth = _resolve_auth_context(db, authorization)
    if auth is None:
        return ok(_guest_profile_payload())
    profile = PreferenceService(db, user_key=str(auth.user.id)).get_profile(conversation_id=conversation_id)
    return ok(profile.model_dump())


@router.get("/preference-profile/timeline")
def get_preference_profile_timeline(
    conversation_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=40, ge=1, le=80),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """读取当前用户的画像时间线。"""

    auth = _resolve_auth_context(db, authorization)
    if auth is None:
        return ok({"items": [], "total": 0})
    effective_limit = limit if isinstance(limit, int) else 40
    timeline = PreferenceService(db, user_key=str(auth.user.id)).list_timeline(
        conversation_id=conversation_id,
        limit=effective_limit,
    )
    return ok(timeline.model_dump())


@router.get("/preference-profile/audit")
def get_preference_profile_audit(
    conversation_id: str | None = Query(default=None, max_length=64),
    limit_per_group: int = Query(default=12, ge=1, le=24),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """读取当前用户的画像审计结果。"""

    auth = _resolve_auth_context(db, authorization)
    if auth is None:
        return ok(_empty_preference_audit_payload())
    audit = PreferenceService(db, user_key=str(auth.user.id)).list_audit(
        conversation_id=conversation_id,
        limit_per_group=limit_per_group,
    )
    return ok(audit.model_dump())


@router.post("/preference-profile/feedback")
def submit_preference_feedback(
    payload: PreferenceFeedbackRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """接收用户对画像判断的人工校正，并立即回写最新画像。"""
    auth = _resolve_auth_context(db, authorization)
    if auth is None:
        return fail(5019, "游客模式下无法保存偏好画像纠正", {"error": "guest_has_no_profile_feedback"})
    try:
        profile = PreferenceService(db, user_key=str(auth.user.id)).apply_manual_feedback(
            dimension=payload.dimension,
            value=payload.value,
            action=payload.action,
            polarity=payload.polarity,
            conversation_id=payload.conversation_id,
        )
        return ok(profile.model_dump())
    except Exception as exc:  # noqa: BLE001
        return fail(5020, "偏好画像纠正失败", {"error": str(exc)})


@router.post("/preference-profile/timeline/undo")
def undo_preference_timeline_event(
    payload: PreferenceTimelineUndoRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """撤销画像时间线中的可逆动作。"""

    auth = _resolve_auth_context(db, authorization)
    if auth is None:
        return fail(5019, "游客模式下无法撤销画像动作", {"error": "guest_has_no_profile_feedback"})
    try:
        result = PreferenceService(db, user_key=str(auth.user.id)).undo_timeline_event(
            event_id=payload.event_id,
            conversation_id=payload.conversation_id,
        )
        return ok(result.model_dump())
    except Exception as exc:  # noqa: BLE001
        return fail(5022, "画像时间线撤销失败", {"error": str(exc)})


@router.post("/preference-profile/events")
def submit_preference_behavior_event(
    payload: PreferenceBehaviorEventRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """接收前端关键行为埋点，并即时回写最新画像。"""

    auth = _resolve_auth_context(db, authorization)
    if auth is None:
        return fail(5019, "游客模式下无法保存偏好画像行为事件", {"error": "guest_has_no_profile_feedback"})
    try:
        profile = PreferenceService(db, user_key=str(auth.user.id)).record_workspace_event(
            action=payload.action,
            conversation_id=payload.conversation_id,
            payload=payload.payload,
        )
        return ok(profile.model_dump())
    except Exception as exc:  # noqa: BLE001
        return fail(5021, "偏好画像行为事件写入失败", {"error": str(exc)})
