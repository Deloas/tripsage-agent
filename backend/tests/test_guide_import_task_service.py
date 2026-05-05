from app.schemas.guides import GuideLinkImportRequest
from app.services.guide_import_task_service import GuideImportTaskService


def test_create_and_update_import_task(db_session) -> None:
    """导入任务应能完整记录排队、运行、完成状态，供前端轮询展示。"""
    service = GuideImportTaskService(db_session)
    task = service.create_preview_task(
        GuideLinkImportRequest(url="https://example.com/guide", category="测试攻略")
    )

    assert task["status"] == "queued"
    assert task["progress"] == 5
    assert task["category"] == "测试攻略"

    service.mark_running(task["id"], stage="fetching", progress=24, message="正在抓取")
    running = service.get_task(task["id"])
    assert running is not None
    assert running["status"] == "running"
    assert running["stage"] == "fetching"
    assert running["progress"] == 24

    service.mark_succeeded(task["id"], {"status": "preview_ready", "title": "苏州攻略", "content": "正文"})
    finished = service.get_task(task["id"])
    assert finished is not None
    assert finished["status"] == "succeeded"
    assert finished["progress"] == 100
    assert finished["result"]["title"] == "苏州攻略"
    assert finished["finished_at"]


def test_list_import_tasks_orders_latest_first(db_session) -> None:
    """任务中心应优先展示最新任务。"""
    service = GuideImportTaskService(db_session)
    first = service.create_preview_task(GuideLinkImportRequest(url="https://example.com/one"))
    second = service.create_preview_task(GuideLinkImportRequest(url="https://example.com/two"))

    items, total = service.list_tasks(limit=10, offset=0)

    assert total == 2
    assert [item["id"] for item in items] == [second["id"], first["id"]]
