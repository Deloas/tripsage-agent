import asyncio
import sys

from app.services.llm_service import LlmService


async def main() -> int:
    """命令行检查 DeepSeek 配置和接口连通性。"""
    result = await LlmService().ping()
    print(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:  # noqa: BLE001
        print(f"DeepSeek 检查失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
