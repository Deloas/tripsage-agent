import json
import time
from collections.abc import Callable
from typing import Any, TypeVar

from sqlalchemy.orm import Session

from app.db.models import ToolCall


T = TypeVar("T")


class ToolLogger:
    """记录智能体工具调用，方便前端展示和答辩解释。"""

    def __init__(
        self,
        db: Session,
        conversation_id: str | None = None,
        enabled: bool = True,
        memory_buffer: list[dict] | None = None,
    ) -> None:
        self.db = db
        self.conversation_id = conversation_id
        self.enabled = enabled
        self.memory_buffer = memory_buffer if memory_buffer is not None else []

    def record(
        self,
        tool_name: str,
        input_data: dict,
        output_summary: str,
        status: str,
        latency_ms: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """写入工具调用日志；输入输出均使用中文可读摘要。"""
        summary = {
            "tool_name": tool_name,
            "status": status,
            "latency_ms": latency_ms,
            "output_summary": output_summary,
        }
        self.memory_buffer.append(summary)
        if not self.enabled:
            return
        self.db.add(
            ToolCall(
                conversation_id=self.conversation_id,
                tool_name=tool_name,
                input_json=json.dumps(input_data, ensure_ascii=False),
                output_summary=output_summary,
                status=status,
                latency_ms=latency_ms,
                error_message=error_message,
            )
        )
        self.db.commit()

    async def measure_async(
        self,
        tool_name: str,
        input_data: dict,
        func: Callable[[], Any],
        summary_getter: Callable[[Any], str],
    ) -> Any:
        """包装异步工具调用，自动计算耗时并记录结果。"""
        start = time.perf_counter()
        try:
            result = await func()
            latency = int((time.perf_counter() - start) * 1000)
            status = "fallback" if isinstance(result, dict) and result.get("fallback") else "success"
            self.record(tool_name, input_data, summary_getter(result), status, latency)
            return result
        except Exception as exc:  # noqa: BLE001
            latency = int((time.perf_counter() - start) * 1000)
            self.record(tool_name, input_data, "工具调用失败", "failed", latency, str(exc))
            raise
