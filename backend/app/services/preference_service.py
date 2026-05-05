import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from uuid import uuid4

from sqlalchemy.orm import Session

from app.agents.nodes import CITY_WORDS
from app.db.models import TravelPreferenceEvent, TravelPreferenceProfile, User, utc_now
from app.schemas.workspace import (
    BudgetProfileView,
    PreferenceAuditGroupView,
    PreferenceAuditItemView,
    PreferenceAuditSummaryView,
    PreferenceAuditView,
    PreferenceEvidenceView,
    PreferenceGovernanceItemView,
    PreferenceLayerView,
    PreferenceProfileView,
    PreferenceTimelineItemView,
    PreferenceTimelineUndoResultView,
    PreferenceTimelineView,
)


TRANSPORT_PATTERNS = {
    "高铁": ["高铁", "动车", "G字头", "D字头"],
    "地铁": ["地铁"],
    "公交": ["公交", "公交车"],
    "打车": ["打车", "出租车", "网约车"],
    "步行": ["步行", "走路"],
    "自驾": ["自驾", "开车"],
    "少换乘": ["少换乘", "尽量别换乘", "不要换乘", "少折腾"],
}

PACE_PATTERNS = {
    "轻松": ["轻松", "悠闲", "慢游", "慢慢逛", "宽松", "不赶", "不想太赶", "别太赶"],
    "紧凑": ["紧凑", "高密度", "特种兵", "多打卡", "早出晚归"],
    "深度体验": ["深度", "沉浸", "深度体验"],
    "亲子友好": ["亲子", "带娃", "适合小朋友"],
    "不折返": ["不折返", "少折返", "顺路"],
}

INTEREST_PATTERNS = {
    "美食": ["美食", "小吃", "探店", "吃点好的", "餐厅"],
    "历史": ["历史", "古迹", "遗址", "人文"],
    "博物馆": ["博物馆", "展览", "馆"],
    "园林": ["园林"],
    "夜景": ["夜景", "夜游", "灯光"],
    "摄影": ["拍照", "摄影", "出片"],
    "自然": ["自然", "山水", "徒步", "风景"],
    "文化": ["文化", "演出", "非遗", "街区文化"],
}

NEGATIVE_PATTERNS = {
    "早班车": ["不要早班车", "别太早出发", "不想太早出发", "不想早起", "睡到自然醒"],
    "高强度": ["不要太赶", "别太赶", "不想太赶", "不要特种兵", "不想排太满", "不要高强度"],
    "步行过多": ["少走路", "不要走太多路", "别走太多路"],
    "爬山过多": ["别安排太多爬山", "不要爬山", "不想爬山", "少爬山", "爬山少一点", "减少爬山", "避免爬山", "不安排爬山"],
    "徒步过多": ["不要徒步", "不想徒步", "少徒步", "减少徒步", "避免徒步"],
    "打车过多": ["少打车", "不要老打车", "不想一直打车"],
    "商业化景点": ["不要太商业", "不想去太商业化", "别太商业"],
    "折返": ["不要折返", "别折返", "不想来回跑"],
}

BUDGET_STYLE_PATTERNS = {
    "预算敏感": ["省钱", "预算控制", "控制预算", "性价比", "穷游", "花少一点"],
    "体验优先": ["体验优先", "住好一点", "吃好一点", "预算不是问题", "愿意花钱", "品质优先"],
}

MODULE_DEFAULT_SIGNALS = {
    "transport": ("transport", "交通衔接优先"),
    "rainy_day": ("risk", "雨天备选"),
    "intensity": ("pace", "强度可控"),
    "budget": ("budget_style", "预算控制"),
    "risk": ("risk", "风险提醒"),
}

SOURCE_GROUPS = {
    "user_message": "explicit",
    "profile_setting": "explicit",
    "manual_prefer": "explicit",
    "manual_avoid": "explicit",
    "manual_session": "explicit",
    "manual_demote": "explicit",
    "manual_allow": "explicit",
    "manual_lock": "explicit",
    "manual_unlock": "explicit",
    "trip_signal": "inferred",
    "destination_inferred": "inferred",
    "decision_accept": "behavior",
    "decision_ignore": "behavior",
    "itinerary_edit": "behavior",
    "railway_selection": "behavior",
    "version_select": "behavior",
    "version_rollback": "behavior",
    "favorite_on": "behavior",
    "favorite_off": "behavior",
    "share_plan": "behavior",
    "history_open": "behavior",
    "continue_optimize": "behavior",
    "memory_open": "behavior",
    "audit_open": "behavior",
    "governance_open": "behavior",
    "blacklist_remove": "behavior",
    "profile_lock": "behavior",
    "profile_unlock": "behavior",
    "timeline_undo": "behavior",
    "legacy_profile": "inferred",
}

SOURCE_WEIGHTS = {
    "user_message": 1.0,
    "profile_setting": 1.15,
    "manual_prefer": 1.75,
    "manual_avoid": 1.75,
    "manual_session": 1.55,
    "manual_demote": 2.0,
    "manual_allow": 1.85,
    "manual_lock": 2.35,
    "manual_unlock": 2.05,
    "trip_signal": 0.45,
    "destination_inferred": 0.35,
    "decision_accept": 1.1,
    "decision_ignore": 1.0,
    "itinerary_edit": 1.2,
    "railway_selection": 1.05,
    "version_select": 0.78,
    "version_rollback": 1.1,
    "favorite_on": 1.18,
    "favorite_off": 0.65,
    "share_plan": 0.95,
    "history_open": 0.92,
    "continue_optimize": 1.08,
    "memory_open": 0.58,
    "audit_open": 0.54,
    "governance_open": 0.52,
    "blacklist_remove": 0.88,
    "profile_lock": 0.94,
    "profile_unlock": 0.9,
    "timeline_undo": 0.82,
    "legacy_profile": 0.55,
}

SESSION_SCOPED_SOURCE_TYPES = {"manual_session"}
CURRENT_CONVERSATION_TRANSIENT_SOURCES = {
    "user_message",
    "trip_signal",
    "destination_inferred",
    "decision_accept",
    "decision_ignore",
    "itinerary_edit",
    "railway_selection",
    "continue_optimize",
}

TIMELINE_SOURCE_LABELS = {
    "manual_allow": "移除黑名单",
    "manual_lock": "长期锁定",
    "manual_unlock": "解除锁定",
    "memory_open": "打开画像中心",
    "audit_open": "打开审计视图",
    "governance_open": "打开治理面板",
    "blacklist_remove": "移除黑名单",
    "profile_lock": "锁定长期偏好",
    "profile_unlock": "解除长期锁定",
    "timeline_undo": "撤销时间线动作",
    "user_message": "对话表达",
    "profile_setting": "资料设定",
    "manual_prefer": "设为常用",
    "manual_avoid": "不再推荐",
    "manual_session": "仅本次生效",
    "manual_demote": "移出长期偏好",
    "trip_signal": "规划结果学习",
    "destination_inferred": "目的地推断",
    "decision_accept": "采纳模块建议",
    "decision_ignore": "忽略模块建议",
    "itinerary_edit": "手动编辑行程",
    "railway_selection": "列车选择",
    "version_select": "查看方案版本",
    "version_rollback": "回退历史版本",
    "favorite_on": "收藏方案",
    "favorite_off": "取消收藏",
    "share_plan": "分享方案",
    "history_open": "打开历史方案",
    "continue_optimize": "继续优化",
    "legacy_profile": "历史画像",
}

UNDOABLE_SOURCE_TYPES = {
    "manual_allow",
    "manual_lock",
    "manual_unlock",
    "manual_prefer",
    "manual_avoid",
    "manual_session",
    "manual_demote",
    "version_select",
    "version_rollback",
    "favorite_on",
    "favorite_off",
    "share_plan",
    "history_open",
    "continue_optimize",
}

HALF_LIFE_DAYS = 90
MAX_EVENTS = 600


@dataclass
class PreferenceSignal:
    dimension: str
    value: str
    source_type: str
    polarity: str = "positive"
    confidence: float = 0.8
    weight: float = 1.0
    raw_text: str | None = None
    metadata: dict | None = None


class PreferenceService:
    """用户偏好画像服务，使用证据事件驱动长期画像聚合。"""

    def __init__(self, db: Session, user_key: str = "default") -> None:
        self.db = db
        self.user_key = user_key

    def get_profile(self, conversation_id: str | None = None) -> PreferenceProfileView:
        """读取聚合后的用户偏好画像。"""
        profile = self._get_or_create(commit=False)
        events = self._load_events()
        legacy_events = self._legacy_seed_events(profile)
        user = self._load_user()
        user_events = self._profile_setting_events(user)
        return self._build_profile(
            events + legacy_events + user_events,
            conversation_id=conversation_id,
        )

    def learn_from_interaction(
        self,
        message: str,
        response: dict,
        *,
        slots: dict | None = None,
        context: dict | None = None,
        conversation_id: str | None = None,
    ) -> PreferenceProfileView:
        """从用户输入、结构化上下文和行为信号中学习偏好。"""
        profile = self._get_or_create(commit=False)
        slots = slots or {}
        context = context or {}
        behavior_only = any(
            key in context
            for key in ("decision_module_action", "edited_plan", "railway_workspace_draft")
        )

        signals: list[PreferenceSignal] = []
        if not behavior_only:
            signals.extend(self._extract_from_text(message, source_type="user_message"))
            signals.extend(self._extract_trip_signals(slots, response))

        signals.extend(self._extract_behavior_signals(context))
        if not signals:
            return self.get_profile(conversation_id=conversation_id)

        return self._persist_signals(
            signals,
            profile=profile,
            conversation_id=conversation_id,
            fallback_raw_text=message,
        )

    def apply_manual_feedback(
        self,
        *,
        dimension: str,
        value: str,
        action: str | None = None,
        polarity: str | None = None,
        conversation_id: str | None = None,
    ) -> PreferenceProfileView:
        """把用户在画像工作台上的人工校正沉淀为强信号。"""
        profile = self._get_or_create(commit=False)
        normalized_dimension = self._normalize_manual_dimension(dimension)
        normalized_value = self._normalize_manual_value(normalized_dimension, value)
        if not normalized_dimension or not normalized_value:
            raise ValueError("invalid_preference_feedback")

        action_key = self._normalize_feedback_action(action, polarity)
        source_type, signal_polarity, expires_in_days = self._manual_feedback_config(action_key, polarity)
        metadata = {
            "manual_feedback": True,
            "feedback_action": action_key,
            "scope": "session" if action_key == "session_only" else "long_term",
        }
        if normalized_dimension == "budget":
            amount = self._parse_budget(normalized_value)
            if amount is not None:
                metadata["amount"] = amount
                normalized_value = f"{amount}元"

        signal = PreferenceSignal(
            dimension=normalized_dimension,
            value=normalized_value,
            source_type=source_type,
            polarity=signal_polarity,
            confidence=0.98,
            weight=SOURCE_WEIGHTS[source_type],
            raw_text=f"{normalized_dimension}:{normalized_value}",
            metadata=metadata,
        )
        return self._persist_signals(
            [signal],
            profile=profile,
            conversation_id=conversation_id,
            fallback_raw_text=normalized_value,
            expires_in_days=expires_in_days,
        )

    def record_workspace_event(
        self,
        *,
        action: str,
        conversation_id: str | None = None,
        payload: dict | None = None,
    ) -> PreferenceProfileView:
        """把前端关键行为沉淀为行为画像与偏好证据。"""

        profile = self._get_or_create(commit=False)
        action_key = self._normalize_workspace_action(action)
        if not action_key:
            raise ValueError("invalid_workspace_event")

        normalized_payload = payload if isinstance(payload, dict) else {}
        signals = self._build_workspace_event_signals(action_key, normalized_payload)
        if not signals:
            return self.get_profile(conversation_id=conversation_id)

        return self._persist_signals(
            signals,
            profile=profile,
            conversation_id=conversation_id,
            fallback_raw_text=self._build_workspace_event_fallback_text(action_key, normalized_payload),
            expires_in_days=365,
        )

    def list_timeline(
        self,
        *,
        conversation_id: str | None = None,
        limit: int = 40,
    ) -> PreferenceTimelineView:
        """返回适合前端直接渲染的画像时间线。"""

        events = self._load_events()
        selected: list[tuple[TravelPreferenceEvent, dict]] = []
        for event in events:
            metadata = self._loads_json(event.metadata_json, {})
            if event.source_type == "legacy_profile":
                continue
            if (
                conversation_id
                and event.conversation_id
                and event.conversation_id != conversation_id
                and (
                    str(metadata.get("scope") or "") == "session"
                    or event.source_type in CURRENT_CONVERSATION_TRANSIENT_SOURCES
                )
            ):
                continue
            selected.append((event, metadata))

        grouped: dict[str, list[tuple[TravelPreferenceEvent, dict]]] = {}
        order: list[str] = []
        for event, metadata in selected:
            group_key = str(metadata.get("operation_id") or f"event-{event.id}")
            if group_key not in grouped:
                grouped[group_key] = []
                order.append(group_key)
            grouped[group_key].append((event, metadata))

        items: list[PreferenceTimelineItemView] = []
        for group_key in order:
            item = self._build_timeline_item(grouped[group_key])
            if item is None:
                continue
            items.append(item)
            if len(items) >= limit:
                break

        return PreferenceTimelineView(items=items, total=len(items))

    def list_audit(
        self,
        *,
        conversation_id: str | None = None,
        limit_per_group: int = 12,
    ) -> PreferenceAuditView:
        """返回当前画像的可审计视图，便于前端按维度、来源和作用域复核。"""

        profile = self._get_or_create(commit=False)
        normalized_events = self._normalize_events(
            self._load_events() + self._legacy_seed_events(profile) + self._profile_setting_events(self._load_user())
        )
        selected = self._select_audit_events(normalized_events, conversation_id)
        locked_map = self._governance_state_map(
            selected,
            activate_source_types={"manual_lock"},
            deactivate_source_types={"manual_unlock"},
        )
        blacklist_map = self._governance_state_map(
            selected,
            activate_source_types={"manual_avoid"},
            deactivate_source_types={"manual_allow"},
        )
        items = [
            self._build_audit_item(item, locked_map=locked_map, blacklist_map=blacklist_map)
            for item in selected
        ]
        return PreferenceAuditView(
            summary=self._build_audit_summary(items, locked_map=locked_map, blacklist_map=blacklist_map),
            by_dimension=self._group_audit_items(
                items,
                key_getter=lambda item: item.dimension,
                label_getter=lambda item: item.dimension_label,
                limit_per_group=limit_per_group,
            ),
            by_source=self._group_audit_items(
                items,
                key_getter=lambda item: item.source_group,
                label_getter=lambda item: self._audit_source_group_label(item.source_group),
                limit_per_group=limit_per_group,
            ),
            by_scope=self._group_audit_items(
                items,
                key_getter=lambda item: item.scope,
                label_getter=lambda item: self._audit_scope_label(item.scope),
                limit_per_group=limit_per_group,
            ),
        )

    def undo_timeline_event(
        self,
        *,
        event_id: int,
        conversation_id: str | None = None,
        timeline_limit: int = 40,
    ) -> PreferenceTimelineUndoResultView:
        """撤销一条可撤销的画像动作，并返回最新画像与时间线。"""

        events = self._load_events()
        target = next((item for item in events if item.id == event_id), None)
        if target is None:
            raise ValueError("preference_timeline_event_not_found")

        target_metadata = self._loads_json(target.metadata_json, {})
        if target_metadata.get("undone"):
            raise ValueError("preference_timeline_event_already_undone")
        if not self._can_undo_timeline_source(target.source_type):
            raise ValueError("preference_timeline_event_cannot_undo")

        operation_id = str(target_metadata.get("operation_id") or "")
        group_events = [
            item
            for item in events
            if self._event_matches_operation(item, operation_id, fallback_event_id=target.id)
        ]
        if not group_events:
            group_events = [target]

        now = utc_now()
        for event in group_events:
            metadata = self._loads_json(event.metadata_json, {})
            metadata["undone"] = True
            metadata["undone_at"] = now.isoformat()
            metadata["undo_source"] = "user_timeline_revert"
            event.metadata_json = json.dumps(metadata, ensure_ascii=False)
            event.expires_at = now - timedelta(seconds=1)
            self.db.add(event)

        self.db.commit()
        profile = self.get_profile(conversation_id=conversation_id)
        timeline = self.list_timeline(conversation_id=conversation_id, limit=timeline_limit)
        return PreferenceTimelineUndoResultView(
            profile=profile,
            timeline=timeline,
            undone_event_id=event_id,
        )

    def _load_events(self) -> list[TravelPreferenceEvent]:
        return (
            self.db.query(TravelPreferenceEvent)
            .filter(TravelPreferenceEvent.user_key == self.user_key)
            .order_by(TravelPreferenceEvent.created_at.desc(), TravelPreferenceEvent.id.desc())
            .limit(MAX_EVENTS)
            .all()
        )

    def _persist_signals(
        self,
        signals: list[PreferenceSignal],
        *,
        profile: TravelPreferenceProfile,
        conversation_id: str | None,
        fallback_raw_text: str,
        expires_in_days: int = 365,
    ) -> PreferenceProfileView:
        """统一持久化偏好信号，并回写聚合画像快照。"""
        now = utc_now()
        operation_id = f"pref-op-{uuid4().hex[:12]}"
        for signal in signals:
            # 每次写入都附带同一个操作批次号，便于时间线分组和撤销。
            metadata = {**(signal.metadata or {}), "operation_id": operation_id}
            self.db.add(
                TravelPreferenceEvent(
                    user_key=self.user_key,
                    conversation_id=conversation_id,
                    source_type=signal.source_type,
                    dimension=signal.dimension,
                    value=signal.value[:120],
                    polarity=signal.polarity,
                    confidence=max(0.1, min(signal.confidence, 1.0)),
                    weight=max(0.1, signal.weight),
                    metadata_json=json.dumps(metadata, ensure_ascii=False),
                    raw_text=(signal.raw_text or fallback_raw_text)[:4000],
                    created_at=now,
                    expires_at=now + timedelta(days=expires_in_days),
                )
            )

        self.db.flush()
        aggregated = self._build_profile(
            self._load_events() + self._profile_setting_events(self._load_user()),
            conversation_id=conversation_id,
        )
        self._write_legacy_snapshot(profile, aggregated)
        self.db.add(profile)
        self.db.commit()
        return aggregated

    def _build_profile(
        self,
        events: list[TravelPreferenceEvent | PreferenceSignal],
        *,
        conversation_id: str | None = None,
    ) -> PreferenceProfileView:
        """同时构造长期偏好层、本次偏好层和前端可直接消费的合并画像。"""

        normalized_events = self._normalize_events(events)
        long_term_events = self._select_long_term_events(normalized_events, conversation_id)
        session_events = self._select_session_events(normalized_events, conversation_id)
        blacklist_items, locked_items = self._build_governance_views(long_term_events)

        long_term_profile = self._build_profile_layer(
            long_term_events,
            empty_hint="系统还没有沉淀出稳定的长期偏好。",
        )
        session_profile = self._build_profile_layer(
            session_events,
            empty_hint="当前会话还没有形成明确的本次偏好。",
        )
        merged_profile = self._build_profile_layer(
            long_term_events + session_events,
            empty_hint="暂无稳定偏好，系统会继续依据你的真实对话、编辑行为和方案决策自动学习。",
        )

        return PreferenceProfileView(
            preferred_cities=merged_profile.preferred_cities,
            budget_range=merged_profile.budget_range,
            transport_modes=merged_profile.transport_modes,
            pace_tags=merged_profile.pace_tags,
            interest_tags=merged_profile.interest_tags,
            negative_preferences=merged_profile.negative_preferences,
            explicit_preferences=merged_profile.explicit_preferences,
            inferred_preferences=merged_profile.inferred_preferences,
            behavior_signals=merged_profile.behavior_signals,
            profile_strength=merged_profile.profile_strength,
            budget_profile=merged_profile.budget_profile,
            recent_evidence=merged_profile.recent_evidence,
            recommendation_hint=merged_profile.recommendation_hint,
            long_term_profile=long_term_profile,
            session_profile=session_profile,
            blacklist_items=blacklist_items,
            locked_items=locked_items,
            updated_at=merged_profile.updated_at,
        )

    def _build_profile_layer(
        self,
        normalized_events: list[dict],
        *,
        empty_hint: str,
    ) -> PreferenceLayerView:
        positive_scores: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        negative_scores: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        demote_scores: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        allow_scores: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        explicit_scores: dict[str, float] = defaultdict(float)
        inferred_scores: dict[str, float] = defaultdict(float)
        behavior_scores: dict[str, float] = defaultdict(float)
        budget_amounts: list[int] = []
        budget_style_scores: dict[str, float] = defaultdict(float)
        recent_evidence: list[PreferenceEvidenceView] = []
        seen_recent: set[tuple[str, str, str, str]] = set()
        updated_at: datetime | None = None
        active_event_count = 0

        for item in normalized_events:
            score = item["score"]
            dimension = item["dimension"]
            value = item["value"]
            polarity = item["polarity"]
            label = self._event_label(dimension, value, polarity)

            if item["source_type"] == "manual_allow":
                allow_scores[dimension][value] += score
            elif item["source_type"] == "manual_unlock":
                # 解锁只改变治理状态，不直接改写正负偏好分数。
                pass
            elif polarity == "neutral":
                demote_scores[dimension][value] += score
            elif polarity == "negative":
                negative_scores[dimension][value] += score
                active_event_count += 1
            else:
                positive_scores[dimension][value] += score
                active_event_count += 1

            source_group = SOURCE_GROUPS.get(item["source_type"], "inferred")
            if polarity != "neutral":
                if source_group == "explicit":
                    explicit_scores[label] += score
                elif source_group == "behavior":
                    behavior_scores[label] += score
                else:
                    inferred_scores[label] += score

            if dimension == "budget" and item["amount"] is not None and polarity == "positive":
                budget_amounts.append(item["amount"])
            if dimension == "budget_style" and polarity != "neutral":
                budget_style_scores[value] += score

            event_key = (dimension, value, polarity, item["source_type"])
            if len(recent_evidence) < 8 and event_key not in seen_recent:
                seen_recent.add(event_key)
                recent_evidence.append(
                    PreferenceEvidenceView(
                        dimension=dimension,
                        value=value,
                        polarity=polarity,
                        source_type=item["source_type"],
                        confidence=item["confidence"],
                        weight=item["weight"],
                        created_at=item["created_at"].isoformat(),
                    )
                )

            if updated_at is None or item["created_at"] > updated_at:
                updated_at = item["created_at"]

        active_locks = self._governance_state_map(
            normalized_events,
            activate_source_types={"manual_lock"},
            deactivate_source_types={"manual_unlock"},
        )
        active_blacklist = self._governance_state_map(
            normalized_events,
            activate_source_types={"manual_avoid"},
            deactivate_source_types={"manual_allow"},
        )

        self._apply_demote_scores(positive_scores, demote_scores)
        self._apply_allow_scores(negative_scores, allow_scores)
        self._apply_demote_labels(explicit_scores, inferred_scores, behavior_scores, demote_scores)
        self._apply_allow_labels(explicit_scores, inferred_scores, behavior_scores, allow_scores)
        self._apply_lock_bonus(
            positive_scores,
            explicit_scores,
            active_locks=active_locks,
            active_blacklist=active_blacklist,
        )

        locked_pairs = set(active_locks.keys()) - set(active_blacklist.keys())
        preferred_cities = self._resolved_top_values(
            "destination",
            positive_scores,
            negative_scores,
            locked_pairs=locked_pairs,
        )
        transport_modes = self._resolved_top_values(
            "transport",
            positive_scores,
            negative_scores,
            locked_pairs=locked_pairs,
        )
        pace_tags = self._resolved_top_values(
            "pace",
            positive_scores,
            negative_scores,
            locked_pairs=locked_pairs,
        )
        interest_tags = self._resolved_top_values(
            "interest",
            positive_scores,
            negative_scores,
            locked_pairs=locked_pairs,
        )
        negative_preferences = self._top_negative_labels(negative_scores)
        explicit_preferences = self._top_labels(explicit_scores)
        inferred_preferences = self._top_labels(inferred_scores)
        behavior_signals = self._top_labels(behavior_scores)
        budget_profile = self._budget_profile(budget_amounts, budget_style_scores)
        budget_range = None
        if budget_profile and budget_profile.lower_bound and budget_profile.upper_bound:
            budget_range = f"{budget_profile.lower_bound}-{budget_profile.upper_bound}元"

        profile_strength = self._profile_strength(
            preferred_cities,
            transport_modes,
            pace_tags,
            interest_tags,
            negative_preferences,
            active_event_count,
        )
        recommendation_hint = (
            empty_hint
            if not normalized_events
            else self._hint(
                preferred_cities,
                budget_range,
                transport_modes,
                pace_tags,
                interest_tags,
                negative_preferences,
                behavior_signals,
                profile_strength,
            )
        )
        return PreferenceLayerView(
            preferred_cities=preferred_cities,
            budget_range=budget_range,
            transport_modes=transport_modes,
            pace_tags=pace_tags,
            interest_tags=interest_tags,
            negative_preferences=negative_preferences,
            explicit_preferences=explicit_preferences,
            inferred_preferences=inferred_preferences,
            behavior_signals=behavior_signals,
            profile_strength=profile_strength,
            budget_profile=budget_profile,
            recent_evidence=recent_evidence,
            recommendation_hint=recommendation_hint,
            updated_at=updated_at.isoformat() if updated_at else None,
        )

    def _normalize_events(
        self,
        events: list[TravelPreferenceEvent | PreferenceSignal],
    ) -> list[dict]:
        normalized: list[dict] = []
        now = utc_now()
        for event in events:
            if isinstance(event, PreferenceSignal):
                created_at = now
                metadata = event.metadata or {}
                source_type = event.source_type
                dimension = event.dimension
                value = event.value
                polarity = event.polarity
                confidence = event.confidence
                weight = event.weight
                conversation_id = None
                event_id = None
            else:
                expires_at = self._ensure_utc(event.expires_at) if event.expires_at else None
                if expires_at and expires_at < self._ensure_utc(now):
                    continue
                created_at = self._ensure_utc(event.created_at) if event.created_at else self._ensure_utc(now)
                metadata = self._loads_json(event.metadata_json, {})
                source_type = event.source_type
                dimension = event.dimension
                value = event.value
                polarity = event.polarity
                confidence = float(event.confidence or 0.8)
                weight = float(event.weight or 1.0)
                conversation_id = event.conversation_id
                event_id = event.id
            score = weight * confidence * self._time_decay(created_at, now)
            normalized.append(
                {
                    "event_id": event_id,
                    "dimension": dimension,
                    "value": value,
                    "polarity": polarity,
                    "source_type": source_type,
                    "confidence": confidence,
                    "weight": weight,
                    "score": score,
                    "created_at": created_at,
                    "amount": self._extract_amount(metadata),
                    "metadata": metadata,
                    "scope": str(metadata.get("scope") or ""),
                    "conversation_id": conversation_id,
                    "is_undone": bool(metadata.get("undone")),
                }
            )
        return normalized

    def _extract_from_text(self, text: str, source_type: str) -> list[PreferenceSignal]:
        lowered = self._normalize_text(text)
        signals: list[PreferenceSignal] = []
        origin_cities, route_destination_cities = self._extract_route_cities(text)

        for city in CITY_WORDS:
            if city not in text:
                continue
            # “从上海去杭州”这类表达中，上海是出发地，不应被误沉淀为偏好目的地。
            if source_type == "user_message" and city in origin_cities and city not in route_destination_cities:
                continue
            confidence = (
                0.92
                if city in route_destination_cities
                else 0.82
                if f"去{city}" in text or f"{city}怎么玩" in text
                else 0.58
            )
            signals.append(
                PreferenceSignal(
                    dimension="destination",
                    value=city,
                    source_type=source_type,
                    confidence=confidence,
                    weight=SOURCE_WEIGHTS[source_type],
                    raw_text=text,
                    metadata={"role": "destination" if city in route_destination_cities else "mentioned_city"},
                )
            )

        for value, patterns in TRANSPORT_PATTERNS.items():
            if self._contains_any(lowered, patterns):
                polarity = "negative" if self._is_transport_negative(lowered, patterns) else "positive"
                signals.append(
                    PreferenceSignal(
                        dimension="transport",
                        value=value,
                        source_type=source_type,
                        polarity=polarity,
                        confidence=0.88 if polarity == "positive" else 0.8,
                        weight=SOURCE_WEIGHTS[source_type],
                        raw_text=text,
                    )
                )

        for value, patterns in PACE_PATTERNS.items():
            if self._contains_any(lowered, patterns):
                signals.append(
                    PreferenceSignal(
                        dimension="pace",
                        value=value,
                        source_type=source_type,
                        confidence=0.83,
                        weight=SOURCE_WEIGHTS[source_type],
                        raw_text=text,
                    )
                )

        for value, patterns in INTEREST_PATTERNS.items():
            if self._contains_any(lowered, patterns) and not self._is_interest_negative(lowered, patterns, value):
                signals.append(
                    PreferenceSignal(
                        dimension="interest",
                        value=value,
                        source_type=source_type,
                        confidence=0.8,
                        weight=SOURCE_WEIGHTS[source_type],
                        raw_text=text,
                    )
                )

        for value, patterns in NEGATIVE_PATTERNS.items():
            if self._contains_any(lowered, patterns):
                signals.append(
                    PreferenceSignal(
                        dimension="avoidance",
                        value=value,
                        source_type=source_type,
                        polarity="negative",
                        confidence=0.92,
                        weight=SOURCE_WEIGHTS[source_type],
                        raw_text=text,
                    )
                )

        for value, patterns in BUDGET_STYLE_PATTERNS.items():
            if self._contains_any(lowered, patterns):
                signals.append(
                    PreferenceSignal(
                        dimension="budget_style",
                        value=value,
                        source_type=source_type,
                        confidence=0.82,
                        weight=SOURCE_WEIGHTS[source_type],
                        raw_text=text,
                    )
                )

        for amount in self._extract_budget_values(text):
            signals.append(
                PreferenceSignal(
                    dimension="budget",
                    value=f"{amount}元",
                    source_type=source_type,
                    confidence=0.96,
                    weight=SOURCE_WEIGHTS[source_type],
                    raw_text=text,
                    metadata={"amount": amount},
                )
            )
        return self._dedupe_signals(signals)

    def _extract_trip_signals(self, slots: dict, response: dict) -> list[PreferenceSignal]:
        signals: list[PreferenceSignal] = []
        destination = self._clean_text(
            slots.get("destination") or self._destination_from_cards(response.get("cards") or []),
            60,
        )
        if destination:
            signals.append(
                PreferenceSignal(
                    dimension="destination",
                    value=destination,
                    source_type="trip_signal",
                    confidence=0.7,
                    weight=SOURCE_WEIGHTS["trip_signal"],
                    raw_text=destination,
                )
            )
        budget = self._parse_budget(slots.get("budget"))
        if budget is not None:
            signals.append(
                PreferenceSignal(
                    dimension="budget",
                    value=f"{budget}元",
                    source_type="trip_signal",
                    confidence=0.88,
                    weight=SOURCE_WEIGHTS["trip_signal"],
                    raw_text=str(slots.get("budget")),
                    metadata={"amount": budget},
                )
            )
        days = self._parse_days(slots.get("days"))
        if days and days <= 2:
            signals.append(
                PreferenceSignal(
                    dimension="pace",
                    value="周末短途",
                    source_type="trip_signal",
                    confidence=0.62,
                    weight=SOURCE_WEIGHTS["trip_signal"],
                )
            )
        return signals

    def _extract_behavior_signals(self, context: dict) -> list[PreferenceSignal]:
        signals: list[PreferenceSignal] = []

        action = context.get("decision_module_action")
        module = context.get("decision_module") or {}
        if action in {"accept", "ignore"} and isinstance(module, dict):
            source_type = "decision_accept" if action == "accept" else "decision_ignore"
            polarity = "positive" if action == "accept" else "negative"
            module_type = str(module.get("type") or "")
            default_signal = MODULE_DEFAULT_SIGNALS.get(module_type)
            if default_signal:
                signals.append(
                    PreferenceSignal(
                        dimension=default_signal[0],
                        value=default_signal[1],
                        source_type=source_type,
                        polarity=polarity,
                        confidence=0.9,
                        weight=SOURCE_WEIGHTS[source_type],
                        raw_text=str(module.get("summary") or module.get("title") or ""),
                    )
                )
            combined_text = "\n".join(
                [
                    str(module.get("title") or ""),
                    str(module.get("summary") or ""),
                    "\n".join(str(item) for item in module.get("points") or []),
                ]
            )
            for signal in self._extract_from_text(combined_text, source_type=source_type):
                if signal.polarity == "positive":
                    signal.polarity = polarity
                signal.weight = SOURCE_WEIGHTS[source_type]
                signal.confidence = max(signal.confidence, 0.76)
                signals.append(signal)

        edited_plan = context.get("edited_plan")
        if isinstance(edited_plan, dict):
            edit_texts = [
                str(edited_plan.get("transport_note") or ""),
                str(edited_plan.get("budget_note") or ""),
                str(edited_plan.get("user_goal") or ""),
            ]
            itinerary = edited_plan.get("itinerary") or []
            for day in itinerary if isinstance(itinerary, list) else []:
                if not isinstance(day, dict):
                    continue
                edit_texts.append(str(day.get("title") or ""))
                for item in day.get("items") or []:
                    if not isinstance(item, dict):
                        continue
                    edit_texts.append(str(item.get("title") or ""))
                    edit_texts.append(str(item.get("detail") or ""))
            edit_text = "\n".join(part for part in edit_texts if part)
            for signal in self._extract_from_text(edit_text, source_type="itinerary_edit"):
                signal.weight = SOURCE_WEIGHTS["itinerary_edit"]
                signal.confidence = max(signal.confidence, 0.82)
                signals.append(signal)

        railway_draft = context.get("railway_workspace_draft")
        if isinstance(railway_draft, dict):
            trains = []
            for key in ("compare_trains", "candidate_trains"):
                values = railway_draft.get(key) or []
                if isinstance(values, list):
                    trains.extend(values)
            if trains:
                high_speed = 0
                start_minutes: list[int] = []
                durations: list[int] = []
                for train in trains:
                    if not isinstance(train, dict):
                        continue
                    train_no = str(train.get("train_no") or "")
                    if re.match(r"^[GDC]", train_no, re.IGNORECASE):
                        high_speed += 1
                    minutes = self._time_to_minutes(str(train.get("start_time") or ""))
                    if minutes is not None:
                        start_minutes.append(minutes)
                    duration = self._duration_to_minutes(str(train.get("duration") or ""))
                    if duration is not None:
                        durations.append(duration)
                if high_speed >= max(1, len(trains) // 2):
                    signals.append(
                        PreferenceSignal(
                            dimension="transport",
                            value="高铁",
                            source_type="railway_selection",
                            confidence=0.86,
                            weight=SOURCE_WEIGHTS["railway_selection"],
                        )
                    )
                if start_minutes and int(median(start_minutes)) >= 9 * 60:
                    signals.append(
                        PreferenceSignal(
                            dimension="behavior",
                            value="偏好九点后出发",
                            source_type="railway_selection",
                            confidence=0.8,
                            weight=SOURCE_WEIGHTS["railway_selection"],
                        )
                    )
                if durations and int(median(durations)) <= 180:
                    signals.append(
                        PreferenceSignal(
                            dimension="behavior",
                            value="偏好短耗时车次",
                            source_type="railway_selection",
                            confidence=0.78,
                            weight=SOURCE_WEIGHTS["railway_selection"],
                        )
                    )
        return self._dedupe_signals(signals)

    def _build_workspace_event_signals(
        self,
        action: str,
        payload: dict,
    ) -> list[PreferenceSignal]:
        """把前端行为事件转换为可聚合的偏好信号。"""

        signals: list[PreferenceSignal] = []
        behavior_value = self._workspace_behavior_label(action)
        if behavior_value:
            signals.append(
                PreferenceSignal(
                    dimension="behavior",
                    value=behavior_value,
                    source_type=action,
                    confidence=0.82 if action != "favorite_off" else 0.68,
                    weight=SOURCE_WEIGHTS[action],
                    raw_text=self._build_workspace_event_fallback_text(action, payload),
                    metadata={"workspace_action": action},
                )
            )

        combined_text = self._build_workspace_event_fallback_text(action, payload)
        if combined_text:
            for signal in self._extract_from_text(combined_text, source_type=action):
                signal.weight = SOURCE_WEIGHTS[action]
                signal.confidence = max(signal.confidence, 0.72)
                signal.metadata = {**(signal.metadata or {}), "workspace_action": action}
                signals.append(signal)

        budget = self._parse_budget(payload.get("budget"))
        if budget is not None and action in {"favorite_on", "share_plan", "history_open", "continue_optimize"}:
            signals.append(
                PreferenceSignal(
                    dimension="budget",
                    value=f"{budget}元",
                    source_type=action,
                    confidence=0.74,
                    weight=SOURCE_WEIGHTS[action],
                    raw_text=combined_text,
                    metadata={"amount": budget, "workspace_action": action},
                )
            )
        return self._dedupe_signals(signals)

    def _build_timeline_item(
        self,
        grouped_events: list[tuple[TravelPreferenceEvent, dict]],
    ) -> PreferenceTimelineItemView | None:
        """把同一次操作聚合成一条前端时间线记录。"""

        if not grouped_events:
            return None

        lead_event, lead_metadata = grouped_events[0]
        is_undone = any(bool(metadata.get("undone")) for _, metadata in grouped_events)
        undone_at = next(
            (
                str(metadata.get("undone_at"))
                for _, metadata in grouped_events
                if metadata.get("undone_at")
            ),
            None,
        )
        scope = self._timeline_scope(lead_event, lead_metadata)
        return PreferenceTimelineItemView(
            id=lead_event.id,
            title=self._timeline_title(lead_event, lead_metadata),
            description=self._timeline_description(lead_event, lead_metadata, grouped_events, scope, is_undone),
            dimension=lead_event.dimension,
            value=lead_event.value,
            polarity=lead_event.polarity,
            source_type=lead_event.source_type,
            source_label=TIMELINE_SOURCE_LABELS.get(lead_event.source_type, lead_event.source_type),
            scope=scope,
            signal_count=len(grouped_events),
            conversation_id=lead_event.conversation_id,
            can_undo=not is_undone and self._can_undo_timeline_source(lead_event.source_type),
            is_undone=is_undone,
            created_at=self._ensure_utc(lead_event.created_at).isoformat(),
            undone_at=undone_at,
        )

    def _timeline_scope(self, event: TravelPreferenceEvent, metadata: dict) -> str:
        if str(metadata.get("scope") or "") == "session" or event.source_type in SESSION_SCOPED_SOURCE_TYPES:
            return "session"
        if event.source_type in CURRENT_CONVERSATION_TRANSIENT_SOURCES and event.conversation_id:
            return "session"
        if event.source_type in {
            "favorite_on",
            "favorite_off",
            "share_plan",
            "history_open",
            "version_select",
            "version_rollback",
            "memory_open",
            "audit_open",
            "governance_open",
            "blacklist_remove",
            "profile_lock",
            "profile_unlock",
            "timeline_undo",
        }:
            return "behavior"
        return "long_term"

    def _timeline_title(self, event: TravelPreferenceEvent, metadata: dict) -> str:
        value = self._timeline_display_value(event.dimension, event.value)
        manual_action = str(metadata.get("feedback_action") or "")
        workspace_action = str(metadata.get("workspace_action") or "")

        if manual_action == "set_common" or event.source_type == "manual_prefer":
            return f"设为常用偏好 · {value}"
        if manual_action == "session_only" or event.source_type == "manual_session":
            return f"{'仅本次避让' if event.polarity == 'negative' else '仅本次生效'} · {value}"
        if manual_action == "avoid" or event.source_type == "manual_avoid":
            return f"不再推荐 · {value}"
        if manual_action == "remove_long_term" or event.source_type == "manual_demote":
            return f"移出长期偏好 · {value}"
        if workspace_action or event.source_type in UNDOABLE_SOURCE_TYPES:
            if manual_action == "remove_avoid" or event.source_type == "manual_allow":
                return f"移除黑名单 路 {value}"
            if manual_action == "lock_long_term" or event.source_type == "manual_lock":
                return f"锁定长期偏好 路 {value}"
            if manual_action == "unlock_long_term" or event.source_type == "manual_unlock":
                return f"解除长期锁定 路 {value}"
            action_key = workspace_action or event.source_type
            if action_key == "favorite_on":
                return f"收藏方案 · {self._timeline_title_suffix(metadata, '收藏内容')}"
            if action_key == "favorite_off":
                return f"取消收藏 · {self._timeline_title_suffix(metadata, '收藏内容')}"
            if action_key == "share_plan":
                return f"分享方案 · {self._timeline_title_suffix(metadata, '当前方案')}"
            if action_key == "history_open":
                return f"打开历史方案 · {self._timeline_title_suffix(metadata, '历史方案')}"
            if action_key == "version_rollback":
                return f"回退版本 · {self._timeline_title_suffix(metadata, '历史版本')}"
            if action_key == "version_select":
                return f"查看版本 · {self._timeline_title_suffix(metadata, '方案版本')}"
            if action_key == "continue_optimize":
                return "继续优化当前方案"
        if event.polarity == "negative":
            if workspace_action == "memory_open" or event.source_type == "memory_open":
                return "打开偏好画像中心"
            if workspace_action == "audit_open" or event.source_type == "audit_open":
                return "打开画像审计视图"
            if workspace_action == "governance_open" or event.source_type == "governance_open":
                return "打开偏好治理面板"
            if workspace_action == "blacklist_remove" or event.source_type == "blacklist_remove":
                return f"行为移除黑名单 路 {self._timeline_title_suffix(metadata, value)}"
            if workspace_action == "profile_lock" or event.source_type == "profile_lock":
                return f"行为锁定偏好 路 {self._timeline_title_suffix(metadata, value)}"
            if workspace_action == "profile_unlock" or event.source_type == "profile_unlock":
                return f"行为解除锁定 路 {self._timeline_title_suffix(metadata, value)}"
            if workspace_action == "timeline_undo" or event.source_type == "timeline_undo":
                return "撤销画像学习动作"
            return f"识别到避让偏好 · {value}"
        if event.polarity == "neutral":
            return f"偏好降权 · {value}"
        return f"{self._timeline_dimension_label(event.dimension)} · {value}"

    def _timeline_description(
        self,
        event: TravelPreferenceEvent,
        metadata: dict,
        grouped_events: list[tuple[TravelPreferenceEvent, dict]],
        scope: str,
        is_undone: bool,
    ) -> str:
        parts: list[str] = []
        if scope == "session":
            parts.append("仅影响当前会话")
        elif scope == "behavior":
            parts.append("来自真实操作行为")
        else:
            parts.append("会进入长期偏好学习")

        destination = self._clean_text(metadata.get("destination_city"), 40)
        if destination:
            parts.append(destination)
        budget = self._parse_budget(metadata.get("budget"))
        if budget is not None:
            parts.append(f"预算 {budget} 元")
        title = self._clean_text(metadata.get("title"), 80)
        version_name = self._clean_text(metadata.get("version_name"), 80)
        if version_name and version_name != title:
            parts.append(version_name)
        elif title:
            parts.append(title)
        if len(grouped_events) > 1:
            parts.append(f"影响 {len(grouped_events)} 条画像信号")
        if is_undone:
            parts.append("已撤销，不再参与后续推荐")
        summary = self._clean_text(metadata.get("summary"), 160)
        if summary:
            parts.append(summary)
        return " · ".join(part for part in parts if part)

    def _timeline_display_value(self, dimension: str, value: str) -> str:
        if dimension == "avoidance":
            return value.replace("避免", "").strip()
        return value

    def _timeline_title_suffix(self, metadata: dict, fallback: str) -> str:
        return (
            self._clean_text(metadata.get("title"), 60)
            or self._clean_text(metadata.get("version_name"), 60)
            or self._clean_text(metadata.get("destination_city"), 30)
            or fallback
        )

    def _timeline_dimension_label(self, dimension: str) -> str:
        mapping = {
            "destination": "目的地偏好",
            "transport": "交通偏好",
            "pace": "旅行节奏",
            "interest": "兴趣主题",
            "avoidance": "避让偏好",
            "budget": "预算偏好",
            "budget_style": "预算风格",
            "behavior": "行为信号",
            "risk": "风险偏好",
        }
        return mapping.get(dimension, dimension)

    def _can_undo_timeline_source(self, source_type: str) -> bool:
        return source_type in UNDOABLE_SOURCE_TYPES

    def _event_matches_operation(
        self,
        event: TravelPreferenceEvent,
        operation_id: str,
        *,
        fallback_event_id: int,
    ) -> bool:
        if operation_id:
            metadata = self._loads_json(event.metadata_json, {})
            return str(metadata.get("operation_id") or "") == operation_id
        return event.id == fallback_event_id

    def _select_long_term_events(
        self,
        normalized_events: list[dict],
        conversation_id: str | None,
    ) -> list[dict]:
        """长期层默认排除会话级事件，并在查看当前会话时避开本轮瞬时偏好。"""

        selected: list[dict] = []
        for item in normalized_events:
            if item["scope"] == "session" or item["source_type"] in SESSION_SCOPED_SOURCE_TYPES:
                continue
            if (
                conversation_id
                and item["conversation_id"] == conversation_id
                and item["source_type"] in CURRENT_CONVERSATION_TRANSIENT_SOURCES
            ):
                continue
            selected.append(item)
        return selected

    def _select_session_events(
        self,
        normalized_events: list[dict],
        conversation_id: str | None,
    ) -> list[dict]:
        """本次层优先围绕当前会话构建，也兼容只有临时纠偏时的场景。"""

        now = utc_now()
        selected: list[dict] = []
        for item in normalized_events:
            is_session_scope = item["scope"] == "session" or item["source_type"] in SESSION_SCOPED_SOURCE_TYPES
            if conversation_id:
                if item["conversation_id"] == conversation_id:
                    selected.append(item)
                    continue
                if is_session_scope and item["conversation_id"] in {None, conversation_id}:
                    selected.append(item)
                continue
            if not is_session_scope:
                continue
            if (self._ensure_utc(now) - item["created_at"]).total_seconds() <= 7 * 86400:
                selected.append(item)
        return selected

    def _apply_demote_scores(
        self,
        positive_scores: dict[str, dict[str, float]],
        demote_scores: dict[str, dict[str, float]],
    ) -> None:
        """“这不是我的长期偏好”只削弱长期正向偏好，不把它直接改成避让。"""

        for dimension, mapping in demote_scores.items():
            positives = positive_scores.get(dimension, {})
            for value, score in mapping.items():
                if value not in positives:
                    continue
                remaining = positives[value] - score * 1.15
                if remaining <= 0.12:
                    positives.pop(value, None)
                else:
                    positives[value] = remaining

    def _apply_demote_labels(
        self,
        explicit_scores: dict[str, float],
        inferred_scores: dict[str, float],
        behavior_scores: dict[str, float],
        demote_scores: dict[str, dict[str, float]],
    ) -> None:
        for dimension, mapping in demote_scores.items():
            for value, score in mapping.items():
                label = self._event_label(dimension, value, "positive")
                for bucket in (explicit_scores, inferred_scores, behavior_scores):
                    if label not in bucket:
                        continue
                    remaining = bucket[label] - score * 1.15
                    if remaining <= 0.12:
                        bucket.pop(label, None)
                    else:
                        bucket[label] = remaining

    def _apply_allow_scores(
        self,
        negative_scores: dict[str, dict[str, float]],
        allow_scores: dict[str, dict[str, float]],
    ) -> None:
        """把“移除黑名单”动作作用到负向偏好分数上。"""

        for dimension, mapping in allow_scores.items():
            negatives = negative_scores.get(dimension, {})
            for value, score in mapping.items():
                if value not in negatives:
                    continue
                remaining = negatives[value] - score * 1.12
                if remaining <= 0.12:
                    negatives.pop(value, None)
                else:
                    negatives[value] = remaining

    def _apply_allow_labels(
        self,
        explicit_scores: dict[str, float],
        inferred_scores: dict[str, float],
        behavior_scores: dict[str, float],
        allow_scores: dict[str, dict[str, float]],
    ) -> None:
        for dimension, mapping in allow_scores.items():
            for value, score in mapping.items():
                label = self._event_label(dimension, value, "negative")
                for bucket in (explicit_scores, inferred_scores, behavior_scores):
                    if label not in bucket:
                        continue
                    remaining = bucket[label] - score * 1.12
                    if remaining <= 0.12:
                        bucket.pop(label, None)
                    else:
                        bucket[label] = remaining

    def _apply_lock_bonus(
        self,
        positive_scores: dict[str, dict[str, float]],
        explicit_scores: dict[str, float],
        *,
        active_locks: dict[tuple[str, str], dict],
        active_blacklist: dict[tuple[str, str], dict],
    ) -> None:
        """长期锁定会在聚合阶段给稳定偏好一个保留权重。"""

        for key, state in active_locks.items():
            if key in active_blacklist:
                continue
            dimension, value = key
            bonus = max(1.25, float(state.get("score") or 0.0) * 0.82)
            positive_scores[dimension][value] += bonus
            explicit_scores[self._event_label(dimension, value, "positive")] += bonus

    def _build_governance_views(
        self,
        normalized_events: list[dict],
    ) -> tuple[list[PreferenceGovernanceItemView], list[PreferenceGovernanceItemView]]:
        blacklist_map = self._governance_state_map(
            normalized_events,
            activate_source_types={"manual_avoid"},
            deactivate_source_types={"manual_allow"},
        )
        locked_map = self._governance_state_map(
            normalized_events,
            activate_source_types={"manual_lock"},
            deactivate_source_types={"manual_unlock"},
        )
        blacklist_items = self._governance_items_from_state(blacklist_map, kind="blacklist")
        locked_items = self._governance_items_from_state(
            {key: value for key, value in locked_map.items() if key not in blacklist_map},
            kind="lock",
        )
        return blacklist_items, locked_items

    def _governance_state_map(
        self,
        normalized_events: list[dict],
        *,
        activate_source_types: set[str],
        deactivate_source_types: set[str],
    ) -> dict[tuple[str, str], dict]:
        """按最新事件推导某类治理状态是否仍然生效。"""

        state: dict[tuple[str, str], dict] = {}
        ordered = sorted(
            normalized_events,
            key=lambda item: (item["created_at"], item.get("event_id") or 0),
        )
        for item in ordered:
            source_type = item["source_type"]
            if source_type not in activate_source_types | deactivate_source_types:
                continue
            key = (item["dimension"], item["value"])
            if source_type in activate_source_types:
                state[key] = item
            else:
                state.pop(key, None)
        return state

    def _governance_items_from_state(
        self,
        state_map: dict[tuple[str, str], dict],
        *,
        kind: str,
    ) -> list[PreferenceGovernanceItemView]:
        items: list[PreferenceGovernanceItemView] = []
        for (dimension, value), item in sorted(
            state_map.items(),
            key=lambda pair: pair[1]["created_at"],
            reverse=True,
        ):
            label = (
                f"避免{self._timeline_display_value(dimension, value)}"
                if kind == "blacklist"
                else self._timeline_display_value(dimension, value)
            )
            items.append(
                PreferenceGovernanceItemView(
                    dimension=dimension,
                    value=value,
                    label=label,
                    source_type=item["source_type"],
                    created_at=item["created_at"].isoformat(),
                    note=self._audit_event_note(item),
                )
            )
        return items

    def _select_audit_events(
        self,
        normalized_events: list[dict],
        conversation_id: str | None,
    ) -> list[dict]:
        """审计视图需要同时看到长期层和当前会话层。"""

        selected: list[dict] = []
        seen: set[tuple[str | None, str, str, str, str]] = set()
        for item in self._select_session_events(normalized_events, conversation_id) + self._select_long_term_events(
            normalized_events,
            conversation_id,
        ):
            item_key = (
                item.get("event_id"),
                item["source_type"],
                item["dimension"],
                item["value"],
                item["created_at"].isoformat(),
            )
            if item_key in seen:
                continue
            seen.add(item_key)
            selected.append(item)
        return sorted(selected, key=lambda item: (item["created_at"], item["score"]), reverse=True)

    def _build_audit_item(
        self,
        item: dict,
        *,
        locked_map: dict[tuple[str, str], dict],
        blacklist_map: dict[tuple[str, str], dict],
    ) -> PreferenceAuditItemView:
        key = (item["dimension"], item["value"])
        scope = self._audit_scope(item)
        return PreferenceAuditItemView(
            id=item.get("event_id"),
            dimension=item["dimension"],
            dimension_label=self._timeline_dimension_label(item["dimension"]),
            value=item["value"],
            display_value=self._timeline_display_value(item["dimension"], item["value"]),
            polarity=item["polarity"],
            source_type=item["source_type"],
            source_label=TIMELINE_SOURCE_LABELS.get(item["source_type"], item["source_type"]),
            source_group=SOURCE_GROUPS.get(item["source_type"], "inferred"),
            scope=scope,
            score=round(float(item["score"]), 4),
            confidence=round(float(item["confidence"]), 4),
            weight=round(float(item["weight"]), 4),
            created_at=item["created_at"].isoformat(),
            conversation_id=item.get("conversation_id"),
            is_locked=key in locked_map and key not in blacklist_map,
            is_blacklisted=key in blacklist_map,
            is_undone=bool(item.get("is_undone")),
            note=self._audit_event_note(item),
        )

    def _build_audit_summary(
        self,
        items: list[PreferenceAuditItemView],
        *,
        locked_map: dict[tuple[str, str], dict],
        blacklist_map: dict[tuple[str, str], dict],
    ) -> PreferenceAuditSummaryView:
        explicit_total = sum(1 for item in items if item.source_group == "explicit")
        inferred_total = sum(1 for item in items if item.source_group == "inferred")
        behavior_total = sum(1 for item in items if item.source_group == "behavior")
        session_total = sum(1 for item in items if item.scope == "session")
        long_term_total = sum(1 for item in items if item.scope == "long_term")
        return PreferenceAuditSummaryView(
            total_events=len(items),
            explicit_total=explicit_total,
            inferred_total=inferred_total,
            behavior_total=behavior_total,
            session_total=session_total,
            long_term_total=long_term_total,
            locked_total=len(locked_map),
            blacklist_total=len(blacklist_map),
        )

    def _group_audit_items(
        self,
        items: list[PreferenceAuditItemView],
        *,
        key_getter,
        label_getter,
        limit_per_group: int,
    ) -> list[PreferenceAuditGroupView]:
        grouped: dict[str, list[PreferenceAuditItemView]] = defaultdict(list)
        order: list[str] = []
        for item in items:
            key = str(key_getter(item))
            if key not in grouped:
                order.append(key)
            grouped[key].append(item)
        result: list[PreferenceAuditGroupView] = []
        for key in order:
            bucket_items = grouped[key]
            label = str(label_getter(bucket_items[0])) if bucket_items else key
            result.append(
                PreferenceAuditGroupView(
                    key=key,
                    label=label,
                    total=len(bucket_items),
                    items=bucket_items[:limit_per_group],
                )
            )
        return result

    def _audit_scope(self, item: dict) -> str:
        if item["scope"] == "session" or item["source_type"] in SESSION_SCOPED_SOURCE_TYPES:
            return "session"
        if item["source_type"] in {
            "favorite_on",
            "favorite_off",
            "share_plan",
            "history_open",
            "version_select",
            "version_rollback",
            "continue_optimize",
            "memory_open",
            "audit_open",
            "governance_open",
            "blacklist_remove",
            "profile_lock",
            "profile_unlock",
            "timeline_undo",
        }:
            return "behavior"
        return "long_term"

    def _audit_source_group_label(self, source_group: str) -> str:
        mapping = {
            "explicit": "显式设定",
            "behavior": "行为学习",
            "inferred": "模型推断",
        }
        return mapping.get(source_group, source_group)

    def _audit_scope_label(self, scope: str) -> str:
        mapping = {
            "session": "本次会话",
            "behavior": "行为侧",
            "long_term": "长期记忆",
        }
        return mapping.get(scope, scope)

    def _audit_event_note(self, item: dict) -> str | None:
        metadata = item.get("metadata") or {}
        return (
            self._clean_text(metadata.get("summary"), 180)
            or self._clean_text(metadata.get("title"), 120)
            or self._clean_text(metadata.get("version_name"), 120)
        )

    def _manual_feedback_config(self, action: str, polarity_hint: str | None = None) -> tuple[str, str, int]:
        mapping = {
            "set_common": ("manual_prefer", "positive", 365 * 3),
            "session_only": ("manual_session", "negative" if polarity_hint == "negative" else "positive", 3),
            "avoid": ("manual_avoid", "negative", 365 * 3),
            "remove_long_term": ("manual_demote", "neutral", 365 * 3),
            "remove_avoid": ("manual_allow", "neutral", 365 * 3),
            "lock_long_term": ("manual_lock", "positive", 365 * 5),
            "unlock_long_term": ("manual_unlock", "neutral", 365 * 5),
        }
        if action not in mapping:
            raise ValueError("invalid_preference_feedback")
        return mapping[action]

    def _normalize_feedback_action(self, action: str | None, polarity: str | None) -> str:
        if action:
            return action
        if polarity == "positive":
            return "set_common"
        if polarity == "negative":
            return "avoid"
        raise ValueError("invalid_preference_feedback")

    def _normalize_workspace_action(self, action: str) -> str | None:
        allowed = {
            "version_select",
            "version_rollback",
            "favorite_on",
            "favorite_off",
            "share_plan",
            "history_open",
            "continue_optimize",
            "memory_open",
            "audit_open",
            "governance_open",
            "blacklist_remove",
            "profile_lock",
            "profile_unlock",
            "timeline_undo",
        }
        normalized = str(action or "").strip().lower()
        return normalized if normalized in allowed else None

    def _workspace_behavior_label(self, action: str) -> str:
        mapping = {
            "memory_open": "会进入画像中心复核长期记忆",
            "audit_open": "会主动打开画像审计视图",
            "governance_open": "会整理黑名单和锁定项",
            "blacklist_remove": "会从黑名单中恢复候选偏好",
            "profile_lock": "会锁定长期偏好",
            "profile_unlock": "会解除长期偏好锁定",
            "timeline_undo": "会撤销画像学习动作",
            "version_select": "会回看多版本方案",
            "version_rollback": "偏好从历史版本继续优化",
            "favorite_on": "会收藏重点方案",
            "favorite_off": "会主动清理收藏",
            "share_plan": "愿意分享成熟方案",
            "history_open": "常从历史方案继续优化",
            "continue_optimize": "偏好二次优化与精修",
        }
        return mapping.get(action, action)

    def _build_workspace_event_fallback_text(self, action: str, payload: dict) -> str:
        parts = [
            self._workspace_behavior_label(action),
            self._clean_text(payload.get("title"), 160) if isinstance(payload, dict) else None,
            self._clean_text(payload.get("summary"), 400) if isinstance(payload, dict) else None,
            self._clean_text(payload.get("destination_city"), 60) if isinstance(payload, dict) else None,
            self._clean_text(payload.get("start_date"), 40) if isinstance(payload, dict) else None,
            self._clean_text(payload.get("version_name"), 80) if isinstance(payload, dict) else None,
            self._clean_text(payload.get("reason"), 200) if isinstance(payload, dict) else None,
        ]
        if isinstance(payload, dict):
            tags = payload.get("tags") or []
            if isinstance(tags, list):
                parts.extend(self._clean_text(item, 40) for item in tags[:8])
            budget = self._parse_budget(payload.get("budget"))
            if budget is not None:
                parts.append(f"预算 {budget} 元")
        return "\n".join(str(part) for part in parts if part)

    def _profile_setting_events(self, user: User | None) -> list[PreferenceSignal]:
        if user is None or not user.travel_style:
            return []
        return self._extract_from_text(user.travel_style, source_type="profile_setting")

    def _legacy_seed_events(self, profile: TravelPreferenceProfile) -> list[PreferenceSignal]:
        events: list[PreferenceSignal] = []
        for value, score in self._loads_dict(profile.preferred_cities_json).items():
            events.append(
                PreferenceSignal(
                    dimension="destination",
                    value=value,
                    source_type="legacy_profile",
                    confidence=0.75,
                    weight=min(float(score), 3.0),
                )
            )
        for value, score in self._loads_dict(profile.transport_modes_json).items():
            events.append(
                PreferenceSignal(
                    dimension="transport",
                    value=value,
                    source_type="legacy_profile",
                    confidence=0.74,
                    weight=min(float(score), 3.0),
                )
            )
        for value, score in self._loads_dict(profile.pace_tags_json).items():
            events.append(
                PreferenceSignal(
                    dimension="pace",
                    value=value,
                    source_type="legacy_profile",
                    confidence=0.72,
                    weight=min(float(score), 3.0),
                )
            )
        for value, score in self._loads_dict(profile.interest_tags_json).items():
            events.append(
                PreferenceSignal(
                    dimension="interest",
                    value=value,
                    source_type="legacy_profile",
                    confidence=0.72,
                    weight=min(float(score), 3.0),
                )
            )
        for amount in self._loads_list(profile.budget_values_json):
            events.append(
                PreferenceSignal(
                    dimension="budget",
                    value=f"{amount}元",
                    source_type="legacy_profile",
                    confidence=0.7,
                    weight=0.65,
                    metadata={"amount": amount},
                )
            )
        return events

    def _write_legacy_snapshot(
        self,
        profile: TravelPreferenceProfile,
        aggregated: PreferenceProfileView,
    ) -> None:
        # 旧快照只保留长期层，避免把“仅本次生效”的临时偏好回灌成长期画像。
        snapshot = aggregated.long_term_profile or aggregated
        profile.preferred_cities_json = json.dumps(
            {value: index + 1 for index, value in enumerate(snapshot.preferred_cities)},
            ensure_ascii=False,
        )
        profile.transport_modes_json = json.dumps(
            {value: index + 1 for index, value in enumerate(snapshot.transport_modes)},
            ensure_ascii=False,
        )
        profile.pace_tags_json = json.dumps(
            {value: index + 1 for index, value in enumerate(snapshot.pace_tags)},
            ensure_ascii=False,
        )
        profile.interest_tags_json = json.dumps(
            {value: index + 1 for index, value in enumerate(snapshot.interest_tags)},
            ensure_ascii=False,
        )
        budget_values = [
            item.median
            for item in [snapshot.budget_profile]
            if item and item.median is not None
        ]
        profile.budget_values_json = json.dumps(budget_values, ensure_ascii=False)
        profile.updated_at = utc_now()

    def _get_or_create(self, commit: bool = True) -> TravelPreferenceProfile:
        profile = self.db.get(TravelPreferenceProfile, self.user_key)
        if profile:
            return profile
        profile = TravelPreferenceProfile(user_key=self.user_key)
        self.db.add(profile)
        if commit:
            self.db.commit()
            self.db.refresh(profile)
        return profile

    def _load_user(self) -> User | None:
        try:
            user_id = int(self.user_key)
        except (TypeError, ValueError):
            return None
        return self.db.get(User, user_id)

    def _loads_dict(self, value: str | None) -> dict[str, float]:
        data = self._loads_json(value, {})
        result: dict[str, float] = {}
        for key, count in data.items():
            try:
                result[str(key)] = float(count)
            except (TypeError, ValueError):
                continue
        return result

    def _loads_list(self, value: str | None) -> list[int]:
        data = self._loads_json(value, [])
        result: list[int] = []
        for item in data:
            try:
                result.append(int(item))
            except (TypeError, ValueError):
                continue
        return result

    def _loads_json(self, value: str | None, fallback):
        try:
            return json.loads(value or json.dumps(fallback, ensure_ascii=False))
        except (TypeError, ValueError, json.JSONDecodeError):
            return fallback

    def _top_values(self, scores: dict[str, float], limit: int = 5) -> list[str]:
        return [key for key, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)[:limit]]

    def _resolved_top_values(
        self,
        dimension: str,
        positive_scores: dict[str, dict[str, float]],
        negative_scores: dict[str, dict[str, float]],
        locked_pairs: set[tuple[str, str]] | None = None,
        limit: int = 5,
    ) -> list[str]:
        resolved: list[tuple[str, float]] = []
        locked_pairs = locked_pairs or set()
        positives = positive_scores.get(dimension, {})
        negatives = negative_scores.get(dimension, {})
        for value, score in positives.items():
            negative_score = negatives.get(value, 0.0)
            is_locked = (dimension, value) in locked_pairs
            if negative_score >= score * 0.9 and not is_locked:
                continue
            penalty = negative_score * (0.18 if is_locked else 0.35)
            boost = 1.05 if is_locked else 0.0
            resolved.append((value, score - penalty + boost))
        return [value for value, _ in sorted(resolved, key=lambda item: item[1], reverse=True)[:limit]]

    def _top_labels(self, scores: dict[str, float], limit: int = 6) -> list[str]:
        return [key for key, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)[:limit]]

    def _top_negative_labels(
        self,
        scores: dict[str, dict[str, float]],
        limit: int = 5,
    ) -> list[str]:
        flattened: list[tuple[str, float]] = []
        for dimension, mapping in scores.items():
            for value, score in mapping.items():
                flattened.append((self._event_label(dimension, value, "negative"), score))
        return [label for label, _ in sorted(flattened, key=lambda item: item[1], reverse=True)[:limit]]

    def _budget_profile(
        self,
        budget_amounts: list[int],
        style_scores: dict[str, float],
    ) -> BudgetProfileView | None:
        if not budget_amounts and not style_scores:
            return None

        median_value = int(median(budget_amounts)) if budget_amounts else None
        lower_bound = None
        upper_bound = None
        if median_value is not None:
            spread = 300
            if len(budget_amounts) >= 3:
                ordered = sorted(budget_amounts)
                spread = max(200, int((ordered[-1] - ordered[0]) / 2))
            lower_bound = max(100, median_value - spread)
            upper_bound = median_value + spread

        sensitivity = None
        if style_scores:
            top_style = max(style_scores.items(), key=lambda item: item[1])[0]
            sensitivity = "高" if top_style == "预算敏感" else "低"
        elif median_value is not None:
            sensitivity = "高" if median_value <= 1500 else "中" if median_value <= 3000 else "低"

        return BudgetProfileView(
            median=median_value,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            sensitivity=sensitivity,
        )

    def _profile_strength(
        self,
        preferred_cities: list[str],
        transport_modes: list[str],
        pace_tags: list[str],
        interest_tags: list[str],
        negative_preferences: list[str],
        event_count: int,
    ) -> str:
        signal_count = (
            len(preferred_cities)
            + len(transport_modes)
            + len(pace_tags)
            + len(interest_tags)
            + len(negative_preferences)
        )
        if signal_count >= 10 or event_count >= 18:
            return "strong"
        if signal_count >= 5 or event_count >= 8:
            return "growing"
        return "new"

    def _hint(
        self,
        cities: list[str],
        budget_range: str | None,
        transports: list[str],
        pace: list[str],
        interests: list[str],
        negative_preferences: list[str],
        behavior_signals: list[str],
        profile_strength: str,
    ) -> str:
        parts: list[str] = []
        if cities:
            parts.append(f"偏好城市：{'、'.join(cities[:3])}")
        if budget_range:
            parts.append(f"常用预算：{budget_range}")
        if transports:
            parts.append(f"交通偏好：{'、'.join(transports[:3])}")
        if pace:
            parts.append(f"旅行节奏：{'、'.join(pace[:3])}")
        if interests:
            parts.append(f"兴趣偏好：{'、'.join(interests[:3])}")
        if negative_preferences:
            parts.append(f"明确避让：{'、'.join(negative_preferences[:2])}")
        if behavior_signals:
            parts.append(f"行为信号：{'、'.join(behavior_signals[:2])}")
        if not parts:
            return "暂无稳定偏好，系统会继续依据你的真实对话、编辑行为和决策采纳结果自动沉淀。"
        strength_label = {"new": "画像初步形成", "growing": "画像逐渐稳定", "strong": "画像较稳定"}.get(
            profile_strength,
            "画像逐渐稳定",
        )
        return f"{strength_label}；" + "；".join(parts)

    def _event_label(self, dimension: str, value: str, polarity: str) -> str:
        if polarity == "negative":
            return f"避免{value}"
        if dimension == "budget_style" and value == "预算敏感":
            return "预算敏感"
        if dimension == "budget_style" and value == "体验优先":
            return "体验优先"
        return value

    def _extract_amount(self, metadata: dict | None) -> int | None:
        if not isinstance(metadata, dict):
            return None
        amount = metadata.get("amount")
        try:
            return int(amount) if amount is not None else None
        except (TypeError, ValueError):
            return None

    def _contains_any(self, text: str, patterns: list[str]) -> bool:
        return any(pattern.lower() in text for pattern in patterns)

    def _extract_route_cities(self, text: str) -> tuple[set[str], set[str]]:
        """识别“从 A 去/到 B”中的出发地和目的地，避免把出发地写入目的地画像。"""
        normalized = re.sub(r"\s+", "", str(text or ""))
        origins: set[str] = set()
        destinations: set[str] = set()
        city_group = "|".join(re.escape(city) for city in CITY_WORDS)
        route_patterns = (
            rf"从(?P<origin>.{{0,8}}?(?:{city_group}).{{0,4}}?)(?:出发)?(?:去|到|前往|游玩|玩)(?P<destination>.{{0,8}}?(?:{city_group}).{{0,8}}?)",
            rf"(?P<origin>{city_group})(?:出发)?(?:去|到|前往)(?P<destination>.{{0,8}}?(?:{city_group}).{{0,8}}?)",
        )
        for pattern in route_patterns:
            for match in re.finditer(pattern, normalized):
                origin_city = self._first_city_in_text(match.group("origin"))
                destination_city = self._first_city_in_text(match.group("destination"))
                if origin_city and destination_city and origin_city != destination_city:
                    origins.add(origin_city)
                    destinations.add(destination_city)
        return origins, destinations

    def _first_city_in_text(self, text: str) -> str | None:
        """按文本出现位置返回第一个城市名。"""
        ranked = [(str(text).find(city), city) for city in CITY_WORDS if city in str(text)]
        ranked = [item for item in ranked if item[0] >= 0]
        if not ranked:
            return None
        return sorted(ranked, key=lambda item: item[0])[0][1]

    def _is_interest_negative(self, text: str, patterns: list[str], value: str) -> bool:
        """识别“不想徒步/少爬山”等否定兴趣，避免误加正向自然偏好。"""
        cues = [pattern.lower() for pattern in patterns]
        if value == "自然":
            cues.extend(["爬山", "登山", "徒步", "山路"])
        negative_prefixes = ("不要", "不想", "别", "少", "减少", "避免", "不安排", "别安排", "别安排太多")
        for cue in cues:
            for prefix in negative_prefixes:
                if f"{prefix}{cue}" in text:
                    return True
        return False

    def _is_transport_negative(self, text: str, patterns: list[str]) -> bool:
        negative_prefixes = ("不要", "不坐", "别坐", "不想坐", "避免")
        for pattern in patterns:
            for prefix in negative_prefixes:
                if f"{prefix}{pattern.lower()}" in text:
                    return True
        return False

    def _dedupe_signals(self, signals: list[PreferenceSignal]) -> list[PreferenceSignal]:
        result: list[PreferenceSignal] = []
        seen: set[tuple[str, str, str, str]] = set()
        for signal in signals:
            key = (signal.dimension, signal.value, signal.polarity, signal.source_type)
            if key in seen:
                continue
            seen.add(key)
            result.append(signal)
        return result

    def _normalize_text(self, text: str) -> str:
        return str(text or "").replace("　", " ").strip().lower()

    def _extract_budget_values(self, text: str) -> list[int]:
        values: list[int] = []
        for left, right in re.findall(r"([0-9]{2,6})\s*[-~到]\s*([0-9]{2,6})", text):
            values.append(int((int(left) + int(right)) / 2))
        for value in re.findall(r"(?:预算\s*)?([0-9]{2,6})\s*元", text):
            values.append(int(value))
        # 兼容“预算2000左右/预算 2000 上下”这类没有写“元”的自然表达。
        for value in re.findall(r"预算\s*([0-9]{2,6})\s*(?:左右|上下|以内|以下|预算内)?", text):
            values.append(int(value))
        return list(dict.fromkeys(values))

    def _destination_from_cards(self, cards: list[dict]) -> str | None:
        for card in cards:
            if isinstance(card, dict) and card.get("type") == "destination" and card.get("title"):
                return self._clean_text(card["title"], 60)
        return None

    def _parse_budget(self, raw_value) -> int | None:
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

    def _time_decay(self, created_at: datetime, now: datetime) -> float:
        created = self._ensure_utc(created_at)
        current = self._ensure_utc(now)
        days = max(0.0, (current - created).total_seconds() / 86400)
        return 0.5 ** (days / HALF_LIFE_DAYS)

    def _time_to_minutes(self, value: str) -> int | None:
        if not value or ":" not in value:
            return None
        try:
            hours, minutes = value.split(":", 1)
            return int(hours) * 60 + int(minutes)
        except (TypeError, ValueError):
            return None

    def _duration_to_minutes(self, value: str) -> int | None:
        if not value:
            return None
        match = re.search(r"(?:(\d+)\s*小时)?(?:(\d+)\s*分)?", value)
        if not match:
            return None
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        total = hours * 60 + minutes
        return total or None

    def _clean_text(self, value: str | None, max_length: int) -> str | None:
        if value is None:
            return None
        text = str(value).replace("　", " ").strip()
        return text[:max_length] if text else None

    def _normalize_manual_dimension(self, dimension: str) -> str | None:
        mapping = {
            "destination": "destination",
            "city": "destination",
            "transport": "transport",
            "pace": "pace",
            "interest": "interest",
            "avoidance": "avoidance",
            "negative_preference": "avoidance",
            "budget": "budget",
            "budget_style": "budget_style",
            "behavior": "behavior",
            "risk": "risk",
        }
        return mapping.get(str(dimension or "").strip().lower())

    def _normalize_manual_value(self, dimension: str, value: str) -> str | None:
        cleaned = self._clean_text(value, 120)
        if not cleaned:
            return None
        if dimension == "avoidance" and cleaned.startswith("避免"):
            cleaned = cleaned[2:].strip() or cleaned
        return cleaned

    def _ensure_utc(self, value: datetime) -> datetime:
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
