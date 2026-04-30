from app.db.session import SessionLocal, init_db
from app.services.bootstrap_service import BootstrapService


if __name__ == "__main__":
    # 手动执行时复用启动初始化逻辑，保证与 FastAPI 启动行为一致。
    init_db()
    db = SessionLocal()
    try:
        result = BootstrapService(db).seed_initial_guides()
        print(result)
        print("示例攻略导入完成")
    finally:
        db.close()
