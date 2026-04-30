import math
import re

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import Guide, GuideChunk, GuideSource
from app.schemas.common import SourceRef
from app.schemas.guides import GuideSearchItem
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
    """把用户问题拆成检索关键词；中文场景先用轻量规则兜底。"""
    tokens: list[str] = []
    for term in CITY_TERMS + TRAVEL_TERMS:
        if term in query:
            tokens.append(term)
    tokens.extend(re.findall(r"[A-Za-z0-9]{2,}", query))
    # 中文连续长句不能直接作为单个 token，否则“上海到苏州两天一夜怎么玩”很难命中攻略切片。
    for segment in re.findall(r"[\u4e00-\u9fa5]{2,}", query):
        if len(segment) <= 4:
            tokens.append(segment)
            continue
        for size in (4, 3, 2):
            tokens.extend(segment[index : index + size] for index in range(0, len(segment) - size + 1))
    seen: set[str] = set()
    cleaned: list[str] = []
    stop_words = {"怎么", "怎么玩", "一下", "顺便", "请给", "可以", "适合", "如果"}
    for token in tokens:
        token = token.strip()
        if len(token) < 2 or token in stop_words or token in seen:
            continue
        seen.add(token)
        cleaned.append(token)
    return cleaned[:40]


def score_chunk(query: str, chunk: str, city: str | None) -> float:
    """计算轻量关键词分数，后续接入 Chroma 后作为混合检索的关键词加权。"""
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
    """攻略检索服务，融合 Chroma 向量检索和 SQLite 关键词检索。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def search(self, query: str, city: str | None = None, top_k: int = 5) -> list[GuideSearchItem]:
        """搜索攻略片段，并返回带来源的前端展示结构。"""
        vector_hits = VectorStoreService().search(query, top_k=top_k * 2, city=city)
        vector_score_map = {hit["chunk_id"]: hit["score"] for hit in vector_hits}

        vector_items = self._items_by_chunk_ids(list(vector_score_map.keys()), vector_score_map)
        keyword_items = self._keyword_search(query, city, limit=max(80, top_k * 8))

        merged: dict[str, GuideSearchItem] = {}
        for item in vector_items:
            merged[item.chunk_id] = item
        for item in keyword_items:
            if item.chunk_id in merged:
                # 向量分和关键词分取较高值，并轻微奖励双通道同时命中的片段。
                merged[item.chunk_id].score = min(1.0, max(merged[item.chunk_id].score, item.score) + 0.08)
            else:
                merged[item.chunk_id] = item

        ranked = list(merged.values())
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[:top_k]

    def _keyword_search(self, query: str, city: str | None = None, limit: int = 80) -> list[GuideSearchItem]:
        """SQLite 关键词检索，作为向量库不可用或低命中时的稳定兜底。"""
        tokens = tokenize_query(query)
        filters = []
        if city:
            filters.append(Guide.city.like(f"%{city}%"))
        # 优先使用城市、旅行主题词和较短中文片段，降低长自然语言问题的漏召回。
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
                    source=SourceRef(
                        title=source.title,
                        url=source.source_url,
                        source_type=source.source_type,
                    ),
                )
            )

        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked

    def _items_by_chunk_ids(self, chunk_ids: list[str], score_map: dict[str, float]) -> list[GuideSearchItem]:
        """根据向量库返回的 chunk_id 回查 SQLite，保证来源信息可信。"""
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
                    source=SourceRef(
                        title=source.title,
                        url=source.source_url,
                        source_type=source.source_type,
                    ),
                )
            )
        items.sort(key=lambda item: order.get(item.chunk_id, 9999))
        return items

    def list_guides(self, city: str | None = None, limit: int = 30) -> list[dict]:
        """返回攻略列表，供知识库页面展示。"""
        stmt = select(Guide, GuideSource).join(GuideSource, GuideSource.id == Guide.source_id)
        if city:
            stmt = stmt.where(Guide.city.like(f"%{city}%"))
        stmt = stmt.order_by(Guide.created_at.desc()).limit(limit)
        rows = self.db.execute(stmt).all()
        return [
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

    def list_sources(self, limit: int = 100, status: str | None = None) -> list[dict]:
        """返回攻略来源列表，包含微博采集到但尚未解析正文的入口。"""
        stmt = select(GuideSource)
        if status:
            stmt = stmt.where(GuideSource.crawl_status == status)
        stmt = stmt.order_by(GuideSource.created_at.desc()).limit(limit)
        rows = self.db.execute(stmt).scalars().all()
        return [
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
