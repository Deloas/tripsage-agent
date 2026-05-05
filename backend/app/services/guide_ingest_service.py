import hashlib
import json
import re

from sqlalchemy.orm import Session

from app.db.models import Guide, GuideChunk, GuideSource, Place
from app.db.models import utc_now
from app.schemas.guides import GuideCreateRequest, GuideUpdateRequest
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
    "哈尔滨",
    "洛阳",
    "桂林",
    "三亚",
    "福州",
    "泉州",
]

SCENIC_SUFFIXES = ("景区", "古镇", "公园", "山", "湖", "寺", "宫", "街", "巷", "城", "馆", "园", "桥", "塔", "岛")
FOOD_SUFFIXES = ("饭店", "餐厅", "火锅", "小馆", "面馆", "酒家", "烧烤", "夜市", "咖啡", "甜品", "小吃", "茶馆")
TRANSPORT_KEYWORDS = {
    "高铁": ("高铁", "动车", "火车"),
    "飞机": ("飞机", "航班", "机场"),
    "地铁": ("地铁", "轨道交通"),
    "公交": ("公交", "巴士", "大巴"),
    "打车": ("打车", "出租车", "网约车"),
    "自驾": ("自驾", "租车", "停车"),
    "步行": ("步行", "徒步"),
    "骑行": ("骑行", "单车"),
}
LODGING_PATTERNS = [
    r"(住在[\u4e00-\u9fa5A-Za-z0-9]{2,18}(?:附近|周边|商圈|地铁站|古城|景区))",
    r"(推荐住[\u4e00-\u9fa5A-Za-z0-9]{2,18}(?:附近|周边|商圈|地铁站|古城|景区))",
    r"([\u4e00-\u9fa5A-Za-z0-9]{2,18}(?:商圈|古城|景区|地铁站)附近)",
]
TRAVEL_STYLE_RULES = {
    "轻松": ("轻松", "慢游", "慢节奏", "不赶", "悠闲"),
    "特种兵": ("暴走", "特种兵", "高强度", "赶路", "打卡"),
    "美食": ("美食", "小吃", "夜市", "咖啡", "甜品"),
    "历史人文": ("历史", "人文", "古城", "博物馆", "遗址", "古镇"),
    "自然风光": ("山水", "自然", "日出", "徒步", "湖", "海边", "森林"),
    "亲子": ("亲子", "带娃", "儿童", "家庭"),
    "情侣": ("情侣", "约会", "浪漫"),
    "拍照": ("出片", "拍照", "摄影", "机位"),
    "夜游": ("夜游", "夜景", "夜生活"),
}
CHINESE_NUMBER_MAP = {
    "零": 0,
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


def clean_text(text: str) -> str:
    """清洗攻略文本，尽量保留原始表达。"""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\u3000+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def infer_city(title: str, content: str) -> str:
    """优先从标题和正文中识别目的地城市。"""
    combined = f"{title}\n{content}"
    for city in KNOWN_CITIES:
        if city in combined:
            return city
    match = re.search(r"([\u4e00-\u9fa5]{2,6})(?:旅游|攻略|行程|两天|三天|一日游)", combined)
    return match.group(1) if match else "未知城市"


def chinese_number_to_int(value: str) -> int | None:
    """把简单中文数字转换成整数，覆盖常见天数表达。"""
    compact = value.strip()
    if not compact:
        return None
    if compact.isdigit():
        return int(compact)
    if compact == "十":
        return 10
    if "十" in compact:
        left, _, right = compact.partition("十")
        left_value = CHINESE_NUMBER_MAP.get(left, 1 if left == "" else None)
        right_value = CHINESE_NUMBER_MAP.get(right, 0 if right == "" else None)
        if left_value is None or right_value is None:
            return None
        return left_value * 10 + right_value
    return CHINESE_NUMBER_MAP.get(compact)


def infer_days(content: str) -> int | None:
    """从攻略中推断建议游玩天数。"""
    patterns = [
        r"([一二两三四五六七八九十0-9]{1,3})天([一二两三四五六七八九十0-9]{1,3})晚",
        r"([一二两三四五六七八九十0-9]{1,3})天",
        r"([一二两三四五六七八九十0-9]{1,3})日游",
    ]
    for pattern in patterns:
        match = re.search(pattern, content)
        if not match:
            continue
        days_value = chinese_number_to_int(match.group(1))
        if days_value and 1 <= days_value <= 30:
            return days_value
    return None


def split_text_segments(content: str) -> list[str]:
    """按段落和标点切成较短语义片段，便于规则抽取。"""
    normalized = clean_text(content)
    if not normalized:
        return []
    segments: list[str] = []
    for block in re.split(r"\n+", normalized):
        pieces = [part.strip() for part in re.split(r"[。！？；;]", block) if part.strip()]
        segments.extend(pieces or [block.strip()])
    return [segment for segment in segments if len(segment) >= 2]


def unique_compact_list(items: list[str], limit: int = 8) -> list[str]:
    """保持顺序去重，避免前端结构化信息膨胀。"""
    seen: set[str] = set()
    results: list[str] = []
    for item in items:
        compact = re.sub(r"\s+", "", item.strip())
        if not compact or compact in seen:
            continue
        seen.add(compact)
        results.append(item.strip())
        if len(results) >= limit:
            break
    return results


def infer_places(content: str, city: str) -> list[dict]:
    """用景点和美食后缀抽取地点。"""
    candidates = re.findall(r"([\u4e00-\u9fa5A-Za-z0-9]{2,20})", content)
    places: list[dict] = []
    seen: set[str] = set()
    for name in candidates:
        name = re.sub(r"^(第[一二两三四五六七八九十0-9]+天|上午|中午|下午|晚上|夜里|夜晚)", "", name).strip()
        if name == city or name in seen:
            continue
        place_type = None
        if name.endswith(FOOD_SUFFIXES):
            place_type = "food"
        elif name.endswith(SCENIC_SUFFIXES):
            place_type = "scenic"
        elif "美食" in name or "小吃" in name:
            place_type = "food"
        if not place_type:
            continue
        seen.add(name)
        places.append({"name": name, "type": place_type})
        if len(places) >= 16:
            break
    return places


def build_summary(content: str) -> str:
    """生成不依赖大模型的短摘要。"""
    compact = re.sub(r"\s+", " ", content).strip()
    return compact[:180] + ("..." if len(compact) > 180 else "")


def split_chunks(content: str, chunk_size: int = 700, overlap: int = 100) -> list[str]:
    """把攻略切成向量检索友好的片段。"""
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


def parse_budget_token(token: str) -> int | None:
    """把预算片段里的金额转换成整数。"""
    digits = re.sub(r"[^\d]", "", token)
    if not digits:
        return None
    try:
        value = int(digits)
    except ValueError:
        return None
    if value <= 0 or value > 200000:
        return None
    return value


def infer_budget_range(content: str) -> tuple[int | None, int | None]:
    """尽量识别攻略中的预算区间。"""
    patterns = [
        r"(?:预算|人均|花费|费用|总计|大概)\s*[约大概在共计：:]?\s*([0-9]{2,6})\s*[-~到至]\s*([0-9]{2,6})\s*元",
        r"(?:预算|人均|花费|费用|总计|大概)\s*[约大概在共计：:]?\s*([0-9]{2,6})\s*元",
    ]
    for pattern in patterns:
        match = re.search(pattern, content)
        if not match:
            continue
        first = parse_budget_token(match.group(1))
        second = parse_budget_token(match.group(2)) if match.lastindex and match.lastindex >= 2 else None
        if first and second:
            return (min(first, second), max(first, second))
        if first:
            return (first, first)

    explicit_tokens = re.findall(r"([0-9]{2,6})\s*元", content)
    values = sorted({value for token in explicit_tokens if (value := parse_budget_token(token))})
    if len(values) >= 2:
        return values[0], values[-1]
    if len(values) == 1:
        return values[0], values[0]
    return None, None


def infer_transport_modes(content: str) -> list[str]:
    """识别攻略里的交通建议。"""
    found: list[str] = []
    for label, keywords in TRANSPORT_KEYWORDS.items():
        if any(keyword in content for keyword in keywords):
            found.append(label)
    return found


def infer_lodging_suggestions(content: str) -> list[str]:
    """抽取住哪里更方便这类建议。"""
    suggestions: list[str] = []
    for pattern in LODGING_PATTERNS:
        suggestions.extend(match.group(1) for match in re.finditer(pattern, content))
    if not suggestions:
        segments = split_text_segments(content)
        suggestions.extend(segment for segment in segments if ("住宿" in segment or "酒店" in segment or "民宿" in segment) and len(segment) <= 32)
    return unique_compact_list(suggestions, limit=6)


def infer_travel_style_tags(content: str) -> list[str]:
    """识别攻略的玩法风格标签。"""
    tags: list[str] = []
    for tag, keywords in TRAVEL_STYLE_RULES.items():
        if any(keyword in content for keyword in keywords):
            tags.append(tag)
    return tags


def build_structured_guide_data(
    title: str,
    content: str,
    *,
    city: str | None = None,
    days: int | None = None,
    places: list[dict] | None = None,
    budget_min: int | None = None,
    budget_max: int | None = None,
    travel_style: str | None = None,
) -> dict:
    """把攻略整理成前端和规划链路都能直接消费的结构化结果。"""
    cleaned = clean_text(content)
    resolved_city = city or infer_city(title, cleaned)
    resolved_days = days if days is not None else infer_days(f"{title}\n{cleaned}")
    resolved_places = places if places is not None else infer_places(cleaned, resolved_city)
    scenic_spots = unique_compact_list([place["name"] for place in resolved_places if place.get("type") == "scenic"], limit=10)
    food_spots = unique_compact_list([place["name"] for place in resolved_places if place.get("type") == "food"], limit=10)
    inferred_budget_min, inferred_budget_max = infer_budget_range(cleaned)
    resolved_budget_min = budget_min if budget_min is not None else inferred_budget_min
    resolved_budget_max = budget_max if budget_max is not None else inferred_budget_max
    travel_style_tags = infer_travel_style_tags(f"{title}\n{cleaned}")
    if travel_style:
        travel_style_tags = unique_compact_list(travel_style_tags + [item for item in travel_style.split(",") if item.strip()], limit=10)
    transport_modes = infer_transport_modes(cleaned)
    lodging_suggestions = infer_lodging_suggestions(cleaned)

    if resolved_budget_min and resolved_budget_max:
        if resolved_budget_min == resolved_budget_max:
            budget_range = f"约{resolved_budget_min}元"
        else:
            budget_range = f"{resolved_budget_min}-{resolved_budget_max}元"
    else:
        budget_range = None

    return {
        "city": resolved_city,
        "days": resolved_days,
        "summary": build_summary(cleaned),
        "budget_min": resolved_budget_min,
        "budget_max": resolved_budget_max,
        "budget_range": budget_range,
        "transport_modes": transport_modes,
        "lodging_suggestions": lodging_suggestions,
        "travel_style_tags": travel_style_tags,
        "scenic_spots": scenic_spots,
        "food_spots": food_spots,
        "places": resolved_places,
    }


class GuideIngestService:
    """攻略入库服务，负责结构化抽取、切片和向量索引。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def add_guide(
        self,
        payload: GuideCreateRequest,
        structured_override: dict | None = None,
        source_metadata_override: dict | None = None,
    ) -> dict:
        """新增攻略并写入 SQLite 与向量索引。"""
        cleaned = clean_text(payload.content)
        structured = build_structured_guide_data(payload.title, cleaned)
        if structured_override:
            structured = self._merge_structured_data(structured, structured_override)
        city = structured["city"]
        days = structured["days"]
        places = structured["places"]
        summary = structured["summary"]
        travel_style_tags = structured["travel_style_tags"]
        vector_chunks: list[dict] = []
        source_metadata_override = source_metadata_override or {}
        author = source_metadata_override.get("author") or payload.author

        source = GuideSource(
            source_type=payload.source_type,
            source_url=payload.source_url,
            raw_url=payload.raw_url or payload.source_url,
            resolved_url=payload.resolved_url or payload.source_url,
            category=payload.category,
            crawl_status=payload.crawl_status,
            title=payload.title,
            author=author,
            raw_text=cleaned,
            # 中文注释：这里保留来源说明，方便后续答辩和生产化溯源。
            license_note="用户添加或课程演示数据，回答时请保留来源说明。",
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
            budget_min=structured["budget_min"],
            budget_max=structured["budget_max"],
            travel_style=",".join(travel_style_tags) if travel_style_tags else None,
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
                "travel_style_tags": travel_style_tags,
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
            "extracted": structured,
        }

    def update_guide(self, guide_id: int, payload: GuideUpdateRequest) -> dict | None:
        """更新已入库攻略，并同步重建地点、切片和向量索引。"""
        guide = self.db.get(Guide, guide_id)
        if not guide:
            return None

        source = self.db.get(GuideSource, guide.source_id)
        if not source:
            return None

        cleaned = clean_text(payload.content)
        structured = build_structured_guide_data(payload.title, cleaned)
        if payload.structured:
            structured = self._merge_structured_data(structured, self._normalize_structured_override(payload.structured))

        city = structured["city"]
        travel_style_tags = structured["travel_style_tags"]
        places = structured["places"]

        old_chunk_ids = [
            chunk_id
            for (chunk_id,) in self.db.query(GuideChunk.id).filter(GuideChunk.guide_id == guide.id).all()
        ]

        source.title = payload.title
        source.raw_text = cleaned
        source.category = payload.category
        source.author = payload.author
        if payload.source_url is not None:
            source.source_url = payload.source_url
            source.resolved_url = payload.source_url
        source.crawl_status = "indexed"

        guide.title = payload.title
        guide.city = city
        guide.days = structured["days"]
        guide.budget_min = structured["budget_min"]
        guide.budget_max = structured["budget_max"]
        guide.travel_style = ",".join(travel_style_tags) if travel_style_tags else None
        guide.summary = structured["summary"]
        guide.status = "active"
        guide.updated_at = utc_now()

        self.db.query(Place).filter(Place.guide_id == guide.id).delete(synchronize_session=False)
        self.db.query(GuideChunk).filter(GuideChunk.guide_id == guide.id).delete(synchronize_session=False)
        self.db.flush()

        for place in places:
            self.db.add(
                Place(
                    guide_id=guide.id,
                    name=place["name"],
                    city=city,
                    place_type=place.get("type") or "scenic",
                )
            )

        vector_chunks: list[dict] = []
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
                "travel_style_tags": travel_style_tags,
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

        self.db.commit()
        vector_store = VectorStoreService()
        vector_deleted = vector_store.delete_chunks(old_chunk_ids)
        vector_indexed = vector_store.index_chunks(vector_chunks)
        return {
            "guide_id": guide.id,
            "city": city,
            "chunks": len(chunks),
            "indexed": vector_indexed,
            "old_vectors_deleted": vector_deleted,
            "extracted": structured,
        }

    def _merge_structured_data(self, base: dict, override: dict) -> dict:
        """合并规则抽取结果和外部补强结果。"""
        merged = dict(base)
        for key, value in override.items():
            if value in (None, "", []):
                continue
            if key == "places" and isinstance(value, list):
                merged[key] = value
                merged["scenic_spots"] = [item["name"] for item in value if item.get("type") == "scenic"]
                merged["food_spots"] = [item["name"] for item in value if item.get("type") == "food"]
                continue
            merged[key] = value
        if merged.get("budget_min") and merged.get("budget_max"):
            if merged["budget_min"] == merged["budget_max"]:
                merged["budget_range"] = f"约{merged['budget_min']}元"
            else:
                merged["budget_range"] = f"{merged['budget_min']}-{merged['budget_max']}元"
        return merged

    def _normalize_structured_override(self, override: dict) -> dict:
        """把前端结构化草稿整理成入库服务内部统一格式。"""
        normalized = dict(override)
        scenic_spots = normalized.get("scenic_spots") or []
        food_spots = normalized.get("food_spots") or []
        places = normalized.get("places")
        if not places and (scenic_spots or food_spots):
            normalized["places"] = [
                *[{"name": name, "type": "scenic"} for name in scenic_spots if name],
                *[{"name": name, "type": "food"} for name in food_spots if name],
            ]
        return normalized
