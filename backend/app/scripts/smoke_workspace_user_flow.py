import asyncio
import sys
from datetime import UTC, datetime
from uuid import uuid4

import httpx


BASE_URL = "http://127.0.0.1:8000/api"


def safe_console_text(value: object) -> str:
    """兼容 Windows 终端编码，避免输出中文时报错。"""

    text = str(value)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, errors="ignore").decode(encoding, errors="ignore")


def auth_header(token: str) -> dict[str, str]:
    """生成统一的登录态请求头。"""

    return {"Authorization": f"Bearer {token}"}


async def check_get(client: httpx.AsyncClient, path: str, headers: dict | None = None, params: dict | None = None) -> dict:
    """检查 GET 接口是否返回统一成功结构。"""

    response = await client.get(f"{BASE_URL}{path}", headers=headers, params=params)
    response.raise_for_status()
    data = response.json()
    if data.get("code") != 0:
        raise RuntimeError(f"{path} 返回失败：{data}")
    return data["data"]


async def check_post(
    client: httpx.AsyncClient,
    path: str,
    payload: dict,
    headers: dict | None = None,
) -> dict:
    """检查 POST 接口是否返回统一成功结构。"""

    response = await client.post(f"{BASE_URL}{path}", json=payload, headers=headers)
    response.raise_for_status()
    data = response.json()
    if data.get("code") != 0:
        raise RuntimeError(f"{path} 返回失败：{data}")
    return data["data"]


async def main() -> int:
    """面向真实本地服务的登录态画像与历史中心烟测。"""

    unique = uuid4().hex[:8]
    username = f"smoke_{unique}"
    password = "secret123"

    async with httpx.AsyncClient(timeout=45, trust_env=False) as client:
        register = await check_post(
            client,
            "/auth/register",
            {
                "display_name": "烟测用户",
                "username": username,
                "password": password,
                "home_city": "上海",
                "travel_style": "轻松慢游",
            },
            headers={"X-Client-Name": "smoke-script"},
        )
        access_token = register["access_token"]
        refresh_token = register["refresh_token"]
        headers = auth_header(access_token)
        print(f"[1/10] 注册成功：{safe_console_text(register['user']['username'])}")

        me = await check_get(client, "/auth/me", headers=headers)
        print(f"[2/10] 当前用户：{safe_console_text(me['user']['display_name'])}")

        profile = await check_post(
            client,
            "/preference-profile/feedback",
            {
                "dimension": "transport",
                "value": "高铁",
                "action": "set_common",
                "conversation_id": "smoke-conv-001",
            },
            headers=headers,
        )
        print(f"[3/10] 长期偏好已写入：{safe_console_text(profile['long_term_profile']['transport_modes'])}")

        profile = await check_post(
            client,
            "/preference-profile/feedback",
            {
                "dimension": "transport",
                "value": "高铁",
                "action": "lock_long_term",
                "conversation_id": "smoke-conv-001",
            },
            headers=headers,
        )
        print(f"[4/10] 锁定项数量：{len(profile['locked_items'])}")

        profile = await check_post(
            client,
            "/preference-profile/events",
            {
                "action": "favorite_on",
                "conversation_id": "smoke-conv-001",
                "payload": {
                    "title": "南京周末高铁慢游",
                    "destination_city": "南京",
                    "budget": 1800,
                    "tags": ["周末", "高铁出行", "美食"],
                    "summary": "高铁优先，轻松节奏，适合周末慢游。",
                },
            },
            headers=headers,
        )
        print(f"[5/10] 行为画像已更新：{safe_console_text(profile['behavior_signals'][:2])}")

        imported = await check_post(
            client,
            "/conversations/import-guest-session",
            {
                "user_id": 1,
                "title": "南京两天一夜",
                "messages": [
                    {"role": "user", "content": "我想从上海去南京玩两天一夜。"},
                    {"role": "assistant", "content": "建议优先高铁，并预留雨天备选。"},
                ],
                "plan_versions": [
                    {
                        "id": "smoke-version-001",
                        "name": "初版方案",
                        "reason": "烟测导入",
                        "created_at": datetime.now(UTC).isoformat(),
                        "response": {
                            "answer": "建议周末出发，安排博物馆和美食街。",
                            "cards": [{"type": "destination", "title": "南京"}],
                        },
                    }
                ],
                "active_version_id": "smoke-version-001",
                "latest_response": {
                    "answer": "建议周末出发，安排博物馆和美食街。",
                    "cards": [{"type": "destination", "title": "南京"}],
                },
                "destination_city": "南京",
                "budget": 1800,
                "start_date": "周末",
                "tags": ["周末", "美食"],
            },
            headers=headers,
        )
        print(f"[6/10] 游客会话导入成功：{safe_console_text(imported['conversation_id'])}")

        conversations = await check_get(client, "/conversations", headers=headers)
        print(f"[7/10] 历史会话数量：{conversations['total']}")

        audit = await check_get(
            client,
            "/preference-profile/audit",
            headers=headers,
            params={"conversation_id": "smoke-conv-001", "limit_per_group": 10},
        )
        print(f"[8/10] 审计摘要：{safe_console_text(audit['summary'])}")

        timeline = await check_get(
            client,
            "/preference-profile/timeline",
            headers=headers,
            params={"conversation_id": "smoke-conv-001", "limit": 20},
        )
        print(f"[9/10] 时间线事件数：{timeline['total']}")

        undoable = next(item for item in timeline["items"] if item["can_undo"] is True)
        undo = await check_post(
            client,
            "/preference-profile/timeline/undo",
            {"event_id": undoable["id"], "conversation_id": "smoke-conv-001"},
            headers=headers,
        )
        print(f"[10/10] 已撤销事件：{undo['undone_event_id']}")

        refreshed = await check_post(
            client,
            "/auth/refresh",
            {"refresh_token": refresh_token},
            headers={"X-Client-Name": "smoke-script-refresh"},
        )
        await check_post(
            client,
            "/auth/logout",
            {"refresh_token": refreshed["refresh_token"]},
        )

    print("登录态画像与历史中心烟测通过。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:  # noqa: BLE001
        print(f"登录态烟测失败：{safe_console_text(exc)}", file=sys.stderr)
        raise SystemExit(1)
