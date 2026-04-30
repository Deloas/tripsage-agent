from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import settings
from app.core.response import ok
from app.db.models import Guide, GuideChunk, GuideSource
from app.db.session import SessionLocal, engine
from app.services.amap_service import AmapService
from app.services.llm_service import LlmService
from app.services.mcp_railway_service import McpRailwayService
from app.services.vector_store_service import VectorStoreService
from app.services.web_search_service import WebSearchService

router = APIRouter()


@router.get("/health")
def health_check():
    """后端健康检查。"""
    return ok({"status": "healthy", "version": settings.app_version})


@router.get("/tools/status")
def tools_status():
    """检查关键工具配置状态，前端顶部状态灯会使用该接口。"""
    railway = McpRailwayService().config_status()
    llm = LlmService()
    amap = AmapService()
    web_search = WebSearchService()
    return ok(
        {
            "llm": "configured" if llm.configured() else "demo",
            "amap": "configured" if amap.configured() else "demo",
            "mcp_12306": "configured" if railway["configured"] and railway["allow_live"] else "demo",
            "web_search": "configured" if web_search.enabled() else "demo",
            "vector_store": "sqlite_keyword_ready",
            "demo_mode": settings.demo_mode,
            "auto_seed_guides": settings.auto_seed_guides,
            "auto_rebuild_vector_index": settings.auto_rebuild_vector_index,
            "auto_crawl_weibo_on_startup": settings.auto_crawl_weibo_on_startup,
        }
    )


@router.get("/diagnostics")
def diagnostics():
    """运行诊断接口，展示数据库、向量库和关键配置状态。"""
    db = SessionLocal()
    try:
        database_ok = True
        try:
            db.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001
            database_ok = False

        guide_count = db.query(Guide).count() if database_ok else 0
        chunk_count = db.query(GuideChunk).count() if database_ok else 0
        source_count = db.query(GuideSource).count() if database_ok else 0
        pending_sources = (
            db.query(GuideSource).filter(GuideSource.crawl_status == "pending").count()
            if database_ok
            else 0
        )

        return ok(
            {
                "database": {
                    "ok": database_ok,
                    "url": settings.database_url,
                    "engine": str(engine.url).split("://")[0],
                },
                "knowledge_base": {
                    "guides": guide_count,
                    "chunks": chunk_count,
                    "sources": source_count,
                    "pending_sources": pending_sources,
                    "auto_seed_guides": settings.auto_seed_guides,
                },
                "vector_store": {
                    "available": VectorStoreService().available(),
                    "persist_dir": settings.chroma_persist_dir,
                    "auto_rebuild": settings.auto_rebuild_vector_index,
                },
                "external_tools": {
                    "llm": LlmService().config_status(),
                    "amap": AmapService().config_status(),
                    "mcp_12306_config": McpRailwayService().config_status(),
                    "web_search": WebSearchService().config_status(),
                },
            }
        )
    finally:
        db.close()


@router.get("/llm/ping")
async def llm_ping():
    """主动检查 DeepSeek 或 OpenAI-compatible 大模型接口。"""
    return ok(await LlmService().ping())
