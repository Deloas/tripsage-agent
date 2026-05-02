import json
import re
from datetime import datetime
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Conversation, Itinerary, Message, PlanVersion, SharedPlan, ToolCall, utc_now
from app.schemas.workspace import (
    ConversationDetail,
    ConversationSummary,
    ConversationUpdateRequest,
    GuestSessionImportRequest,
    GuestSessionImportView,
    MessageView,
)
from app.services.preference_service import PreferenceService


class ConversationService:
    """历史规划中心服务，负责会话列表、元数据维护和会话恢复。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_conversations(self, user_id: int | None = None) -> list[ConversationSummary]:
        """按更新时间倒序列出历史会话。"""
        query = self.db.query(Conversation)
        if user_id is not None:
            query = query.filter(Conversation.user_id == user_id)
        conversations = query.order_by(Conversation.updated_at.desc()).all()
        return [self._to_summary(conversation) for conversation in conversations]

    def get_conversation(self, conversation_id: str, user_id: int | None = None) -> ConversationDetail:
        """读取会话详情和消息。"""
        conversation = self._get_owned_conversation(conversation_id, user_id)
        messages = (
            self.db.query(Message)
            .filter(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .all()
        )
        return ConversationDetail(
            id=conversation.id,
            title=conversation.title,
            status=conversation.status,
            messages=[
                MessageView(role=item.role, content=item.content, created_at=item.created_at.isoformat())
                for item in messages
            ],
            is_favorite=bool(conversation.is_favorite),
            tags=self._load_tags(conversation.tags_json),
            destination_city=conversation.destination_city,
            budget=conversation.budget,
            start_date=conversation.start_date,
        )

    def update_conversation(
        self,
        conversation_id: str,
        payload: ConversationUpdateRequest,
        user_id: int | None = None,
    ) -> ConversationSummary:
        """更新收藏、标签和索引字段，便于历史规划按业务信息检索。"""
        conversation = self._get_owned_conversation(conversation_id, user_id)
        if "title" in payload.model_fields_set:
            conversation.title = (payload.title or "").strip()[:160] or conversation.title
        if "is_favorite" in payload.model_fields_set:
            conversation.is_favorite = bool(payload.is_favorite)
        if "tags" in payload.model_fields_set:
            conversation.tags_json = json.dumps(self._normalize_tags(payload.tags or []), ensure_ascii=False)
        if "destination_city" in payload.model_fields_set:
            conversation.destination_city = self._clean_text(payload.destination_city, 60)
        if "budget" in payload.model_fields_set:
            conversation.budget = payload.budget
        if "start_date" in payload.model_fields_set:
            conversation.start_date = self._clean_text(payload.start_date, 40)
        conversation.updated_at = utc_now()
        self.db.commit()
        self.db.refresh(conversation)
        return self._to_summary(conversation)

    def delete_conversation(self, conversation_id: str, user_id: int | None = None) -> dict:
        """删除会话及其关联版本、消息、工具日志和分享数据。"""
        conversation = self._get_owned_conversation(conversation_id, user_id)
        version_ids = [
            row[0]
            for row in (
                self.db.query(PlanVersion.id)
                .filter(PlanVersion.conversation_id == conversation_id)
                .all()
            )
        ]
        if version_ids:
            self.db.query(SharedPlan).filter(SharedPlan.version_id.in_(version_ids)).delete(
                synchronize_session=False
            )
        self.db.query(SharedPlan).filter(SharedPlan.conversation_id == conversation_id).delete(
            synchronize_session=False
        )
        self.db.query(PlanVersion).filter(PlanVersion.conversation_id == conversation_id).delete(
            synchronize_session=False
        )
        self.db.query(Itinerary).filter(Itinerary.conversation_id == conversation_id).delete(
            synchronize_session=False
        )
        self.db.query(ToolCall).filter(ToolCall.conversation_id == conversation_id).delete(
            synchronize_session=False
        )
        self.db.query(Message).filter(Message.conversation_id == conversation_id).delete(
            synchronize_session=False
        )
        self.db.delete(conversation)
        self.db.commit()
        return {"id": conversation_id, "deleted": True}

    def sync_archive_meta(
        self,
        conversation_id: str,
        user_message: str,
        response_data: dict,
        slots: dict,
        user_id: int | None = None,
    ) -> None:
        """在智能体完成后自动沉淀历史索引，减少用户手工整理成本。"""
        conversation = self._get_owned_conversation(conversation_id, user_id, check_exists=False)
        if not conversation:
            return

        destination = self._clean_text(
            slots.get("destination") or self._destination_from_cards(response_data.get("cards", [])),
            60,
        )
        budget = self._parse_budget(slots.get("budget"))
        start_date = self._clean_text(slots.get("date"), 40)
        days = self._parse_days(slots.get("days"))
        auto_tags = self._build_auto_tags(slots, response_data)

        if destination:
            conversation.destination_city = destination
        if budget is not None:
            conversation.budget = budget
        if start_date:
            conversation.start_date = start_date
        if auto_tags and conversation.tags_json is None:
            conversation.tags_json = json.dumps(auto_tags, ensure_ascii=False)
        if self._should_refresh_title(conversation.title, user_message):
            conversation.title = self._build_archive_title(destination, days, start_date, user_message)

        conversation.updated_at = utc_now()
        self.db.commit()

    def import_guest_session(self, payload: GuestSessionImportRequest) -> GuestSessionImportView:
        """把游客临时方案转入某个已登录账号，形成可继续管理的持久化会话。"""
        meaningful_messages = [
            item for item in payload.messages if self._clean_text(item.content, 4000)
        ]
        if not meaningful_messages and not payload.plan_versions and not payload.latest_response:
            raise ValueError("娓稿浼氳瘽娌℃湁鍙鍏ョ殑鍐呭")

        conversation_id = uuid4().hex
        conversation = Conversation(
            id=conversation_id,
            user_id=payload.user_id,
            title=self._build_guest_import_title(payload, meaningful_messages),
            destination_city=self._clean_text(payload.destination_city, 60),
            budget=payload.budget,
            start_date=self._clean_text(payload.start_date, 40),
            tags_json=json.dumps(self._normalize_tags(payload.tags), ensure_ascii=False)
            if payload.tags
            else None,
            updated_at=utc_now(),
        )
        self.db.add(conversation)
        self.db.flush()

        for item in meaningful_messages:
            self.db.add(
                Message(
                    conversation_id=conversation_id,
                    role=item.role,
                    content=item.content.strip(),
                )
            )

        for version in payload.plan_versions:
            self.db.merge(
                PlanVersion(
                    id=version.id,
                    conversation_id=conversation_id,
                    name=version.name,
                    reason=version.reason,
                    response_json=json.dumps(version.response, ensure_ascii=False, default=str),
                    created_at=self._parse_plan_created_at(version.created_at),
                )
            )

        self.db.commit()

        latest_response = self._pick_latest_response(payload)
        latest_user_message = self._latest_user_message(meaningful_messages)
        if latest_response and latest_user_message:
            self.sync_archive_meta(
                conversation_id,
                latest_user_message,
                latest_response,
                {
                    "destination": payload.destination_city,
                    "budget": payload.budget,
                    "date": payload.start_date,
                },
                user_id=payload.user_id,
            )
            PreferenceService(self.db, user_key=str(payload.user_id)).learn_from_interaction(
                latest_user_message,
                latest_response,
                slots={
                    "destination": payload.destination_city,
                    "budget": payload.budget,
                    "date": payload.start_date,
                },
                conversation_id=conversation_id,
            )

        saved_conversation = self.db.get(Conversation, conversation_id)
        return GuestSessionImportView(
            conversation_id=conversation_id,
            title=saved_conversation.title if saved_conversation else conversation.title,
            active_version_id=payload.active_version_id,
            imported_message_count=len(meaningful_messages),
            imported_plan_version_count=len(payload.plan_versions),
        )

    def _to_summary(self, conversation: Conversation) -> ConversationSummary:
        """把数据库对象转换为前端历史中心需要的摘要结构。"""
        message_count = (
            self.db.query(func.count(Message.id))
            .filter(Message.conversation_id == conversation.id)
            .scalar()
            or 0
        )
        version_count = (
            self.db.query(func.count(PlanVersion.id))
            .filter(PlanVersion.conversation_id == conversation.id)
            .scalar()
            or 0
        )
        latest = (
            self.db.query(Message)
            .filter(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc())
            .first()
        )
        return ConversationSummary(
            id=conversation.id,
            title=conversation.title,
            status=conversation.status,
            message_count=message_count,
            version_count=version_count,
            updated_at=conversation.updated_at.isoformat(),
            latest_message=latest.content[:120] if latest else None,
            is_favorite=bool(conversation.is_favorite),
            tags=self._load_tags(conversation.tags_json),
            destination_city=conversation.destination_city,
            budget=conversation.budget,
            start_date=conversation.start_date,
        )

    def _get_owned_conversation(
        self,
        conversation_id: str,
        user_id: int | None = None,
        check_exists: bool = True,
    ) -> Conversation | None:
        conversation = self.db.get(Conversation, conversation_id)
        if not conversation:
            if check_exists:
                raise ValueError("会话不存在")
            return None
        if user_id is not None and conversation.user_id != user_id:
            raise ValueError("无权读取该会话")
        return conversation

    def _load_tags(self, value: str | None) -> list[str]:
        """解析数据库中的标签 JSON。"""
        if not value:
            return []
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return self._normalize_tags(parsed if isinstance(parsed, list) else [])

    def _normalize_tags(self, tags: list[str]) -> list[str]:
        """整理标签数组，限制长度并去重，避免历史中心显示噪声。"""
        result: list[str] = []
        seen: set[str] = set()
        for raw_tag in tags:
            tag = self._clean_text(raw_tag, 20)
            if not tag or tag in seen:
                continue
            seen.add(tag)
            result.append(tag)
        return result[:8]

    def _clean_text(self, value: str | None, max_length: int) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text[:max_length] if text else None

    def _parse_budget(self, raw_value) -> int | None:
        """把槽位中的预算信息转成整数，供档案过滤和展示。"""
        if raw_value is None:
            return None
        if isinstance(raw_value, int):
            return raw_value
        match = re.search(r"([0-9]{2,6})", str(raw_value))
        return int(match.group(1)) if match else None

    def _parse_days(self, raw_value) -> int | None:
        if raw_value is None:
            return None
        if isinstance(raw_value, int):
            return raw_value
        normalized = str(raw_value).strip()
        mapping = {
            "一": 1,
            "二": 2,
            "两": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
            "十": 10,
        }
        if normalized.isdigit():
            return int(normalized)
        return mapping.get(normalized)

    def _destination_from_cards(self, cards: list[dict]) -> str | None:
        for card in cards:
            if card.get("type") == "destination" and card.get("title"):
                return str(card["title"])
        return None

    def _build_auto_tags(self, slots: dict, response_data: dict) -> list[str]:
        """把智能体上下文沉淀成首批可筛选标签。"""
        tags: list[str] = []
        destination = self._clean_text(slots.get("destination"), 20)
        date_text = self._clean_text(slots.get("date"), 20)
        budget = self._parse_budget(slots.get("budget"))
        user_message = str(response_data.get("answer") or "")
        modules = response_data.get("decision_modules") or []

        if destination:
            tags.append(destination)
        if budget is not None:
            tags.append(self._budget_label(budget))
        if date_text:
            tags.append(self._time_label(date_text))
        if slots.get("origin"):
            tags.append("含往返交通")
        if "高铁" in user_message or "铁路" in user_message:
            tags.append("高铁出行")
        if any(module.get("type") == "rainy_day" and module.get("level") == "warn" for module in modules):
            tags.append("雨天备选")
        return self._normalize_tags(tags)

    def _budget_label(self, budget: int) -> str:
        if budget < 1000:
            return "轻预算"
        if budget < 3000:
            return "均衡预算"
        if budget < 6000:
            return "舒适预算"
        return "高配预算"

    def _time_label(self, value: str) -> str:
        if any(keyword in value for keyword in ["周末", "周六", "周日"]):
            return "周末出行"
        if any(keyword in value for keyword in ["五一", "十一", "国庆", "端午", "中秋", "春节", "暑假", "寒假", "假期"]):
            return "假期出行"
        if any(keyword in value for keyword in ["明天", "后天", "本周", "下周", "近期", "最近"]):
            return "近期出行"
        return "已定日期"

    def _should_refresh_title(self, current_title: str | None, first_message: str) -> bool:
        if not current_title:
            return True
        seed = first_message[:40].strip()
        normalized_title = current_title.strip()
        if bool(seed) and normalized_title == seed:
            return True
        # 自动生成的旧标题如果仍是英文描述或缺少行程语义，允许被结构化标题覆盖。
        if normalized_title.isascii():
            return True
        return not any(keyword in normalized_title for keyword in ["出行", "旅行", "行程", "规划"])

    def _build_guest_import_title(
        self,
        payload: GuestSessionImportRequest,
        messages,
    ) -> str | None:
        title = self._clean_text(payload.title, 160)
        if title:
            return title
        destination = self._clean_text(payload.destination_city, 60)
        if destination and payload.start_date:
            return f"{payload.start_date} {destination}鍑鸿"
        if destination:
            return f"{destination}鏃呰瑙勫垝"
        latest_user_message = self._latest_user_message(messages)
        return latest_user_message[:40] if latest_user_message else "娓稿瀵艰繘鏂规"

    def _latest_user_message(self, messages) -> str | None:
        for item in reversed(messages):
            if item.role == "user":
                return item.content.strip()
        return None

    def _pick_latest_response(self, payload: GuestSessionImportRequest) -> dict | None:
        if payload.active_version_id:
            for version in payload.plan_versions:
                if version.id == payload.active_version_id:
                    return version.response
        if payload.plan_versions:
            return payload.plan_versions[-1].response
        return payload.latest_response

    def _parse_plan_created_at(self, value: str | None) -> datetime:
        if not value:
            return utc_now().replace(tzinfo=None)
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
            return parsed.replace(tzinfo=None)
        except ValueError:
            return utc_now().replace(tzinfo=None)

    def _build_archive_title(
        self,
        destination: str | None,
        days: int | None,
        start_date: str | None,
        fallback: str,
    ) -> str:
        if destination and days:
            return f"{destination}{days}日行程"
        if destination and start_date:
            return f"{start_date} {destination}出行"
        if destination:
            return f"{destination}旅行规划"
        return fallback[:40]
