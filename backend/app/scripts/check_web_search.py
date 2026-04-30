import asyncio
import json
import sys

from app.services.web_search_service import WebSearchService


async def main() -> int:
    """命令行检查联网搜索配置、网络连通性和结果解析状态。"""
    result = await WebSearchService().ping()
    print(json.dumps(result, ensure_ascii=True, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:  # noqa: BLE001
        print(f"联网搜索检查失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
