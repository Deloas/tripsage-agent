from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import settings
from app.data.initial_guides import INITIAL_GUIDES, WEIBO_SOURCE_URL
from app.db.models import GuideChunk, GuideSource
from app.schemas.guides import GuideCreateRequest
from app.services.guide_ingest_service import GuideIngestService
from app.services.vector_store_service import VectorStoreService
from app.services.weibo_crawler_service import WeiboCrawlerService


class BootstrapService:
    """应用启动数据初始化服务，保证首次运行自动具备可检索攻略库。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    async def run(self) -> dict:
        """执行启动初始化：导入内置攻略、补建向量索引、可选采集微博。"""
        result = {
            "seed_inserted": 0,
            "seed_skipped": 0,
            "vector_rebuilt": False,
            "weibo_crawl": None,
        }

        if settings.auto_seed_guides:
            seed_result = self.seed_initial_guides()
            result.update(seed_result)

        if settings.auto_rebuild_vector_index:
            result["vector_rebuilt"] = self.rebuild_vector_index_if_needed()

        if settings.auto_crawl_weibo_on_startup:
            # 微博采集默认关闭，避免每次启动都产生联网请求；开启后也会按来源 URL 幂等跳过。
            result["weibo_crawl"] = await WeiboCrawlerService(self.db).crawl_index(WEIBO_SOURCE_URL)

        logger.info(f"启动数据初始化完成：{result}")
        return result

    def seed_initial_guides(self) -> dict:
        """幂等导入内置攻略数据，已存在同标题来源时跳过。"""
        service = GuideIngestService(self.db)
        inserted = 0
        skipped = 0
        for guide in INITIAL_GUIDES:
            if self._source_exists(guide):
                skipped += 1
                continue
            service.add_guide(guide)
            inserted += 1
        return {"seed_inserted": inserted, "seed_skipped": skipped}

    def rebuild_vector_index_if_needed(self) -> bool:
        """当向量库为空或刚导入数据时，按 SQLite 切片重建 Chroma 索引。"""
        chunks_count = self.db.query(GuideChunk).count()
        if chunks_count == 0:
            return False

        vector_store = VectorStoreService()
        rows = (
            self.db.query(GuideChunk)
            .order_by(GuideChunk.created_at.asc())
            .all()
        )
        vector_chunks = []
        for chunk in rows:
            metadata = {}
            if chunk.metadata_json:
                import json

                try:
                    metadata = json.loads(chunk.metadata_json)
                except json.JSONDecodeError:
                    metadata = {}
            vector_chunks.append({"id": chunk.id, "content": chunk.content, "metadata": metadata})

        return vector_store.index_chunks(vector_chunks)

    def _source_exists(self, guide: GuideCreateRequest) -> bool:
        """根据标题和来源类型判断内置攻略是否已经导入。"""
        return (
            self.db.query(GuideSource)
            .filter(GuideSource.title == guide.title)
            .filter(GuideSource.source_type.in_(["seed", "demo"]))
            .first()
            is not None
        )

