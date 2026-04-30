from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, guides, health, plans, tools, workspace
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.db.session import init_db
from app.services.bootstrap_service import BootstrapService


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期钩子，负责启动阶段的数据库与攻略库初始化。"""
    # 启动时自动建表和导入内置攻略，保证首次运行就有可检索数据。
    init_db()
    db = SessionLocal()
    try:
        await BootstrapService(db).run()
    finally:
        db.close()
    yield


def create_app() -> FastAPI:
    """创建 FastAPI 应用，并集中注册中间件、路由和启动任务。"""
    configure_logging()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="基于攻略知识库、12306 MCP、天气和地图工具的旅游攻略智能体。",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(chat.router, prefix="/api", tags=["chat"])
    app.include_router(guides.router, prefix="/api", tags=["guides"])
    app.include_router(plans.router, prefix="/api", tags=["plans"])
    app.include_router(tools.router, prefix="/api", tags=["tools"])
    app.include_router(workspace.router, prefix="/api", tags=["workspace"])
    return app


app = create_app()
