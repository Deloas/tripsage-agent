import asyncio

from app.schemas.guides import GuideCreateRequest, GuideLinkImportRequest
from app.schemas.guides import GuideLinkImportConfirmRequest
from app.services.guide_ingest_service import GuideIngestService
from app.services.guide_link_import_service import FetchedGuidePage, GuideLinkImportService
from app.services.vector_store_service import VectorStoreService


SAMPLE_HTML = """
<html>
  <head>
    <title>苏州两天一夜攻略 - 城市旅行笔记</title>
    <meta name="author" content="旅行研究所" />
  </head>
  <body>
    <header>扫码登录查看更多</header>
    <article>
      <h1>苏州两天一夜攻略</h1>
      <p>预算大约 900-1200 元，适合周末轻松出行。</p>
      <p>第一天去拙政园、苏州博物馆和平江路，晚上吃苏帮菜。</p>
      <p>第二天去虎丘和山塘街，地铁与打车都很方便。</p>
      <p>推荐住在平江路附近或观前街商圈。</p>
    </article>
    <footer>版权所有</footer>
  </body>
</html>
"""

WEIBO_WALL_HTML = """
<!DOCTYPE html>
<html>
  <head>
    <title>Sina Visitor System</title>
  </head>
  <body>
    <div>登录注册更精彩</div>
  </body>
</html>
"""


def test_extract_main_content_prefers_article_and_removes_noise(db_session) -> None:
    """正文抽取应保留攻略主体并剔除登录、版权等噪音。"""
    service = GuideLinkImportService(db_session)

    content = service._extract_main_content(SAMPLE_HTML)

    assert "苏州两天一夜攻略" in content
    assert "拙政园" in content
    assert "扫码登录" not in content
    assert "版权所有" not in content


def test_import_link_indexes_valid_page(db_session, monkeypatch) -> None:
    """公开攻略链接应完成抓取、结构化增强和入库。"""
    monkeypatch.setattr(VectorStoreService, "index_chunks", lambda self, chunks: True)

    async def fake_fetch(self, url: str, source_type: str) -> FetchedGuidePage:
        return FetchedGuidePage(
            requested_url=url,
            resolved_url="https://example.com/suzhou-guide",
            html_text=SAMPLE_HTML,
            status_code=200,
            content_type="text/html",
            fetch_method="httpx",
        )

    async def fake_llm_hint(self, **kwargs):
        return {
            "normalized_title": "苏州两天一夜周末攻略",
            "city": "苏州",
            "days": 2,
            "budget_min": 900,
            "budget_max": 1200,
            "category": "苏州",
            "author": "旅行研究所",
            "travel_style_tags": ["轻松", "美食"],
            "transport_modes": ["地铁", "打车"],
            "lodging_suggestions": ["住在平江路附近", "住在观前街商圈"],
            "scenic_spots": ["拙政园", "苏州博物馆", "平江路", "虎丘", "山塘街"],
            "food_spots": ["苏帮菜"],
            "summary": "适合周末高铁出行的苏州两天一夜路线。",
        }

    monkeypatch.setattr(GuideLinkImportService, "_fetch_public_page", fake_fetch)
    monkeypatch.setattr(GuideLinkImportService, "_build_llm_structured_hint", fake_llm_hint)

    service = GuideLinkImportService(db_session)
    result = asyncio.run(service.import_link(GuideLinkImportRequest(url="https://example.com/suzhou-guide")))

    assert result["status"] == "indexed"
    assert result["city"] == "苏州"
    assert result["source_type"] == "web_link"
    assert result["llm_enhanced"] is True
    assert result["quality"]["score"] >= 65
    assert result["diagnostics"]["fetch_method"] == "httpx"
    assert result["guide"]["title"] == "苏州两天一夜周末攻略"
    assert "拙政园" in result["guide"]["content"]


def test_import_link_detects_duplicate_url(db_session, monkeypatch) -> None:
    """同一链接重复导入时应直接命中已有攻略，不再重复入库。"""
    monkeypatch.setattr(VectorStoreService, "index_chunks", lambda self, chunks: True)
    GuideIngestService(db_session).add_guide(
        GuideCreateRequest(
            title="苏州基础攻略",
            content="苏州两天一夜攻略，预算 800 元，第一天平江路，第二天虎丘，适合轻松慢游。",
            source_url="https://example.com/repeat-guide",
            raw_url="https://example.com/repeat-guide",
            resolved_url="https://example.com/repeat-guide",
        )
    )

    service = GuideLinkImportService(db_session)
    result = asyncio.run(service.import_link(GuideLinkImportRequest(url="https://example.com/repeat-guide")))

    assert result["status"] == "duplicate"
    assert result["reason"] == "url"
    assert result["guide"]["title"] == "苏州基础攻略"


def test_import_link_uses_browser_fallback_for_weibo_wall(db_session, monkeypatch) -> None:
    """微博访客墙命中后，应允许浏览器渲染兜底拿到正文。"""
    monkeypatch.setattr(VectorStoreService, "index_chunks", lambda self, chunks: True)

    async def fake_single_fetch(self, url: str) -> FetchedGuidePage:
        return FetchedGuidePage(
            requested_url=url,
            resolved_url="https://visitor.passport.weibo.cn/visitor/visitor",
            html_text=WEIBO_WALL_HTML,
            status_code=200,
            content_type="text/html",
            fetch_method="httpx",
        )

    async def fake_browser_fetch(self, candidates: list[str]) -> FetchedGuidePage:
        return FetchedGuidePage(
            requested_url=candidates[0],
            resolved_url="https://m.weibo.cn/status/5286261986169693",
            html_text=(
                "<html><head><title>南京两日攻略</title></head>"
                "<body><article>南京两日攻略 预算 1200 元，适合周末轻松出行。"
                "第一天从新街口出发，先去夫子庙、老门东和秦淮河夜游，晚饭可以安排南京大牌档。"
                "第二天去钟山风景区、明孝陵和音乐台，推荐全程地铁加步行，住宿优先选择新街口或苜蓿园附近。</article></body></html>"
            ),
            status_code=200,
            content_type="text/html",
            fetch_method="browser_render",
            attempts=[
                {
                    "method": "browser_render",
                    "requested_url": candidates[0],
                    "resolved_url": "https://m.weibo.cn/status/5286261986169693",
                    "status_code": 200,
                    "content_type": "text/html",
                    "issue_code": None,
                }
            ],
        )

    monkeypatch.setattr(GuideLinkImportService, "_fetch_single_page", fake_single_fetch)
    monkeypatch.setattr(GuideLinkImportService, "_fetch_with_browser_render", fake_browser_fetch)
    monkeypatch.setattr(GuideLinkImportService, "_fetch_with_node_render", lambda self, candidates: None)

    service = GuideLinkImportService(db_session)
    result = asyncio.run(
        service.import_link(
            GuideLinkImportRequest(url="https://weibo.com/6549236920/5286261986169693", force_reimport=True)
        )
    )

    assert result["status"] == "indexed"
    assert result["source_type"] == "weibo_link"
    assert result["diagnostics"]["fetch_method"] == "browser_render"
    assert result["quality"]["content_length"] >= 30


def test_import_link_uses_node_render_fallback_for_weibo_wall(db_session, monkeypatch) -> None:
    """当 Python 浏览器兜底不可用时，微博导入应继续尝试 Node 渲染兜底。"""
    monkeypatch.setattr(VectorStoreService, "index_chunks", lambda self, chunks: True)

    async def fake_single_fetch(self, url: str) -> FetchedGuidePage:
        return FetchedGuidePage(
            requested_url=url,
            resolved_url="https://visitor.passport.weibo.cn/visitor/visitor",
            html_text=WEIBO_WALL_HTML,
            status_code=200,
            content_type="text/html",
            fetch_method="httpx",
        )

    async def fake_browser_fetch(self, candidates: list[str]) -> FetchedGuidePage | None:
        return None

    def fake_node_fetch(self, candidates: list[str]) -> FetchedGuidePage:
        return FetchedGuidePage(
            requested_url=candidates[0],
            resolved_url="https://weibo.com/3311493561/5198608074539115",
            html_text=(
                "<html><head><title>苏州暑假遛娃3日游攻略</title></head><body><article>"
                "一张图看懂苏州旅游，附暑假遛娃3日游攻略。"
                "第一天苏州博物馆西馆、寒山寺、留园、七里山塘。"
                "第二天虎丘、拙政园、狮子林、平江路。"
                "第三天艺圃、怡园、网师园、金鸡湖。"
                "观前街和平江路都适合住宿，整体路线适合亲子出行。"
                "</article></body></html>"
            ),
            status_code=200,
            content_type="text/html",
            fetch_method="browser_render_node",
            attempts=[
                {
                    "method": "browser_render_node",
                    "requested_url": candidates[0],
                    "resolved_url": "https://weibo.com/3311493561/5198608074539115",
                    "status_code": 200,
                    "content_type": "text/html",
                    "issue_code": None,
                }
            ],
        )

    monkeypatch.setattr(GuideLinkImportService, "_fetch_single_page", fake_single_fetch)
    monkeypatch.setattr(GuideLinkImportService, "_fetch_with_browser_render", fake_browser_fetch)
    monkeypatch.setattr(GuideLinkImportService, "_fetch_with_node_render", fake_node_fetch)

    service = GuideLinkImportService(db_session)
    result = asyncio.run(
        service.import_link(
            GuideLinkImportRequest(url="https://weibo.com/3311493561/5198608074539115", force_reimport=True)
        )
    )

    assert result["status"] == "indexed"
    assert result["diagnostics"]["fetch_method"] == "browser_render_node"
    assert result["quality"]["content_length"] >= 60


def test_import_link_returns_login_wall_pending_when_all_attempts_fail(db_session, monkeypatch) -> None:
    """若微博所有抓取方式都命中访客墙，应返回明确的待处理诊断。"""

    async def fake_single_fetch(self, url: str) -> FetchedGuidePage:
        return FetchedGuidePage(
            requested_url=url,
            resolved_url="https://visitor.passport.weibo.cn/visitor/visitor",
            html_text=WEIBO_WALL_HTML,
            status_code=200,
            content_type="text/html",
            fetch_method="httpx",
        )

    async def fake_browser_fetch(self, candidates: list[str]) -> FetchedGuidePage | None:
        return None

    monkeypatch.setattr(GuideLinkImportService, "_fetch_single_page", fake_single_fetch)
    monkeypatch.setattr(GuideLinkImportService, "_fetch_with_browser_render", fake_browser_fetch)
    monkeypatch.setattr(GuideLinkImportService, "_fetch_with_node_render", lambda self, candidates: None)

    service = GuideLinkImportService(db_session)
    result = asyncio.run(
        service.import_link(
            GuideLinkImportRequest(url="https://weibo.com/6549236920/5286261986169693", force_reimport=True)
        )
    )

    assert result["status"] == "pending"
    assert result["reason"] == "login_wall"
    assert result["diagnostics"]["attempt_count"] >= 1


def test_extract_weibo_status_id_prefers_post_id_over_user_id(db_session) -> None:
    """微博路径里同时出现用户 ID 与微博 ID 时，应优先取微博 ID。"""
    service = GuideLinkImportService(db_session)

    status_id = service._extract_weibo_status_id("https://weibo.com/6549236920/5286261986169693")

    assert status_id == "5286261986169693"


def test_weibo_browser_snapshot_prefers_post_body_and_author(db_session) -> None:
    """微博浏览器快照应只保留博主正文，并能从正文中提炼真实攻略标题。"""
    service = GuideLinkImportService(db_session)
    snapshot = service._compose_browser_snapshot_html(
        title="微博正文 - 微博",
        author="吃不胖的西西",
        visible_text=(
            "最美人间四月天\n"
            "杭州西湖一日游玩攻略\n"
            "✅游玩路线：\n龙翔桥C口→二公园码头→三潭印月→花港观鱼→断桥残雪\n"
            "🚇交通出行：\n乘坐地铁1号线到龙翔桥站C口出来，往南步行几分钟就到二公园码头。\n"
            "Live\n分享这条博文\n同时转发\n这是一条评论区内容，不应进入攻略正文。"
        ),
        raw_html="<main>推荐 热门推荐 微博热搜</main>",
    )

    content = service._extract_main_content(snapshot)
    title = service._derive_title_from_content("微博正文 - 微博", content, source_type="weibo_link")
    author = service._extract_author(snapshot)

    assert title == "杭州西湖一日游玩攻略"
    assert author == "吃不胖的西西"
    assert "二公园码头" in content
    assert "评论区内容" not in content
    assert "热门推荐" not in content


def test_ocr_enrichment_accepts_multiple_image_texts(db_session) -> None:
    """图片 OCR 兜底应兼容多图返回，并把有效文本合并回正文。"""

    class FakeOcr:
        def available(self) -> bool:
            return True

        def extract_from_images(self, image_urls, seed, limit=5):
            return [
                "杭州西湖一日游攻略，路线包含龙翔桥、三潭印月、花港观鱼和断桥残雪。",
                "交通建议乘坐地铁1号线，预算包含船票和雷峰塔门票。",
            ]

    service = GuideLinkImportService(db_session)
    service.ocr = FakeOcr()
    page = FetchedGuidePage(
        requested_url="https://weibo.com/6549236920/5286261986169693",
        resolved_url="https://weibo.com/6549236920/5286261986169693",
        html_text="<html></html>",
        status_code=200,
        content_type="text/html",
        image_urls=["https://wx1.sinaimg.cn/large/example.jpg"],
    )

    content = service._enrich_content_with_ocr("", page=page, url=page.resolved_url)

    assert "杭州西湖一日游攻略" in content
    assert "雷峰塔门票" in content


def test_extract_image_urls_collects_meta_and_img_sources(db_session) -> None:
    """原始 HTML 中的攻略配图链接也应被收集，不能只依赖浏览器渲染结果。"""
    service = GuideLinkImportService(db_session)
    html_text = """
    <html>
      <head><meta property="og:image" content="//wx1.sinaimg.cn/thumb180/example_a.jpg" /></head>
      <body>
        <img src="/images/guide_b.png" />
        <img data-src="https://cdn.example.com/guide_c.jpeg" />
      </body>
    </html>
    """

    image_urls = service._extract_image_urls(html_text, "https://weibo.com/example/post")

    assert image_urls[0].startswith("https://wx1.sinaimg.cn/large/")
    assert "https://weibo.com/images/guide_b.png" in image_urls
    assert "https://cdn.example.com/guide_c.jpeg" in image_urls


def test_ocr_enrichment_merges_image_text_for_mixed_content(db_session) -> None:
    """图文混排页面即使已有少量正文，也应把图片里的关键信息并回正文。"""

    class FakeOcr:
        def available(self) -> bool:
            return True

        def extract_from_images(self, image_urls, seed, limit=8):
            return [
                "西湖游船路线：龙翔桥地铁站C口 - 二公园码头 - 三潭印月 - 花港观鱼。",
                "门票与预算：游船55元，雷峰塔40元，建议预留半天步行时间。",
            ]

    service = GuideLinkImportService(db_session)
    service.ocr = FakeOcr()
    page = FetchedGuidePage(
        requested_url="https://weibo.com/demo/mixed",
        resolved_url="https://weibo.com/demo/mixed",
        html_text="<html></html>",
        status_code=200,
        content_type="text/html",
        image_urls=[
            "https://wx1.sinaimg.cn/large/guide_a.jpg",
            "https://wx1.sinaimg.cn/large/guide_b.jpg",
        ],
    )

    enriched = service._enrich_content_with_ocr(
        "杭州西湖一日游适合周末出发，正文里只有很短的简介。",
        page=page,
        url=page.resolved_url,
    )

    assert "图片OCR补充" in enriched
    assert "游船55元" in enriched
    assert "二公园码头" in enriched


def test_visual_enrichment_uses_llm_fallback_for_image_only_guide(db_session) -> None:
    """当 OCR 仍不足时，应允许多模态兜底把图片型攻略转成正文。"""

    class WeakOcr:
        def available(self) -> bool:
            return True

        def extract_from_images(self, image_urls, seed, limit=8):
            return ["杭州", "西湖"]

    class FakeVisionLlm:
        def configured(self) -> bool:
            return True

        async def vision_plain_chat(self, prompt, image_urls):
            return "杭州西湖一日游路线：龙翔桥地铁站出发，先去二公园码头坐船到三潭印月，再去花港观鱼和雷峰塔。预算约200元。"

    service = GuideLinkImportService(db_session)
    service.ocr = WeakOcr()
    service.llm = FakeVisionLlm()
    page = FetchedGuidePage(
        requested_url="https://weibo.com/demo/image-only",
        resolved_url="https://weibo.com/demo/image-only",
        html_text="<html></html>",
        status_code=200,
        content_type="text/html",
        image_urls=["https://wx1.sinaimg.cn/large/image_only.jpg"],
    )

    enriched, diagnostics = asyncio.run(
        service._enrich_content_with_visual_text(
            "",
            page=page,
            url=page.resolved_url,
            title="杭州西湖一日游攻略",
        )
    )

    assert diagnostics["vision_used"] is True
    assert diagnostics["vision_text_length"] > 20
    assert diagnostics["content_sources"] == ["vision"]
    assert diagnostics["vision_preview_lines"]
    assert "龙翔桥地铁站" in diagnostics["vision_preview_lines"][0]
    assert "龙翔桥地铁站" in enriched
    assert "预算约200元" in enriched


def test_extract_ocr_text_uses_more_images_for_long_image_guides(db_session, monkeypatch) -> None:
    """长图型攻略应放宽 OCR 覆盖范围，避免只识别前几张。"""

    captured: dict[str, int] = {}

    class SpyOcr:
        def available(self) -> bool:
            return True

        def extract_from_images(self, image_urls, seed, limit=5, **kwargs):
            captured["limit"] = limit
            captured["count"] = len(image_urls)
            return [
                "攻略第1页：苏州穷游路线包含平江路、苏州博物馆、山塘街和艺圃，适合多图长图攻略导入。",
                "攻略第2页：继续补充交通、预算、住宿、美食、门票预约和风险提醒，验证不会只识别前两张图。",
            ]

    service = GuideLinkImportService(db_session)
    service.ocr = SpyOcr()
    page = FetchedGuidePage(
        requested_url="https://weibo.com/demo/image-heavy",
        resolved_url="https://weibo.com/demo/image-heavy",
        html_text="<html></html>",
        status_code=200,
        content_type="text/html",
        image_urls=[f"https://wx1.sinaimg.cn/large/demo_{index}.jpg" for index in range(9)],
    )

    text = service._extract_ocr_text("", page=page, url=page.resolved_url)

    assert captured["count"] == 9
    assert captured["limit"] >= 9
    assert "攻略第1页" in text


def test_preview_link_returns_structured_review_draft(db_session, monkeypatch) -> None:
    """预览接口应返回可编辑的结构化校对草稿。"""

    async def fake_fetch(self, url: str, source_type: str) -> FetchedGuidePage:
        return FetchedGuidePage(
            requested_url=url,
            resolved_url=url,
                html_text=(
                    "<html><head><title>杭州西湖一日游玩攻略</title></head><body><article>"
                    "杭州西湖一日游玩攻略\n游玩路线：龙翔桥C口→二公园码头→三潭印月→花港观鱼→断桥残雪\n"
                    "交通建议乘坐地铁1号线。船票70元/人，旺季建议提前出发。"
                    "二公园码头适合先拍照，三潭印月是一元纸币打卡地，花港观鱼适合下午散步。"
                    "如果当天人多，可以减少雷峰塔排队时间，把重点放在西湖沿线步行和骑行。"
                    "</article></body></html>"
                ),
            status_code=200,
            content_type="text/html",
            fetch_method="browser_render",
        )

    monkeypatch.setattr(GuideLinkImportService, "_fetch_public_page", fake_fetch)

    service = GuideLinkImportService(db_session)
    result = asyncio.run(service.preview_link(GuideLinkImportRequest(url="https://weibo.com/6549236920/5286261986169693")))

    assert result["status"] == "preview_ready"
    assert result["structured"]["city"] == "杭州"
    assert "二公园码头" in result["structured"]["route_nodes"]
    assert result["structured"]["ticket_hints"]
    assert result["structured"]["risk_notes"]


def test_confirm_import_prefers_user_structured_override(db_session, monkeypatch) -> None:
    """确认入库应优先采用前端校对后的结构化字段。"""
    monkeypatch.setattr(VectorStoreService, "index_chunks", lambda self, chunks: True)

    service = GuideLinkImportService(db_session)
    result = asyncio.run(
        service.confirm_import(
            GuideLinkImportConfirmRequest(
                url="https://example.com/structured-guide",
                title="杭州西湖一日游玩攻略",
                content="杭州西湖一日游玩攻略。路线包含龙翔桥、三潭印月、花港观鱼和断桥残雪，船票70元。",
                category="杭州",
                structured={
                    "city": "杭州",
                    "days": 1,
                    "budget_min": 70,
                    "budget_max": 180,
                    "scenic_spots": ["龙翔桥", "三潭印月", "花港观鱼", "断桥残雪"],
                    "transport_modes": ["地铁", "步行"],
                    "risk_notes": ["旺季建议提前出发"],
                },
                force_reimport=True,
            )
        )
    )

    assert result["status"] == "indexed"
    assert result["extracted"]["city"] == "杭州"
    assert result["extracted"]["days"] == 1
    assert result["extracted"]["budget_min"] == 70
    assert "三潭印月" in result["extracted"]["scenic_spots"]
    assert "旺季建议提前出发" in result["extracted"]["risk_notes"]
def test_build_diagnostics_includes_image_preview_and_final_preview(db_session) -> None:
    """导入诊断应带上图片预览、原文片段和入库片段，供详情页直接展示。"""

    service = GuideLinkImportService(db_session)
    page = FetchedGuidePage(
        requested_url="https://example.com/import-preview",
        resolved_url="https://example.com/import-preview",
        html_text=(
            "<html><body><article>杭州西湖一日游攻略\n"
            "原文第一段：龙翔桥地铁站出发\n"
            "原文第二段：二公园码头到花港观鱼</article></body></html>"
        ),
        status_code=200,
        content_type="text/html",
        fetch_method="browser_render",
        attempts=[{"method": "browser_render", "status_code": 200}],
        image_urls=[
            "https://example.com/images/a.jpg",
            "https://example.com/images/b.jpg",
        ],
    )

    diagnostics = service._build_diagnostics(
        page,
        quality={"grade": "A"},
        visual_diagnostics={
            "ocr_preview_lines": ["图片补充：预算约 200 元"],
            "vision_preview_lines": ["图片识别：建议下午去雷峰塔"],
        },
        content="最终入库正文：龙翔桥地铁站出发，预算约 200 元",
    )

    assert diagnostics["image_urls"][0] == "https://example.com/images/a.jpg"
    assert diagnostics["source_preview_lines"]
    assert diagnostics["final_preview_lines"]
    assert any("图片补充" in line for line in diagnostics["source_preview_lines"])
