import asyncio

from app.db.session import SessionLocal, init_db
from app.services.weibo_crawler_service import WEIBO_GUIDE_INDEX_URL, WeiboCrawlerService


async def main() -> None:
    """采集微博公开攻略入口并写入本地数据库。"""
    init_db()
    db = SessionLocal()
    try:
        result = await WeiboCrawlerService(db).crawl_index(WEIBO_GUIDE_INDEX_URL)
        print(result)
    finally:
        db.close()


if __name__ == "__main__":
    # 该脚本只抓取公开页面，不使用登录态；遇到登录墙时会保存 pending 状态。
    asyncio.run(main())

