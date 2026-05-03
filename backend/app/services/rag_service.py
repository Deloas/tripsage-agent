import math
import re
from collections.abc import Sequence

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Guide, GuideChunk, GuideSource, Place
from app.schemas.common import SourceRef
from app.schemas.guides import GuideSearchItem
from app.services.guide_ingest_service import build_structured_guide_data
from app.services.vector_store_service import VectorStoreService


CITY_TERMS = [
    "北京",
    "上海",
    "南京",
    "苏州",
    "杭州",
    "成都",
    "重庆",
    "广州",
    "深圳",
    "厦门",
    "青岛",
    "长沙",
    "武汉",
    "西安",
    "云南",
]

TRAVEL_TERMS = [
    "两天一夜",
    "三天两夜",
    "攻略",
    "行程",
    "路线",
    "景点",
    "美食",
    "博物馆",
    "高铁",
    "铁路",
    "火车",
    "车次",
    "天气",
    "雨天",
    "园林",
    "历史",
    "轻松",
]


def tokenize_query(query: str) -> list[str]:
    """把自然语言问题拆成更适合本地检索的关键词。"""
    tokens: list[str] = []
    for term in CITY_TERMS + TRAVEL_TERMS:
        if term in query:
            tokens.append(term)
    tokens.extend(re.findall(r"[A-Za-z0-9]{2,}", query))

    for segment in re.findall(r"[\u4e00-\u9fa5]{2,}", query):
        if len(segment) <= 4:
            tokens.append(segment)
            continue
        for size in (4, 3, 2):
            tokens.extend(segment[index : index + size] for index in range(0, len(segment) - size + 1))

    stop_words = {"怎么", "怎么玩", "一个", "顺便", "请给", "可以", "适合", "如果", "推荐一下"}
    seen: set[str] = set()
    cleaned: list[str] = []
    for token in tokens:
        compact = token.strip()
        if len(compact) < 2 or compact in stop_words or compact in seen:
            continue
        seen.add(compact)
        cleaned.append(compact)
    return cleaned[:40]


def score_chunk(query: str, chunk: str, city: str | None) -> float:
    """给本地命中的攻略片段一个轻量相关性分数。"""
    tokens = tokenize_query(query)
    if not tokens:
        return 0.1
    hits = sum(1 for token in tokens if token in chunk)
    base = hits / max(len(tokens), 1)
    if city and city in chunk:
        base += 0.35
    for term in CITY_TERMS + TRAVEL_TERMS:
        if term in query and term in chunk:
            base += 0.08
    return round(min(1.0, math.sqrt(base)), 4)


class RagService:
    """本地攻略检索服务，融合向量检索和 SQLite 关键词检索。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def search(self, query: str, city: str | None = None, top_k: int = 5) -> list[GuideSearchItem]:
        """返回带来源信息的攻略检索结果。"""
        vector_hits = VectorStoreService().search(query, top_k=top_k * 2, city=city)
        vector_score_map = {hit["chunk_id"]: hit["score"] for hit in vector_hits}

        vector_items = self._items_by_chunk_ids(list(vector_score_map.keys()), vector_score_map)
        keyword_items = self._keyword_search(query, city, limit=max(80, top_k * 8))

        merged: dict[str, GuideSearchItem] = {}
        for item in vector_items:
            merged[item.chunk_id] = item
        for item in keyword_items:
            if item.chunk_id in merged:
                merged[item.chunk_id].score = min(1.0, max(merged[item.chunk_id].score, item.score) + 0.08)
            else:
                merged[item.chunk_id] = item

        ranked = list(merged.values())
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[:top_k]

    def _keyword_search(self, query: str, city: str | None = None, limit: int = 80) -> list[GuideSearchItem]:
        """SQLite 关键词兜底检索。"""
        tokens = tokenize_query(query)
        filters = []
        if city:
            filters.append(Guide.city.like(f"%{city}%"))
        for token in tokens[:12]:
            filters.append(GuideChunk.content.like(f"%{token}%"))
            filters.append(Guide.title.like(f"%{token}%"))

        stmt = (
            select(GuideChunk, Guide, GuideSource)
            .join(Guide, Guide.id == GuideChunk.guide_id)
            .join(GuideSource, GuideSource.id == Guide.source_id)
            .limit(limit)
        )
        if filters:
            stmt = stmt.where(or_(*filters))

        rows = self.db.execute(stmt).all()
        ranked: list[GuideSearchItem] = []
        for chunk, guide, source in rows:
            score = score_chunk(query, f"{guide.title}\n{chunk.content}", city)
            ranked.append(
                GuideSearchItem(
                    guide_id=guide.id,
                    chunk_id=chunk.id,
                    title=guide.title,
                    city=guide.city,
                    content=chunk.content,
                    score=score,
                    source=SourceRef(title=source.title, url=source.source_url, source_type=source.source_type),
                )
            )

        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked

    def _items_by_chunk_ids(self, chunk_ids: list[str], score_map: dict[str, float]) -> list[GuideSearchItem]:
        """根据向量命中的 chunk_id 回查 SQLite。"""
        if not chunk_ids:
            return []

        stmt = (
            select(GuideChunk, Guide, GuideSource)
            .join(Guide, Guide.id == GuideChunk.guide_id)
            .join(GuideSource, GuideSource.id == Guide.source_id)
            .where(GuideChunk.id.in_(chunk_ids))
        )
        rows = self.db.execute(stmt).all()
        order = {chunk_id: index for index, chunk_id in enumerate(chunk_ids)}
        items: list[GuideSearchItem] = []
        for chunk, guide, source in rows:
            items.append(
                GuideSearchItem(
                    guide_id=guide.id,
                    chunk_id=chunk.id,
                    title=guide.title,
                    city=guide.city,
                    content=chunk.content,
                    score=score_map.get(chunk.id, 0.0),
                    source=SourceRef(title=source.title, url=source.source_url, source_type=source.source_type),
                )
            )
        items.sort(key=lambda item: order.get(item.chunk_id, 9999))
        return items

    def list_guides(
        self,
        city: str | None = None,
        category: str | None = None,
        source_type: str | None = None,
        keyword: str | None = None,
        sort_by: str = "latest",
        limit: int = 30,
        offset: int = 0,
    ) -> tuple[list[dict], int, dict]:
        """返回攻略列表、总数和筛选聚合。"""
        filters = self._build_guide_filters(city=city, category=category, source_type=source_type, keyword=keyword)

        total_stmt = select(func.count(Guide.id)).join(GuideSource, GuideSource.id == Guide.source_id)
        if filters:
            total_stmt = total_stmt.where(*filters)
        total = int(self.db.execute(total_stmt).scalar_one())

        stmt = select(Guide, GuideSource).join(GuideSource, GuideSource.id == Guide.source_id)
        if filters:
            stmt = stmt.where(*filters)
        stmt = self._apply_guide_sort(stmt, sort_by).offset(offset).limit(limit)
        rows = self.db.execute(stmt).all()
        items = [
            {
                "id": guide.id,
                "title": guide.title,
                "city": guide.city,
                "summary": guide.summary,
                "source_url": source.source_url,
                "source_type": source.source_type,
                "category": source.category,
                "crawl_status": source.crawl_status,
            }
            for guide, source in rows
        ]
        facets = self._build_guide_facets(keyword=keyword)
        return items, total, facets

    def get_guide_detail(self, guide_id: int) -> dict | None:
        """返回单条攻略的完整详情。"""
        stmt = (
            select(Guide, GuideSource)
            .join(GuideSource, GuideSource.id == Guide.source_id)
            .where(Guide.id == guide_id)
        )
        row = self.db.execute(stmt).first()
        if not row:
            return None

        guide, source = row
        chunk_rows = (
            self.db.execute(
                select(GuideChunk).where(GuideChunk.guide_id == guide.id).order_by(GuideChunk.chunk_index.asc())
            )
            .scalars()
            .all()
        )
        place_rows = (
            self.db.execute(select(Place).where(Place.guide_id == guide.id).order_by(Place.name.asc()))
            .scalars()
            .all()
        )
        places = [
            {
                "name": place.name,
                "city": place.city,
                "place_type": place.place_type,
                "address": place.address,
            }
            for place in place_rows
        ]
        structured = build_structured_guide_data(
            guide.title,
            source.raw_text or "",
            city=guide.city,
            days=guide.days,
            places=[{"name": place.name, "type": place.place_type or "scenic"} for place in place_rows],
            budget_min=guide.budget_min,
            budget_max=guide.budget_max,
            travel_style=guide.travel_style,
        )
        return {
            "id": guide.id,
            "title": guide.title,
            "city": guide.city,
            "summary": guide.summary,
            "days": guide.days,
            "budget_min": guide.budget_min,
            "budget_max": guide.budget_max,
            "travel_style": guide.travel_style,
            "source_url": source.source_url,
            "source_type": source.source_type,
            "category": source.category,
            "crawl_status": source.crawl_status,
            "content": source.raw_text or "",
            "created_at": guide.created_at.isoformat() if guide.created_at else None,
            "chunk_count": len(chunk_rows),
            "structured": structured,
            "chunks": [
                {
                    "id": chunk.id,
                    "chunk_index": chunk.chunk_index,
                    "content": chunk.content,
                }
                for chunk in chunk_rows
            ],
            "places": places,
        }

    def list_sources(
        self,
        limit: int = 100,
        offset: int = 0,
        status: str | None = None,
    ) -> tuple[list[dict], int]:
        """返回攻略来源列表。"""
        total_stmt = select(func.count(GuideSource.id))
        if status:
            total_stmt = total_stmt.where(GuideSource.crawl_status == status)
        total = int(self.db.execute(total_stmt).scalar_one())

        stmt = select(GuideSource)
        if status:
            stmt = stmt.where(GuideSource.crawl_status == status)
        stmt = stmt.order_by(GuideSource.created_at.desc()).offset(offset).limit(limit)
        rows = self.db.execute(stmt).scalars().all()
        items = [
            {
                "id": source.id,
                "title": source.title,
                "source_type": source.source_type,
                "source_url": source.source_url,
                "raw_url": source.raw_url,
                "category": source.category,
                "crawl_status": source.crawl_status,
            }
            for source in rows
        ]
        return items, total

    def _build_guide_filters(
        self,
        city: str | None = None,
        category: str | None = None,
        source_type: str | None = None,
        keyword: str | None = None,
    ) -> list:
        """统一构建列表、统计和聚合使用的过滤条件。"""
        filters: list = []
        if city:
            filters.append(Guide.city == city)
        if category:
            filters.append(GuideSource.category == category)
        if source_type:
            filters.append(GuideSource.source_type == source_type)
        if keyword:
            like_keyword = f"%{keyword.strip()}%"
            filters.append(
                or_(
                    Guide.title.like(like_keyword),
                    Guide.summary.like(like_keyword),
                    Guide.city.like(like_keyword),
                    GuideSource.category.like(like_keyword),
                    GuideSource.raw_text.like(like_keyword),
                )
            )
        return filters

    def _apply_guide_sort(self, stmt, sort_by: str):
        """统一处理攻略列表排序。"""
        if sort_by == "oldest":
            return stmt.order_by(Guide.created_at.asc(), Guide.id.asc())
        if sort_by == "city_hot":
            city_count_subquery = (
                select(Guide.city.label("city"), func.count(Guide.id).label("city_count")).group_by(Guide.city).subquery()
            )
            return (
                stmt.join(city_count_subquery, city_count_subquery.c.city == Guide.city)
                .order_by(city_count_subquery.c.city_count.desc(), Guide.created_at.desc(), Guide.id.desc())
            )
        if sort_by == "source_priority":
            source_priority = case(
                (GuideSource.source_type == "weibo_rendered", 0),
                (GuideSource.source_type == "manual", 1),
                else_=2,
            )
            return stmt.order_by(source_priority.asc(), Guide.created_at.desc(), Guide.id.desc())
        return stmt.order_by(Guide.created_at.desc(), Guide.id.desc())

    def _build_guide_facets(self, keyword: str | None = None) -> dict:
        """返回知识库筛选项聚合。"""
        keyword_filters = self._build_guide_filters(keyword=keyword)
        return {
            "source_types": self._facet_source_types(keyword_filters),
            "cities": self._facet_cities(keyword_filters),
            "categories": self._facet_categories(keyword_filters),
        }

    def _facet_source_types(self, filters: Sequence | None = None) -> list[dict]:
        stmt = (
            select(GuideSource.source_type, func.count(Guide.id))
            .join(Guide, Guide.source_id == GuideSource.id)
            .group_by(GuideSource.source_type)
            .order_by(func.count(Guide.id).desc(), GuideSource.source_type.asc())
        )
        if filters:
            stmt = stmt.where(*filters)
        return [
            {"value": value, "label": value, "count": int(count)}
            for value, count in self.db.execute(stmt).all()
            if value
        ]

    def _facet_categories(self, filters: Sequence | None = None) -> list[dict]:
        stmt = (
            select(GuideSource.category, func.count(Guide.id))
            .join(Guide, Guide.source_id == GuideSource.id)
            .group_by(GuideSource.category)
            .order_by(func.count(Guide.id).desc(), GuideSource.category.asc())
        )
        if filters:
            stmt = stmt.where(*filters)
        return [
            {"value": value, "label": value, "count": int(count)}
            for value, count in self.db.execute(stmt).all()
            if value
        ][:40]

    def _facet_cities(self, filters: Sequence | None = None) -> list[dict]:
        stmt = (
            select(Guide.city, func.count(Guide.id))
            .join(GuideSource, GuideSource.id == Guide.source_id)
            .group_by(Guide.city)
            .order_by(func.count(Guide.id).desc(), Guide.city.asc())
        )
        if filters:
            stmt = stmt.where(*filters)

        items: list[dict] = []
        for value, count in self.db.execute(stmt).all():
            if not self._is_presentable_city(value):
                continue
            items.append({"value": value, "label": value, "count": int(count)})
            if len(items) >= 40:
                break
        return items

    def _is_presentable_city(self, value: str | None) -> bool:
        """过滤明显失真的城市抽取结果。"""
        if not value or value == "未知城市":
            return False
        compact = value.strip()
        if len(compact) < 2 or len(compact) > 8:
            return False
        if re.search(r"[A-Za-z0-9]", compact):
            return False
        if re.search(r"[，。、“”‘’？：；（）\\-\\s]", compact):
            return False
        return True
