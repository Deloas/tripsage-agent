import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median

from sqlalchemy.orm import Session

from app.agents.nodes import CITY_WORDS
from app.db.models import TravelPreferenceEvent, TravelPreferenceProfile, User, utc_now
from app.schemas.workspace import BudgetProfileView, PreferenceEvidenceView, PreferenceProfileView


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
    "轻松": ["轻松", "悠闲", "慢游", "慢慢逛", "宽松", "不赶"],
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
    "高强度": ["不要太赶", "别太赶", "不要特种兵", "不想排太满", "不要高强度"],
    "步行过多": ["少走路", "不要走太多路", "别走太多路"],
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
    "trip_signal": "inferred",
    "destination_inferred": "inferred",
    "decision_accept": "behavior",
    "decision_ignore": "behavior",
    "itinerary_edit": "behavior",
    "railway_selection": "behavior",
    "legacy_profile": "inferred",
}

SOURCE_WEIGHTS = {
    "user_message": 1.0,
    "profile_setting": 1.15,
    "trip_signal": 0.45,
    "destination_inferred": 0.35,
    "decision_accept": 1.1,
    "decision_ignore": 1.0,
    "itinerary_edit": 1.2,
    "railway_selection": 1.05,
    "legacy_profile": 0.55,
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

    def get_profile(self) -> PreferenceProfileView:
        """读取聚合后的用户偏好画像。"""
        profile = self._get_or_create(commit=False)
        events = self._load_events()
        legacy_events = self._legacy_seed_events(profile)
        user = self._load_user()
        user_events = self._profile_setting_events(user)
        return self._build_profile(events + legacy_events + user_events)

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
            return self.get_profile()

        now = utc_now()
        for signal in signals:
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
                    metadata_json=json.dumps(signal.metadata or {}, ensure_ascii=False),
                    raw_text=(signal.raw_text or message)[:4000],
                    created_at=now,
                    expires_at=now + timedelta(days=365),
                )
            )

        aggregated = self._build_profile(self._load_events() + self._profile_setting_events(self._load_user()))
        self._write_legacy_snapshot(profile, aggregated)
        self.db.add(profile)
        self.db.commit()
        return aggregated

    def _load_events(self) -> list[TravelPreferenceEvent]:
        return (
            self.db.query(TravelPreferenceEvent)
            .filter(TravelPreferenceEvent.user_key == self.user_key)
            .order_by(TravelPreferenceEvent.created_at.desc(), TravelPreferenceEvent.id.desc())
            .limit(MAX_EVENTS)
            .all()
        )

    def _build_profile(
        self,
        events: list[TravelPreferenceEvent | PreferenceSignal],
    ) -> PreferenceProfileView:
        now = utc_now()
        positive_scores: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        negative_scores: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        explicit_scores: dict[str, float] = defaultdict(float)
        inferred_scores: dict[str, float] = defaultdict(float)
        behavior_scores: dict[str, float] = defaultdict(float)
        budget_amounts: list[int] = []
        budget_style_scores: dict[str, float] = defaultdict(float)
        recent_evidence: list[PreferenceEvidenceView] = []
        seen_recent: set[tuple[str, str, str, str]] = set()
        updated_at: datetime | None = None

        normalized_events = self._normalize_events(events)
        for item in normalized_events:
            score = item["score"]
            dimension = item["dimension"]
            value = item["value"]
            polarity = item["polarity"]
            label = self._event_label(dimension, value, polarity)

            if polarity == "negative":
                negative_scores[dimension][value] += score
            else:
                positive_scores[dimension][value] += score

            source_group = SOURCE_GROUPS.get(item["source_type"], "inferred")
            if source_group == "explicit":
                explicit_scores[label] += score
            elif source_group == "behavior":
                behavior_scores[label] += score
            else:
                inferred_scores[label] += score

            if dimension == "budget" and item["amount"] is not None and polarity == "positive":
                budget_amounts.append(item["amount"])
            if dimension == "budget_style":
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

        preferred_cities = self._top_values(positive_scores.get("destination", {}))
        transport_modes = self._top_values(positive_scores.get("transport", {}))
        pace_tags = self._top_values(positive_scores.get("pace", {}))
        interest_tags = self._top_values(positive_scores.get("interest", {}))
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
            len(normalized_events),
        )
        return PreferenceProfileView(
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
            recommendation_hint=self._hint(
                preferred_cities,
                budget_range,
                transport_modes,
                pace_tags,
                interest_tags,
                negative_preferences,
                behavior_signals,
                profile_strength,
            ),
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
            score = weight * confidence * self._time_decay(created_at, now)
            normalized.append(
                {
                    "dimension": dimension,
                    "value": value,
                    "polarity": polarity,
                    "source_type": source_type,
                    "confidence": confidence,
                    "weight": weight,
                    "score": score,
                    "created_at": created_at,
                    "amount": self._extract_amount(metadata),
                }
            )
        return normalized

    def _extract_from_text(self, text: str, source_type: str) -> list[PreferenceSignal]:
        lowered = self._normalize_text(text)
        signals: list[PreferenceSignal] = []

        for city in CITY_WORDS:
            if city not in text:
                continue
            confidence = 0.82 if f"去{city}" in text or f"{city}怎么玩" in text else 0.58
            signals.append(
                PreferenceSignal(
                    dimension="destination",
                    value=city,
                    source_type=source_type,
                    confidence=confidence,
                    weight=SOURCE_WEIGHTS[source_type],
                    raw_text=text,
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
            if self._contains_any(lowered, patterns):
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
        profile.preferred_cities_json = json.dumps(
            {value: index + 1 for index, value in enumerate(aggregated.preferred_cities)},
            ensure_ascii=False,
        )
        profile.transport_modes_json = json.dumps(
            {value: index + 1 for index, value in enumerate(aggregated.transport_modes)},
            ensure_ascii=False,
        )
        profile.pace_tags_json = json.dumps(
            {value: index + 1 for index, value in enumerate(aggregated.pace_tags)},
            ensure_ascii=False,
        )
        profile.interest_tags_json = json.dumps(
            {value: index + 1 for index, value in enumerate(aggregated.interest_tags)},
            ensure_ascii=False,
        )
        budget_values = [
            item.median
            for item in [aggregated.budget_profile]
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

    def _ensure_utc(self, value: datetime) -> datetime:
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
