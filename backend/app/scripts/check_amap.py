import asyncio
import sys

from app.services.amap_service import AmapService


async def main() -> int:
    """命令行检查高德天气、地理编码和地图接口配置。"""
    result = await AmapService().ping()
    print(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:  # noqa: BLE001
        print(f"高德检查失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
