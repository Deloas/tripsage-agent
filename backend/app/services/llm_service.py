import json
import re
from typing import Any

import httpx
from loguru import logger

from app.core.config import public_url, settings


class LlmService:
    """DeepSeek/OpenAI-compatible 大模型服务封装。"""

    def provider(self) -> str:
        """返回当前大模型提供商名称。"""
        return settings.llm_provider or "deepseek"

    def base_url(self) -> str:
        """返回兼容 OpenAI 的 base_url。"""
        if settings.llm_base_url:
            return public_url(settings.llm_base_url)
        if self.provider().lower() == "deepseek":
            return "https://api.deepseek.com"
        return ""

    def configured(self) -> bool:
        """判断大模型是否可调用。"""
        return bool(settings.llm_api_key and self.base_url() and settings.llm_model)

    def config_status(self) -> dict[str, Any]:
        """返回可公开展示的模型配置状态。"""
        return {
            "provider": self.provider(),
            "model": settings.llm_model,
            "base_url": self.base_url(),
            "configured": self.configured(),
            "has_api_key": bool(settings.llm_api_key),
            "timeout_seconds": settings.llm_timeout_seconds,
            "max_tokens": settings.llm_max_tokens,
        }

    async def chat(self, messages: list[dict[str, Any]], temperature: float = 0.2) -> str | None:
        """调用聊天补全接口。"""
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
            logger.warning("LLM 调用失败，已切换兜底：{}", exc)
            return None

    async def ping(self) -> dict[str, Any]:
        """主动测试模型接口连通性。"""
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
        parsed = self._parse_json_response(content)
        if parsed is None:
            logger.warning("LLM JSON 解析失败，原始回复前 400 字符：{}", content[:400])
        return parsed

    async def vision_plain_chat(self, prompt: str, image_urls: list[str]) -> str | None:
        """尝试通过多模态接口直接读取图片中的攻略文本。"""
        if not self.configured() or not image_urls:
            return None
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image_url in image_urls[:4]:
            content.append({"type": "image_url", "image_url": {"url": image_url}})
        return await self.chat(
            [
                {"role": "system", "content": "你是严谨的中文 OCR 与攻略提取助手，只输出纯文本，不要解释。"},
                {"role": "user", "content": content},
            ],
            temperature=0,
        )

    async def plain_chat(self, prompt: str) -> str | None:
        """生成普通文本回答。"""
        return await self.chat(
            [
                {"role": "system", "content": "你是严谨的中国旅行规划智能体。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )

    def _parse_json_response(self, content: str) -> dict[str, Any] | None:
        """中文注释：对大模型回复做宽松 JSON 抽取，避免因少量前后缀就整段失效。"""
        cleaned = self._strip_markdown_fence(content)
        direct = self._try_load_json(cleaned)
        if direct is not None:
            return direct

        decoder = json.JSONDecoder()
        for match in re.finditer(r"[\{\[]", cleaned):
            fragment = cleaned[match.start() :].strip()
            try:
                parsed, _ = decoder.raw_decode(fragment)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed

        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            return self._try_load_json(cleaned[start : end + 1])
        return None

    def _strip_markdown_fence(self, content: str) -> str:
        cleaned = content.strip()
        if not cleaned.startswith("```"):
            return cleaned
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        return cleaned.strip()

    def _try_load_json(self, content: str) -> dict[str, Any] | None:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
