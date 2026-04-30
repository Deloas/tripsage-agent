from typing import Any
from uuid import uuid4

from fastapi.responses import JSONResponse


def new_trace_id() -> str:
    """生成一次请求链路追踪 ID，便于前端反馈和后端排查。"""
    return uuid4().hex[:16]


def ok(data: Any = None, message: str = "ok", trace_id: str | None = None) -> JSONResponse:
    """统一成功响应格式。"""
    return JSONResponse(
        {
            "code": 0,
            "message": message,
            "data": data if data is not None else {},
            "trace_id": trace_id or new_trace_id(),
        }
    )


def fail(code: int, message: str, data: Any = None, trace_id: str | None = None) -> JSONResponse:
    """统一失败响应格式，避免把异常堆栈直接暴露给前端。"""
    return JSONResponse(
        status_code=200,
        content={
            "code": code,
            "message": message,
            "data": data if data is not None else {},
            "trace_id": trace_id or new_trace_id(),
        },
    )

