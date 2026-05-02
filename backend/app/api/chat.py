import json

from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.agents.graph import TripAgent
from app.core.response import fail, ok
from app.db.session import get_db
from app.schemas.chat import ChatRequest
from app.services.auth_service import AuthService

router = APIRouter()


class AuthRequiredError(Exception):
    """需要正式登录态才能继续的错误。"""


def _parse_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def _coerce_persist_flag(value: object) -> bool | None:
    """兼容字符串布尔值，避免游客模式被误判为持久化会话。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _normalize_request_context(db: Session, payload: ChatRequest, authorization: str | None) -> ChatRequest:
    """用后端鉴权结果重写聊天上下文，避免前端伪造 user_id。"""
    context = dict(payload.context or {})
    token = _parse_bearer_token(authorization)
    requested_persist = _coerce_persist_flag(context.get("persist_session"))

    # 未显式声明时，登录用户默认持久化，游客默认临时会话。
    if requested_persist is None:
        requested_persist = bool(token)

    if token and requested_persist:
        try:
            auth = AuthService(db).authenticate_access_token(token)
            context["persist_session"] = True
            context["user_id"] = auth.user.id
            return payload.model_copy(update={"context": context})
        except Exception as exc:  # noqa: BLE001
            raise AuthRequiredError("当前登录态已失效，请刷新后重试") from exc

    if requested_persist:
        raise AuthRequiredError("当前未登录，无法保存会话")

    context["persist_session"] = False
    context.pop("user_id", None)
    return payload.model_copy(update={"context": context})


@router.post("/chat")
async def chat(
    payload: ChatRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """智能体聊天入口。"""
    try:
        normalized_payload = _normalize_request_context(db, payload, authorization)
        result = await TripAgent(db).run(normalized_payload)
        return ok(result.model_dump())
    except AuthRequiredError as exc:
        return fail(4011, "当前登录态已失效", {"error": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return fail(5001, "智能体处理失败，请稍后重试或开启演示模式", {"error": str(exc)})


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """智能体流式入口，使用 SSE 推送阶段进度和最终结果。"""
    try:
        normalized_payload = _normalize_request_context(db, payload, authorization)

        async def event_stream():
            try:
                async for event_name, data in TripAgent(db).run_steps(normalized_payload):
                    yield f"event: {event_name}\n"
                    yield f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
            except Exception as exc:  # noqa: BLE001
                yield "event: error\n"
                yield f"data: {json.dumps({'message': '智能体流式处理失败', 'error': str(exc)}, ensure_ascii=False)}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")
    except AuthRequiredError as exc:
        return fail(4011, "当前登录态已失效", {"error": str(exc)})
