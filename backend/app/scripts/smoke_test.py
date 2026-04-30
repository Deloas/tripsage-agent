import asyncio
import sys

import httpx


BASE_URL = "http://127.0.0.1:8000/api"


async def check_get(client: httpx.AsyncClient, path: str) -> dict:
    """检查 GET 接口是否返回统一成功结构。"""
    response = await client.get(f"{BASE_URL}{path}")
    response.raise_for_status()
    data = response.json()
    if data.get("code") != 0:
        raise RuntimeError(f"{path} 返回失败：{data}")
    return data["data"]


async def check_post(client: httpx.AsyncClient, path: str, payload: dict) -> dict:
    """检查 POST 接口是否返回统一成功结构。"""
    response = await client.post(f"{BASE_URL}{path}", json=payload)
    response.raise_for_status()
    data = response.json()
    if data.get("code") != 0:
        raise RuntimeError(f"{path} 返回失败：{data}")
    return data["data"]


async def main() -> int:
    """服务启动后的冒烟测试，验证核心接口是否可用。"""
    async with httpx.AsyncClient(timeout=30) as client:
        health = await check_get(client, "/health")
        print(f"健康检查：{health}")

        tools = await check_get(client, "/tools/status")
        print(f"工具状态：{tools}")

        diagnostics = await check_get(client, "/diagnostics")
        print(f"诊断状态：{diagnostics}")

        guides = await check_get(client, "/guides")
        print(f"攻略数量：{guides.get('total')}")

        chat = await check_post(
            client,
            "/chat",
            {
                "message": "上海出发，两天一夜，预算800，想轻松一点，去哪比较好？",
                "search_mode": "auto",
                "context": {"home_city": "上海"},
            },
        )
        print(f"聊天意图：{chat.get('intent')}")
        print(f"回答预览：{str(chat.get('answer'))[:120]}")

    print("冒烟测试通过。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:  # noqa: BLE001
        print(f"冒烟测试失败：{exc}", file=sys.stderr)
        raise SystemExit(1)

