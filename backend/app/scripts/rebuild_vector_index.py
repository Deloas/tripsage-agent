import json

from app.db.models import Guide, GuideChunk, GuideSource
from app.db.session import SessionLocal, init_db
from app.services.vector_store_service import VectorStoreService


def main() -> None:
    """从 SQLite 中读取全部攻略切片，重建 Chroma 向量索引。"""
    init_db()
    db = SessionLocal()
    try:
        vector_store = VectorStoreService()
        vector_store.reset()
        rows = (
            db.query(GuideChunk, Guide, GuideSource)
            .join(Guide, Guide.id == GuideChunk.guide_id)
            .join(GuideSource, GuideSource.id == Guide.source_id)
            .all()
        )
        chunks = []
        for chunk, guide, source in rows:
            metadata = {
                "guide_id": guide.id,
                "title": guide.title,
                "city": guide.city,
                "source_url": source.source_url,
                "source_type": source.source_type,
            }
            if chunk.metadata_json:
                try:
                    metadata.update(json.loads(chunk.metadata_json))
                except json.JSONDecodeError:
                    pass
            chunks.append({"id": chunk.id, "content": chunk.content, "metadata": metadata})

        ok = vector_store.index_chunks(chunks)
        print({"chunks": len(chunks), "indexed": ok})
    finally:
        db.close()


if __name__ == "__main__":
    # 用于首次安装依赖后或导入大量攻略后，重新生成本地向量索引。
    main()

