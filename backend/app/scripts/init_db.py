from app.db.session import init_db


if __name__ == "__main__":
    # 本脚本用于手动初始化数据库，start.bat 也会间接触发建表。
    init_db()
    print("数据库初始化完成")

