import asyncio
import json
import sys

from app.services.mcp_railway_service import McpRailwayService


async def main() -> int:
    """命令行检查 12306 MCP 配置和安全工具发现状态。"""
    result = await McpRailwayService().ping()
    print(json.dumps(result, ensure_ascii=True, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:  # noqa: BLE001
        print(f"12306 MCP 检查失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
