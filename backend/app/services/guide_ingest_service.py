import hashlib
import json
import re

from sqlalchemy.orm import Session

from app.db.models import Guide, GuideChunk, GuideSource, Place
from app.schemas.guides import GuideCreateRequest
from app.services.vector_store_service import VectorStoreService


KNOWN_CITIES = [
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
    "大理",
    "丽江",
    "昆明",
]


def clean_text(text: str) -> str:
    """清洗攻略文本，保留用户经验表达，只去掉影响检索的噪声。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def infer_city(title: str, content: str) -> str:
    """用轻量规则抽取城市；后续接入大模型后可替换为结构化抽取。"""
    combined = f"{title}\n{content}"
    for city in KNOWN_CITIES:
        if city in combined:
            return city
    match = re.search(r"([\u4e00-\u9fa5]{2,4})(?:旅游|攻略|三天|两天|一日游)", combined)
    return match.group(1) if match else "未知城市"


def infer_days(content: str) -> int | None:
    """从常见中文表达中推断旅行天数。"""
    patterns = {
        "一天": 1,
        "一日": 1,
        "两天": 2,
        "二天": 2,
        "三天": 3,
        "四天": 4,
        "五天": 5,
    }
    for word, days in patterns.items():
        if word in content:
            return days
    return None


def infer_places(content: str, city: str) -> list[dict]:
    """用常见地点后缀抽取景点和餐饮名称，先满足骨架阶段可用性。"""
    candidates = re.findall(r"([\u4e00-\u9fa5A-Za-z0-9]{2,16}(?:园|寺|山|湖|街|巷|馆|桥|站|店|坊|城|江|河|塔))", content)
    seen: set[str] = set()
    places: list[dict] = []
    for name in candidates:
        if name in seen or name == city:
            continue
        seen.add(name)
        place_type = "food" if name.endswith("店") else "scenic"
        places.append({"name": name, "type": place_type})
        if len(places) >= 12:
            break
    return places


def build_summary(content: str) -> str:
    """生成不依赖大模型的摘要，避免未配置模型时无法添加攻略。"""
    compact = re.sub(r"\s+", " ", content).strip()
    return compact[:160] + ("..." if len(compact) > 160 else "")


def split_chunks(content: str, chunk_size: int = 700, overlap: int = 100) -> list[str]:
    """按固定窗口切片；后续可升级为按标题和天数优先切片。"""
    if len(content) <= chunk_size:
        return [content]
    chunks: list[str] = []
    start = 0
    while start < len(content):
        end = min(start + chunk_size, len(content))
        chunks.append(content[start:end].strip())
        if end == len(content):
            break
        start = max(0, end - overlap)
    return [chunk for chunk in chunks if chunk]


class GuideIngestService:
    """攻略入库服务，负责原文保存、字段抽取、地点抽取和切片。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def add_guide(self, payload: GuideCreateRequest) -> dict:
        """新增攻略并写入 SQLite，同时尽力同步到 Chroma 向量库。"""
        cleaned = clean_text(payload.content)
        city = infer_city(payload.title, cleaned)
        days = infer_days(cleaned)
        places = infer_places(cleaned, city)
        summary = build_summary(cleaned)
        vector_chunks: list[dict] = []

        source = GuideSource(
            source_type=payload.source_type,
            source_url=payload.source_url,
            raw_url=payload.raw_url or payload.source_url,
            resolved_url=payload.resolved_url or payload.source_url,
            category=payload.category,
            crawl_status=payload.crawl_status,
            title=payload.title,
            raw_text=cleaned,
            license_note="用户添加或课程演示数据，请在回答中保留来源。",
        )
        self.db.add(source)
        self.db.flush()

        guide = Guide(
            source_id=source.id,
            title=payload.title,
            city=city,
            province=None,
            region=None,
            days=days,
            budget_min=None,
            budget_max=None,
            travel_style=None,
            season=None,
            summary=summary,
        )
        self.db.add(guide)
        self.db.flush()

        chunks = split_chunks(cleaned)
        for index, chunk in enumerate(chunks):
            digest = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
            chunk_id = f"guide-{guide.id}-chunk-{index}"
            metadata = {
                "guide_id": guide.id,
                "title": guide.title,
                "city": guide.city,
                "source_url": source.source_url,
                "source_type": source.source_type,
            }
            vector_chunks.append({"id": chunk_id, "content": chunk, "metadata": metadata})
            self.db.add(
                GuideChunk(
                    id=chunk_id,
                    guide_id=guide.id,
                    chunk_index=index,
                    content_hash=digest,
                    content=chunk,
                    token_count=len(chunk),
                    metadata_json=json.dumps(metadata, ensure_ascii=False),
                )
            )

        for place in places:
            self.db.add(
                Place(
                    guide_id=guide.id,
                    name=place["name"],
                    city=city,
                    place_type=place["type"],
                )
            )

        self.db.commit()
        vector_indexed = VectorStoreService().index_chunks(vector_chunks)
        return {
            "guide_id": guide.id,
            "city": city,
            "chunks": len(chunks),
            "indexed": vector_indexed,
            "extracted": {
                "city": city,
                "days": days,
                "places": places,
                "summary": summary,
            },
        }
