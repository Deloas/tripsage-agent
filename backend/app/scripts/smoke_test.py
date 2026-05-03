import asyncio
import sys

import httpx


BASE_URL = "http://127.0.0.1:8000/api"


def safe_console_text(value: object) -> str:
    """兼容 Windows 终端编码，避免烟测输出中文时异常。"""

    text = str(value)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, errors="ignore").decode(encoding, errors="ignore")


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
    """后端启动后执行核心接口烟测。"""

    async with httpx.AsyncClient(timeout=45, trust_env=False) as client:
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
                "message": "上海出发，两天一夜，预算 800，想轻松一点，去哪里比较合适？",
                "search_mode": "auto",
                "context": {
                    "home_city": "上海",
                    "persist_session": False,
                },
            },
        )
        print(f"聊天意图：{chat.get('intent')}")
        print(f"回答预览：{safe_console_text(str(chat.get('answer'))[:120])}")

    print("烟测通过。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:  # noqa: BLE001
        print(f"烟测失败：{safe_console_text(exc)}", file=sys.stderr)
        raise SystemExit(1)
