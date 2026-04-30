import json
from typing import Any

import httpx
from loguru import logger

from app.core.config import public_url, settings


class LlmService:
    """DeepSeek/OpenAI-compatible 大模型服务封装。

    未配置 API Key 时返回 None，让智能体使用规则兜底，保证本地演示稳定。
    """

    def provider(self) -> str:
        """返回当前大模型供应商名称。"""
        return settings.llm_provider or "deepseek"

    def base_url(self) -> str:
        """DeepSeek 官方兼容 OpenAI 的默认 base_url。"""
        if settings.llm_base_url:
            return public_url(settings.llm_base_url)
        if self.provider().lower() == "deepseek":
            return "https://api.deepseek.com"
        return ""

    def configured(self) -> bool:
        """判断大模型是否可调用。"""
        return bool(settings.llm_api_key and self.base_url() and settings.llm_model)

    def config_status(self) -> dict[str, Any]:
        """返回可公开展示的大模型配置状态，不包含 API Key。"""
        return {
            "provider": self.provider(),
            "model": settings.llm_model,
            "base_url": self.base_url(),
            "configured": self.configured(),
            "has_api_key": bool(settings.llm_api_key),
            "timeout_seconds": settings.llm_timeout_seconds,
            "max_tokens": settings.llm_max_tokens,
        }

    async def chat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> str | None:
        """调用大模型聊天接口。"""
        if not self.configured():
            return None

        url = self.base_url() + "/chat/completions"
        payload = {
            "model": settings.llm_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": settings.llm_max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
            return data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            # 大模型异常不能拖垮课程演示主流程，智能体会自动切回规则与模板兜底。
            logger.warning("LLM 调用失败，已切换兜底回答：{}", exc)
            return None

    async def ping(self) -> dict[str, Any]:
        """主动测试 DeepSeek/OpenAI-compatible 接口连通性。"""
        status = self.config_status()
        if not self.configured():
            return {
                **status,
                "ok": False,
                "message": "未配置 LLM_API_KEY，当前会使用本地规则兜底。",
            }

        content = await self.chat(
            [
                {"role": "system", "content": "你是接口健康检查助手，只输出中文短句。"},
                {"role": "user", "content": "请回复：DeepSeek 连接正常"},
            ],
            temperature=0,
        )
        return {
            **status,
            "ok": bool(content),
            "message": content or "接口调用失败，请检查 API Key、余额、网络或 base_url。",
        }

    async def json_chat(self, prompt: str) -> dict[str, Any] | None:
        """要求模型输出 JSON，并做一次宽松解析。"""
        content = await self.chat(
            [
                {"role": "system", "content": "你只输出严格 JSON，不输出 Markdown。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
        )
        if not content:
            return None
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.replace("json", "", 1).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None

    async def plain_chat(self, prompt: str) -> str | None:
        """生成普通文本回答。"""
        return await self.chat(
            [
                {"role": "system", "content": "你是严谨的中国旅行规划智能体。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )
