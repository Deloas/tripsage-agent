import json
from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db.models import Conversation, PlanVersion, SharedPlan
from app.schemas.plans import (
    PlanExportView,
    PlanVersionCompareView,
    PlanVersionCreate,
    PlanVersionView,
    SharedPlanView,
)


class PlanVersionService:
    """方案版本服务，负责持久化、对比、导出与分享。"""

    def __init__(self, db: Session):
        self.db = db

    def save(self, payload: PlanVersionCreate, user_id: int | None = None) -> PlanVersionView:
        """保存或覆盖同 ID 的方案版本。"""
        self._ensure_owned_conversation(payload.conversation_id, user_id)
        model = self.db.get(PlanVersion, payload.id)
        created_at = self._parse_created_at(payload.created_at)
        response_json = json.dumps(payload.response, ensure_ascii=False, default=str)
        if model:
            model.name = payload.name
            model.reason = payload.reason
            model.response_json = response_json
            model.created_at = created_at
        else:
            model = PlanVersion(
                id=payload.id,
                conversation_id=payload.conversation_id,
                name=payload.name,
                reason=payload.reason,
                response_json=response_json,
                created_at=created_at,
            )
            self.db.add(model)
        self.db.commit()
        self.db.refresh(model)
        return self._to_view(model)

    def list_by_conversation(
        self,
        conversation_id: str,
        user_id: int | None = None,
    ) -> list[PlanVersionView]:
        """按会话读取版本列表。"""
        self._ensure_owned_conversation(conversation_id, user_id)
        items = (
            self.db.query(PlanVersion)
            .filter(PlanVersion.conversation_id == conversation_id)
            .order_by(PlanVersion.created_at.asc())
            .all()
        )
        return [self._to_view(item) for item in items]

    def compare(
        self,
        base_id: str,
        target_id: str,
        user_id: int | None = None,
    ) -> PlanVersionCompareView:
        """比较两个版本的结构化差异。"""
        base = self._get_version(base_id, user_id)
        target = self._get_version(target_id, user_id)
        base_response = self._load_response(base)
        target_response = self._load_response(target)
        metrics = {
            "source_delta": len(target_response.get("sources") or []) - len(base_response.get("sources") or []),
            "tool_delta": len(target_response.get("tool_calls") or []) - len(base_response.get("tool_calls") or []),
            "warning_delta": len(target_response.get("warnings") or []) - len(base_response.get("warnings") or []),
            "itinerary_day_delta": len(target_response.get("itinerary") or []) - len(base_response.get("itinerary") or []),
            "module_delta": len(target_response.get("decision_modules") or [])
            - len(base_response.get("decision_modules") or []),
        }
        highlights = self._build_highlights(base_response, target_response, metrics)
        return PlanVersionCompareView(
            base_id=base_id,
            target_id=target_id,
            title=f"{base.name} -> {target.name}",
            summary="已从来源、工具、风险、天数和决策模块维度完成版本对比。",
            metrics=metrics,
            highlights=highlights,
        )

    def export(
        self,
        version_id: str,
        export_format: str,
        user_id: int | None = None,
    ) -> PlanExportView:
        """导出指定方案版本。"""
        version = self._get_version(version_id, user_id)
        response = self._load_response(version)
        title = self._export_title(version, response)
        if export_format == "html":
            return PlanExportView(
                filename=f"{self._safe_filename(title)}.html",
                mime_type="text/html;charset=utf-8",
                content=self._build_html(title, response),
            )
        return PlanExportView(
            filename=f"{self._safe_filename(title)}.md",
            mime_type="text/markdown;charset=utf-8",
            content=self._build_markdown(title, response),
        )

    def create_share(self, version_id: str, user_id: int | None = None) -> SharedPlanView:
        """为某个方案版本创建本地只读分享页。"""
        version = self._get_version(version_id, user_id)
        response = self._load_response(version)
        share = SharedPlan(
            id=uuid4().hex[:12],
            version_id=version.id,
            conversation_id=version.conversation_id,
            title=self._export_title(version, response),
            response_json=version.response_json,
        )
        self.db.add(share)
        self.db.commit()
        self.db.refresh(share)
        return self._share_to_view(share)

    def get_share(self, share_id: str) -> SharedPlanView:
        """读取本地只读分享页。"""
        share = self.db.get(SharedPlan, share_id)
        if not share:
            raise ValueError("分享方案不存在")
        return self._share_to_view(share)

    def _get_version(self, version_id: str, user_id: int | None = None) -> PlanVersion:
        version = self.db.get(PlanVersion, version_id)
        if not version:
            raise ValueError("方案版本不存在")
        self._ensure_owned_conversation(version.conversation_id, user_id)
        return version

    def _ensure_owned_conversation(self, conversation_id: str, user_id: int | None) -> None:
        if user_id is None:
            return
        conversation = self.db.get(Conversation, conversation_id)
        if not conversation:
            raise ValueError("关联会话不存在")
        if conversation.user_id != user_id:
            raise ValueError("无权访问该方案版本")

    def _to_view(self, item: PlanVersion) -> PlanVersionView:
        return PlanVersionView(
            id=item.id,
            conversation_id=item.conversation_id,
            name=item.name,
            reason=item.reason,
            response=self._load_response(item),
            createdAt=item.created_at.isoformat(),
        )

    def _load_response(self, item: PlanVersion) -> dict:
        try:
            return json.loads(item.response_json)
        except json.JSONDecodeError:
            return {}

    def _load_shared_response(self, item: SharedPlan) -> dict:
        try:
            return json.loads(item.response_json)
        except json.JSONDecodeError:
            return {}

    def _parse_created_at(self, value: str | None) -> datetime:
        if not value:
            return datetime.utcnow()
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
            return parsed.replace(tzinfo=None)
        except ValueError:
            return datetime.utcnow()

    def _build_highlights(self, base: dict, target: dict, metrics: dict) -> list[str]:
        highlights: list[str] = []
        if metrics["tool_delta"] > 0:
            highlights.append(f"新版本多调用 {metrics['tool_delta']} 个工具，实时依据更充分。")
        if metrics["source_delta"] > 0:
            highlights.append(f"新版本新增 {metrics['source_delta']} 个引用来源，可解释性更强。")
        if metrics["warning_delta"] > 0:
            highlights.append(f"新版本增加 {metrics['warning_delta']} 条风险提醒，适合出发前复核。")
        if metrics["warning_delta"] < 0:
            highlights.append(f"新版本减少 {abs(metrics['warning_delta'])} 条风险提醒，方案更收敛。")
        base_titles = self._day_titles(base)
        target_titles = self._day_titles(target)
        changed_days = [title for title in target_titles if title not in base_titles]
        if changed_days:
            highlights.append(f"行程标题出现新调整：{changed_days[0]}")
        if not highlights:
            highlights.append("两个版本结构接近，主要差异集中在文字建议和细节表述。")
        return highlights[:4]

    def _day_titles(self, response: dict) -> set[str]:
        return {
            str(day.get("title", ""))
            for day in response.get("itinerary") or []
            if isinstance(day, dict)
        }

    def _share_to_view(self, item: SharedPlan) -> SharedPlanView:
        return SharedPlanView(
            id=item.id,
            version_id=item.version_id,
            conversation_id=item.conversation_id,
            title=item.title,
            response=self._load_shared_response(item),
            createdAt=item.created_at.isoformat(),
        )

    def _export_title(self, version: PlanVersion, response: dict) -> str:
        destination = next(
            (
                str(card.get("title"))
                for card in response.get("cards") or []
                if isinstance(card, dict) and card.get("type") == "destination" and card.get("title")
            ),
            "",
        )
        return f"{destination or '旅行方案'} - {version.name}"

    def _safe_filename(self, title: str) -> str:
        keep = [char if char.isalnum() or char in ("-", "_") else "-" for char in title.strip()]
        filename = "".join(keep).strip("-")
        return filename[:80] or "tripsage-plan"

    def _build_markdown(self, title: str, response: dict) -> str:
        lines = [
            f"# {title}",
            "",
            "## 智能体建议",
            "",
            str(response.get("answer") or "暂无文字建议。"),
            "",
        ]
        itinerary = response.get("itinerary") or []
        if itinerary:
            lines.extend(["## 行程安排", ""])
            for day in itinerary:
                if not isinstance(day, dict):
                    continue
                lines.extend([f"### DAY {day.get('day', '')} {day.get('title', '')}", ""])
                for item in day.get("items") or []:
                    if isinstance(item, dict):
                        lines.append(
                            f"- **{item.get('time', '弹性')} · {item.get('title', '安排')}**：{item.get('detail', '')}"
                        )
                lines.append("")
        modules = response.get("decision_modules") or []
        if modules:
            lines.extend(["## 决策提示", ""])
            for module in modules:
                if isinstance(module, dict):
                    lines.append(f"- **{module.get('title', '提示')}**：{module.get('summary', '')}")
            lines.append("")
        sources = response.get("sources") or []
        if sources:
            lines.extend(["## 引用来源", ""])
            for source in sources:
                if isinstance(source, dict):
                    title_text = source.get("title", "来源")
                    url = source.get("url")
                    lines.append(f"- [{title_text}]({url})" if url else f"- {title_text}")
        return "\n".join(lines).strip() + "\n"

    def _build_html(self, title: str, response: dict) -> str:
        markdown = self._build_markdown(title, response)
        body = markdown.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        paragraphs = "".join(f"<p>{line}</p>" if line else "" for line in body.splitlines())
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    body {{ margin: 0; background: #f4efe2; color: #18342c; font-family: "Microsoft YaHei", sans-serif; }}
    main {{ max-width: 920px; margin: 40px auto; padding: 32px; background: #fffaf0; border: 1px solid #d7cdb9; }}
    p {{ line-height: 1.8; white-space: pre-wrap; }}
  </style>
</head>
<body><main>{paragraphs}</main></body>
</html>"""
