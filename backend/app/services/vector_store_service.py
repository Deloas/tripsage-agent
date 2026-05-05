import hashlib
import math
from pathlib import Path
from typing import Any

from app.core.config import settings


VECTOR_DIMENSION = 96


def simple_hash_embedding(text: str, dimension: int = VECTOR_DIMENSION) -> list[float]:
    """生成本地哈希向量，保证未配置外部 embedding 时也能演示向量检索。"""
    vector = [0.0] * dimension
    tokens = [token for token in text.replace("\n", " ").split(" ") if token]
    if not tokens:
        tokens = [text[i : i + 2] for i in range(0, min(len(text), 120), 2)]

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign

    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [round(value / norm, 6) for value in vector]


class VectorStoreService:
    """Chroma 向量库封装，导入失败时自动退化为空结果。"""

    collection_name = "travel_guides"

    def __init__(self) -> None:
        self.persist_dir = Path(settings.chroma_persist_dir)
        self._collection = None

    def available(self) -> bool:
        """判断 Chroma 是否可用。"""
        try:
            self._get_collection()
            return True
        except Exception:  # noqa: BLE001
            return False

    def index_chunks(self, chunks: list[dict[str, Any]]) -> bool:
        """写入攻略切片向量，失败时返回 False，不影响 SQLite 主流程。"""
        if not chunks:
            return True
        try:
            collection = self._get_collection()
            ids = [chunk["id"] for chunk in chunks]
            documents = [chunk["content"] for chunk in chunks]
            metadatas = [chunk["metadata"] for chunk in chunks]
            embeddings = [simple_hash_embedding(chunk["content"]) for chunk in chunks]
            collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embeddings,
            )
            return True
        except Exception:  # noqa: BLE001
            return False

    def delete_chunks(self, chunk_ids: list[str]) -> bool:
        """删除指定向量切片，用于攻略编辑后重建索引。"""
        if not chunk_ids:
            return True
        try:
            collection = self._get_collection()
            collection.delete(ids=chunk_ids)
            return True
        except Exception:  # noqa: BLE001
            return False

    def search(self, query: str, top_k: int = 5, city: str | None = None) -> list[dict[str, Any]]:
        """执行向量检索，返回 chunk_id 和归一化分数。"""
        try:
            collection = self._get_collection()
            where = {"city": city} if city else None
            result = collection.query(
                query_embeddings=[simple_hash_embedding(query)],
                n_results=top_k,
                where=where,
                include=["distances", "metadatas", "documents"],
            )
        except Exception:  # noqa: BLE001
            return []

        ids = (result.get("ids") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]

        hits: list[dict[str, Any]] = []
        for index, chunk_id in enumerate(ids):
            distance = distances[index] if index < len(distances) else 1.0
            hits.append(
                {
                    "chunk_id": chunk_id,
                    "score": round(1 / (1 + float(distance)), 4),
                    "metadata": metadatas[index] if index < len(metadatas) else {},
                    "content": documents[index] if index < len(documents) else "",
                }
            )
        return hits

    def reset(self) -> bool:
        """删除并重建 collection，用于重新生成索引。"""
        try:
            client = self._get_client()
            try:
                client.delete_collection(self.collection_name)
            except Exception:  # noqa: BLE001
                pass
            self._collection = client.get_or_create_collection(self.collection_name)
            return True
        except Exception:  # noqa: BLE001
            return False

    def _get_client(self):
        """延迟导入 Chroma，避免未安装依赖时影响后端基础编译。"""
        import chromadb

        self.persist_dir.mkdir(parents=True, exist_ok=True)
        return chromadb.PersistentClient(path=str(self.persist_dir))

    def _get_collection(self):
        """获取或创建 Chroma collection。"""
        if self._collection is not None:
            return self._collection
        client = self._get_client()
        self._collection = client.get_or_create_collection(self.collection_name)
        return self._collection
