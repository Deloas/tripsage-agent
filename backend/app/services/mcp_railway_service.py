import asyncio
import json
import re
import shutil
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from loguru import logger

from app.core.config import BACKEND_DIR, settings


class McpRailwayService:
    """12306 MCP 查询服务封装。

    安全边界：
    - 默认不启动外部 MCP 进程，必须显式设置 MCP_12306_ALLOW_LIVE=true。
    - 只允许查询类工具，屏蔽登录、下单、支付、抢票、乘客信息等工具。
    - 所有失败都返回可展示兜底结果，不影响智能体整体工作流。
    """

    SAFE_TOOL_KEYWORDS = (
        "query",
        "train",
        "station",
        "ticket",
        "transfer",
        "price",
        "route",
        "stop",
        "查询",
        "车次",
        "站点",
        "车站",
        "余票",
        "票价",
        "换乘",
        "经停",
    )
    BLOCKED_TOOL_KEYWORDS = (
        "login",
        "order",
        "pay",
        "captcha",
        "grab",
        "passenger",
        "submit",
        "cancel",
        "登录",
        "下单",
        "订单",
        "支付",
        "抢票",
        "候补下单",
        "乘客",
        "验证码",
    )
    PLACEHOLDER_MARKERS = ("请根据", "请填写", "如该", "placeholder", "your-", "todo")

    def __init__(self) -> None:
        self.timeout = settings.mcp_12306_timeout_seconds
        self.server_name = settings.mcp_12306_server_name

    def config_status(self) -> dict[str, Any]:
        """检查 MCP 配置文件和安全开关状态。"""
        path = self._config_path()
        config = self._load_server_config()
        command = config.get("command") if config else None
        url = config.get("url") if config else None
        configured = bool(config and self._server_config_valid(config))
        resolved_command = self._resolve_command(command) if command else None
        return {
            "enabled": settings.mcp_12306_enabled,
            "allow_live": settings.mcp_12306_allow_live,
            "configured": configured,
            "server_name": self.server_name,
            "config_path": str(path),
            "exists": path.exists(),
            "transport": (config or {}).get("transport") or ("stdio" if command else None),
            "command": command if command and not self._looks_placeholder(command) else None,
            "resolved_command": resolved_command,
            "args": self._safe_args((config or {}).get("args") or []),
            "url": url,
            "timeout_seconds": self.timeout,
            "safe_keywords": list(self.SAFE_TOOL_KEYWORDS),
            "blocked_keywords": list(self.BLOCKED_TOOL_KEYWORDS),
        }

    async def ping(self) -> dict[str, Any]:
        """检查 MCP 配置；只有 allow_live=true 时才会尝试发现真实工具。"""
        status = self.config_status()
        if not status["enabled"]:
            return {**status, "ok": False, "message": "12306 MCP 已禁用。"}
        if not status["exists"]:
            return {**status, "ok": False, "message": "未找到 mcp_servers.json。"}
        if not status["configured"]:
            return {**status, "ok": False, "message": "12306 MCP 配置仍是占位符或缺少 command/url。"}
        if not status["allow_live"]:
            return {
                **status,
                "ok": False,
                "message": "已检测到配置，但 MCP_12306_ALLOW_LIVE=false，未启动外部 MCP。",
            }

        try:
            tools = await asyncio.wait_for(self._load_safe_tools(), timeout=self.timeout)
        except Exception as exc:  # noqa: BLE001
            logger.warning("12306 MCP 工具发现失败：{}", exc)
            return {**status, "ok": False, "message": f"MCP 工具发现失败：{exc}"}

        return {
            **status,
            "ok": bool(tools),
            "message": f"发现 {len(tools)} 个安全查询工具" if tools else "未发现安全查询工具",
            "tools": [self._tool_brief(tool) for tool in tools],
        }

    async def query_trains(self, origin: str, destination: str, date_text: str) -> dict[str, Any]:
        """查询铁路车次；配置不可用时返回明确标记的演示结果。"""
        normalized_date = self.normalize_date(date_text)
        status = self.config_status()
        if settings.demo_mode:
            return self._demo_trains(origin, destination, normalized_date, "演示模式开启，使用演示铁路数据")
        if not status["exists"]:
            return self._demo_trains(origin, destination, normalized_date, "未找到 MCP 配置，使用演示铁路数据")
        if not status["configured"]:
            return self._demo_trains(
                origin,
                destination,
                normalized_date,
                "12306 MCP 配置仍是占位符，使用演示铁路数据",
            )
        if not settings.mcp_12306_allow_live:
            return self._demo_trains(
                origin,
                destination,
                normalized_date,
                "MCP_12306_ALLOW_LIVE=false，未启动外部 MCP，使用演示铁路数据",
            )

        try:
            result = await asyncio.wait_for(
                self._query_trains_live(origin, destination, normalized_date),
                timeout=self.timeout,
            )
            if result:
                return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("12306 MCP 查询失败，切换兜底：{}", exc)

        return self._demo_trains(origin, destination, normalized_date, "12306 MCP 查询失败，使用演示铁路数据")

    def normalize_date(self, value: str | None) -> str:
        """把常见中文相对日期转换为 12306 更容易接受的 YYYY-MM-DD。"""
        today = date.today()
        text = (value or "").strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return text
        if re.fullmatch(r"\d{4}/\d{1,2}/\d{1,2}", text):
            year, month, day = [int(item) for item in text.split("/")]
            return date(year, month, day).isoformat()
        if text in {"今天", "今日"}:
            return today.isoformat()
        if text == "明天":
            return (today + timedelta(days=1)).isoformat()
        if text == "后天":
            return (today + timedelta(days=2)).isoformat()
        if "周末" in text:
            days_until_saturday = (5 - today.weekday()) % 7
            days_until_saturday = days_until_saturday or 7
            return (today + timedelta(days=days_until_saturday)).isoformat()
        month_day = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*(?:日|号)?", text)
        if month_day:
            month = int(month_day.group(1))
            day = int(month_day.group(2))
            candidate = date(today.year, month, day)
            if candidate < today:
                candidate = date(today.year + 1, month, day)
            return candidate.isoformat()
        # 非标准日期会造成 12306 查询失败；先退到今天，并在回答层提示用户可进一步指定日期。
        return today.isoformat()

    def is_safe_tool(self, tool_name: str, description: str | None = None) -> bool:
        """过滤 MCP 工具名，防止智能体误调用高风险能力。"""
        haystack = f"{tool_name} {description or ''}".lower()
        if any(keyword in haystack for keyword in self.BLOCKED_TOOL_KEYWORDS):
            return False
        return any(keyword in haystack for keyword in self.SAFE_TOOL_KEYWORDS)

    async def _query_trains_live(
        self,
        origin: str,
        destination: str,
        normalized_date: str,
    ) -> dict[str, Any] | None:
        """调用真实 MCP 安全工具，并把结果归一化给前端和智能体。"""
        tools = await self._load_safe_tools()
        ranked = sorted(tools, key=self._tool_rank, reverse=True)
        attempts: list[dict[str, Any]] = []
        for tool in ranked[:5]:
            payloads = self._payload_candidates(tool, origin, destination, normalized_date)
            for payload in payloads:
                try:
                    raw = await tool.ainvoke(payload)
                except Exception as exc:  # noqa: BLE001
                    attempts.append({"tool": tool.name, "payload": payload, "error": str(exc)})
                    continue
                return self._normalize_live_result(
                    raw,
                    tool.name,
                    origin,
                    destination,
                    normalized_date,
                    attempts,
                )
        return None

    async def _load_safe_tools(self) -> list[BaseTool]:
        """加载 MCP 工具并保留安全查询工具。"""
        config = self._load_server_config()
        if not config or not self._server_config_valid(config):
            return []
        client = MultiServerMCPClient({self.server_name: self._connection_config(config)})
        tools = await client.get_tools(server_name=self.server_name)
        return [tool for tool in tools if self.is_safe_tool(tool.name, tool.description)]

    def _payload_candidates(
        self,
        tool: BaseTool,
        origin: str,
        destination: str,
        normalized_date: str,
    ) -> list[dict[str, Any]]:
        """根据工具 schema 生成多组兼容参数。"""
        schema = self._tool_schema(tool)
        properties = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        schema_payload = self._payload_from_schema(properties, origin, destination, normalized_date)
        payloads = [
            schema_payload,
            {
                "origin": origin,
                "destination": destination,
                "date": normalized_date,
            },
            {
                "from_station": origin,
                "to_station": destination,
                "date": normalized_date,
            },
            {
                "from_city": origin,
                "to_city": destination,
                "train_date": normalized_date,
            },
            {
                "start_station": origin,
                "end_station": destination,
                "travel_date": normalized_date,
            },
        ]
        cleaned: list[dict[str, Any]] = []
        for payload in payloads:
            if required and not required.issubset(payload):
                continue
            if payload not in cleaned:
                cleaned.append(payload)
        return cleaned or [schema_payload]

    def _payload_from_schema(
        self,
        properties: dict[str, Any],
        origin: str,
        destination: str,
        normalized_date: str,
    ) -> dict[str, Any]:
        """按 MCP 工具参数名猜测 origin/destination/date 的映射。"""
        payload: dict[str, Any] = {}
        for name in properties:
            lower = name.lower()
            if any(word in lower for word in ["from", "origin", "start", "departure"]):
                payload[name] = origin
            elif any(word in lower for word in ["to", "dest", "end", "arrival"]):
                payload[name] = destination
            elif "date" in lower or "day" in lower:
                payload[name] = normalized_date
        return payload

    def _normalize_live_result(
        self,
        raw: Any,
        tool_name: str,
        origin: str,
        destination: str,
        normalized_date: str,
        attempts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """把 LangChain/MCP 工具返回转成项目统一结构。"""
        raw_text = self._raw_to_text(raw)
        trains = self._extract_train_rows(raw_text)
        return {
            "provider": "modelscope_12306_mcp",
            "tool_name": tool_name,
            "origin": origin,
            "destination": destination,
            "date": normalized_date,
            "fallback": False,
            "notice": "仅提供查询参考，不支持购票、抢票、登录或支付。",
            "raw_text": raw_text[:4000],
            "trains": trains,
            "attempts": attempts[-3:],
        }

    def _extract_train_rows(self, raw_text: str) -> list[dict[str, Any]]:
        """从 MCP 返回中提取车次结构，优先解析 JSON，失败时再用正则兜底。"""
        structured = self._extract_train_rows_from_json(raw_text)
        if structured:
            return structured[:20]
        trains: list[dict[str, Any]] = []
        for train_no in dict.fromkeys(re.findall(r"\b[GDCKZT]\d{1,5}\b", raw_text)):
            trains.append({"train_no": train_no})
        return trains[:20]

    def _extract_train_rows_from_json(self, raw_text: str) -> list[dict[str, Any]]:
        """兼容 MCP 文本消息里包裹 JSON 字符串的返回格式。"""
        candidates: list[Any] = [raw_text]
        rows: list[dict[str, Any]] = []
        while candidates:
            current = candidates.pop(0)
            if isinstance(current, str):
                text = current.strip()
                if not text:
                    continue
                try:
                    candidates.append(json.loads(text))
                except json.JSONDecodeError:
                    continue
            elif isinstance(current, dict):
                if isinstance(current.get("trains"), list):
                    rows.extend(self._normalize_train_row(item) for item in current["trains"])
                for key in ("text", "content", "data", "result"):
                    if key in current:
                        candidates.append(current[key])
            elif isinstance(current, list):
                candidates.extend(current)
        return [row for row in rows if row.get("train_no")]

    def _normalize_train_row(self, row: Any) -> dict[str, Any]:
        """把 12306 MCP 的车次字段压缩成前端稳定展示字段。"""
        if not isinstance(row, dict):
            return {}
        return {
            "train_no": row.get("train_no") or row.get("train_code") or row.get("station_train_code"),
            "from_station": row.get("from_station"),
            "to_station": row.get("to_station"),
            "start_time": row.get("start_time"),
            "arrive_time": row.get("arrive_time") or row.get("arrival_time"),
            "duration": row.get("duration"),
            "seats": row.get("seats") or {},
        }

    def _raw_to_text(self, raw: Any) -> str:
        """兼容 MCP 工具返回的字符串、列表、字典和消息对象。"""
        if raw is None:
            return ""
        if isinstance(raw, str):
            return raw
        if isinstance(raw, dict):
            return json.dumps(raw, ensure_ascii=False, default=str)
        if isinstance(raw, list):
            return "\n".join(self._raw_to_text(item) for item in raw)
        content = getattr(raw, "content", None)
        if content is not None:
            return self._raw_to_text(content)
        text = getattr(raw, "text", None)
        if text is not None:
            return str(text)
        return str(raw)

    def _tool_rank(self, tool: BaseTool) -> int:
        """按车票查询相关度排序工具。"""
        text = f"{tool.name} {tool.description or ''}".lower()
        score = 0
        for keyword in ["ticket", "query", "train", "余票", "车次", "查询"]:
            if keyword in text:
                score += 3
        for keyword in ["price", "transfer", "stop", "票价", "换乘", "经停"]:
            if keyword in text:
                score += 1
        return score

    def _connection_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """转换 mcp_servers.json 为 langchain-mcp-adapters 连接配置。"""
        if config.get("url"):
            transport = config.get("transport") or "streamable_http"
            if transport == "http":
                transport = "streamable_http"
            return {
                "transport": transport,
                "url": config["url"],
                "headers": config.get("headers") or None,
            }
        return {
            "transport": "stdio",
            "command": self._resolve_command(config["command"]) or config["command"],
            "args": config.get("args") or [],
            "env": config.get("env") or None,
            "cwd": config.get("cwd") or str(BACKEND_DIR.parent),
        }

    def _load_server_config(self) -> dict[str, Any] | None:
        """读取 mcp_servers.json 中的 12306 服务配置。"""
        path = self._config_path()
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("读取 MCP 配置失败：{}", exc)
            return None
        servers = data.get("mcpServers") or data.get("servers") or {}
        if self.server_name in servers:
            return servers[self.server_name]
        for name, config in servers.items():
            if "12306" in name:
                return config
        return None

    def _server_config_valid(self, config: dict[str, Any]) -> bool:
        """判断配置是否足以启动 MCP 连接。"""
        if config.get("url"):
            return not self._looks_placeholder(str(config["url"]))
        command = str(config.get("command") or "")
        return bool(command and not self._looks_placeholder(command))

    def _resolve_command(self, command: str | None) -> str | None:
        """解析 MCP 启动命令，优先使用 PATH，其次使用项目虚拟环境中的可执行文件。"""
        if not command:
            return None
        command_path = Path(command)
        if command_path.is_absolute() and command_path.exists():
            return str(command_path)
        if any(separator in command for separator in ("/", "\\")):
            candidate = (BACKEND_DIR.parent / command_path).resolve()
            return str(candidate) if candidate.exists() else command
        resolved = shutil.which(command)
        if resolved:
            return resolved
        for candidate in [
            BACKEND_DIR / ".venv" / "Scripts" / f"{command}.exe",
            BACKEND_DIR / ".venv" / "Scripts" / command,
            BACKEND_DIR / ".venv" / "bin" / command,
        ]:
            if candidate.exists():
                return str(candidate)
        return command

    def _config_path(self) -> Path:
        """解析 MCP 配置路径，兼容 backend 工作目录和项目根目录启动。"""
        raw = Path(settings.mcp_12306_config_path)
        if raw.is_absolute():
            return raw
        return (BACKEND_DIR / raw).resolve()

    def _looks_placeholder(self, value: str) -> bool:
        """识别配置模板中的占位文本。"""
        lower = value.lower()
        return any(marker.lower() in lower for marker in self.PLACEHOLDER_MARKERS)

    def _safe_args(self, args: list[Any]) -> list[str]:
        """返回可展示参数，避免泄露 token。"""
        safe: list[str] = []
        for item in args:
            text = str(item)
            if "token" in text.lower() or "key" in text.lower():
                safe.append("***")
            else:
                safe.append(text)
        return safe

    def _tool_schema(self, tool: BaseTool) -> dict[str, Any]:
        """兼容 LangChain 工具的 Pydantic schema 和原始 dict schema。"""
        args_schema = getattr(tool, "args_schema", None)
        if args_schema is None:
            return {}
        if isinstance(args_schema, dict):
            return args_schema
        model_json_schema = getattr(args_schema, "model_json_schema", None)
        if callable(model_json_schema):
            return model_json_schema()
        return {}

    def _tool_brief(self, tool: BaseTool) -> dict[str, Any]:
        """返回工具摘要，不包含运行时敏感信息。"""
        schema = self._tool_schema(tool)
        return {
            "name": tool.name,
            "description": tool.description,
            "args": list((schema.get("properties") or {}).keys()),
        }

    def _demo_trains(self, origin: str, destination: str, date_text: str, reason: str) -> dict[str, Any]:
        """提供稳定演示车次，即使 MCP 不可用也能展示完整链路。"""
        return {
            "provider": "modelscope_12306_mcp",
            "origin": origin,
            "destination": destination,
            "date": date_text,
            "fallback": True,
            "reason": reason,
            "notice": "仅提供查询参考，不支持购票、抢票、登录或支付。",
            "trains": [
                {
                    "train_no": "G7391",
                    "from_station": f"{origin}东",
                    "to_station": f"{destination}南",
                    "start_time": "08:12",
                    "arrive_time": "09:48",
                    "duration": "1小时36分",
                    "seats": {"二等座": "有", "一等座": "少量", "商务座": "候补"},
                },
                {
                    "train_no": "G7565",
                    "from_station": f"{origin}站",
                    "to_station": f"{destination}站",
                    "start_time": "10:24",
                    "arrive_time": "12:05",
                    "duration": "1小时41分",
                    "seats": {"二等座": "有", "一等座": "有", "商务座": "少量"},
                },
                {
                    "train_no": "D3141",
                    "from_station": f"{origin}东",
                    "to_station": f"{destination}南",
                    "start_time": "14:30",
                    "arrive_time": "16:28",
                    "duration": "1小时58分",
                    "seats": {"二等座": "有", "一等座": "候补"},
                },
            ],
        }
