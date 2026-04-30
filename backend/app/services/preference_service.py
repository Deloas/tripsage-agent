import json
import re
from statistics import median

from sqlalchemy.orm import Session

from app.agents.nodes import CITY_WORDS
from app.db.models import TravelPreferenceProfile, utc_now
from app.schemas.workspace import PreferenceProfileView


TRANSPORT_KEYWORDS = ["高铁", "地铁", "步行", "打车", "公交", "火车", "自驾"]
PACE_KEYWORDS = ["轻松", "紧凑", "慢游", "深度", "周末", "亲子"]
INTEREST_KEYWORDS = ["美食", "历史", "园林", "博物馆", "自然", "夜游", "拍照", "文化"]


class PreferenceService:
    """用户旅行偏好画像服务，使用本地会话内容做轻量沉淀。"""

    def __init__(self, db: Session, user_key: str = "default") -> None:
        self.db = db
        self.user_key = user_key

    def get_profile(self) -> PreferenceProfileView:
        """读取偏好画像，若不存在则返回空画像。"""
        profile = self._get_or_create(commit=False)
        cities = self._top_keys(self._loads_dict(profile.preferred_cities_json))
        transports = self._top_keys(self._loads_dict(profile.transport_modes_json))
        pace = self._top_keys(self._loads_dict(profile.pace_tags_json))
        interests = self._top_keys(self._loads_dict(profile.interest_tags_json))
        budgets = self._loads_list(profile.budget_values_json)
        budget_range = self._budget_range(budgets)
        return PreferenceProfileView(
            preferred_cities=cities,
            budget_range=budget_range,
            transport_modes=transports,
            pace_tags=pace,
            interest_tags=interests,
            recommendation_hint=self._hint(cities, budget_range, transports, pace, interests),
            updated_at=profile.updated_at.isoformat() if profile.updated_at else None,
        )

    def learn_from_interaction(self, message: str, response: dict) -> PreferenceProfileView:
        """从用户问题和智能体结果中抽取偏好并更新画像。"""
        profile = self._get_or_create(commit=False)
        text = f"{message}\n{response.get('answer', '')}"
        city_counts = self._loads_dict(profile.preferred_cities_json)
        transport_counts = self._loads_dict(profile.transport_modes_json)
        pace_counts = self._loads_dict(profile.pace_tags_json)
        interest_counts = self._loads_dict(profile.interest_tags_json)
        budgets = self._loads_list(profile.budget_values_json)

        for city in CITY_WORDS:
            if city in text:
                city_counts[city] = city_counts.get(city, 0) + 1
        for card in response.get("cards") or []:
            if isinstance(card, dict) and card.get("type") == "destination" and card.get("title"):
                city = str(card["title"])
                city_counts[city] = city_counts.get(city, 0) + 1
        for keyword in TRANSPORT_KEYWORDS:
            if keyword in text:
                transport_counts[keyword] = transport_counts.get(keyword, 0) + 1
        for keyword in PACE_KEYWORDS:
            if keyword in text:
                pace_counts[keyword] = pace_counts.get(keyword, 0) + 1
        for keyword in INTEREST_KEYWORDS:
            if keyword in text:
                interest_counts[keyword] = interest_counts.get(keyword, 0) + 1
        for value in re.findall(r"(?:预算\s*)?([0-9]{2,6})\s*元?", message):
            budgets.append(int(value))

        profile.preferred_cities_json = json.dumps(city_counts, ensure_ascii=False)
        profile.transport_modes_json = json.dumps(transport_counts, ensure_ascii=False)
        profile.pace_tags_json = json.dumps(pace_counts, ensure_ascii=False)
        profile.interest_tags_json = json.dumps(interest_counts, ensure_ascii=False)
        profile.budget_values_json = json.dumps(budgets[-20:], ensure_ascii=False)
        profile.updated_at = utc_now()
        self.db.add(profile)
        self.db.commit()
        return self.get_profile()

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

    def _loads_dict(self, value: str | None) -> dict[str, int]:
        try:
            data = json.loads(value or "{}")
            return {str(key): int(count) for key, count in data.items()}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    def _loads_list(self, value: str | None) -> list[int]:
        try:
            data = json.loads(value or "[]")
            return [int(item) for item in data if str(item).isdigit()]
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    def _top_keys(self, counts: dict[str, int], limit: int = 5) -> list[str]:
        return [key for key, _ in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]]

    def _budget_range(self, budgets: list[int]) -> str | None:
        if not budgets:
            return None
        center = int(median(budgets))
        return f"{max(100, center - 300)}-{center + 300}元"

    def _hint(
        self,
        cities: list[str],
        budget_range: str | None,
        transports: list[str],
        pace: list[str],
        interests: list[str],
    ) -> str:
        parts = []
        if cities:
            parts.append(f"偏好城市：{'、'.join(cities[:3])}")
        if budget_range:
            parts.append(f"常用预算：{budget_range}")
        if transports:
            parts.append(f"交通偏好：{'、'.join(transports[:3])}")
        if pace:
            parts.append(f"节奏偏好：{'、'.join(pace[:3])}")
        if interests:
            parts.append(f"兴趣：{'、'.join(interests[:3])}")
        return "；".join(parts) if parts else "暂无稳定偏好，系统会在后续规划中自动沉淀。"
