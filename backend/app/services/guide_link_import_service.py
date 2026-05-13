import asyncio
import html
import json
import re
import subprocess
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import ROOT_DIR
from app.db.models import Guide, GuideImportRecord, GuideImportTask, GuideSource
from app.schemas.guides import GuideCreateRequest, GuideLinkImportConfirmRequest, GuideLinkImportRequest
from app.services.guide_ocr_service import GuideOcrService
from app.services.guide_ingest_service import (
    GuideIngestService,
    build_structured_guide_data,
    clean_text,
    infer_city,
    infer_days,
)
from app.services.llm_service import LlmService
from app.services.rag_service import RagService


TRAVEL_IMPORT_TERMS = [
    "攻略",
    "旅行",
    "旅游",
    "景点",
    "路线",
    "行程",
    "住宿",
    "美食",
    "高铁",
    "火车",
    "地铁",
    "预算",
]

NOISE_PATTERNS = [
    r"登录后即可查看.*",
    r"扫码登录.*",
    r"打开APP.*",
    r"版权所有.*",
    r"未经授权.*转载",
    r"点击展开全文.*",
    r"微博访客系统.*",
]

BLOCKED_PAGE_MARKERS = [
    "Sina Visitor System",
    "visitor/passport",
    "visitor/visitor",
    "登录注册更精彩",
    "安全验证",
    "请输入验证码",
    "passport.weibo.com",
]

WEIBO_TRACKING_QUERY_KEYS = {
    "from",
    "jumpfrom",
    "type",
    "wm",
    "weiboauthoruid",
    "featurecode",
    "luicode",
    "lfid",
    "sudaref",
}

BLOCKED_TITLE_KEYWORDS = {
    "Sina Visitor System",
    "微博访客系统",
    "Visitor",
}


WEIBO_RENDERED_FETCHER_PATH = ROOT_DIR / "backend" / "app" / "scripts" / "weibo_rendered_fetcher.cjs"


@dataclass
class FetchedGuidePage:
    """统一承载网页抓取结果，便于后续抽取、诊断与测试。"""

    requested_url: str
    resolved_url: str
    html_text: str
    status_code: int
    content_type: str
    fetch_method: str = "httpx"
    issue_code: str | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)
    image_urls: list[str] = field(default_factory=list)


class GuideLinkImportService:
    """通用攻略链接导入服务。

    支持任意公开网页导入，同时对微博这类存在访客墙的来源追加多路 URL 尝试
    和浏览器渲染兜底，尽量把“浏览器能看、程序拿不到”的情况收窄。
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.llm = LlmService()
        self.ocr = GuideOcrService()

    async def import_link(self, payload: GuideLinkImportRequest) -> dict[str, Any]:
        """导入单条公开攻略链接。"""
        normalized_url = self._normalize_url(payload.url)
        source_type = self._detect_source_type(normalized_url)

        existing = self._find_duplicate_by_url(normalized_url)
        if existing and not payload.force_reimport:
            result = self._build_duplicate_result(existing, reason="url")
            return self._save_import_record(normalized_url, result, mode="link")

        page = await self._fetch_public_page(normalized_url, source_type=source_type)
        title = self._sanitize_title(
            self._extract_title(page.html_text, page.resolved_url),
            source_type=source_type,
            issue_code=page.issue_code,
        )
        author = self._extract_author(page.html_text)
        content = self._extract_main_content(page.html_text)
        content, visual_diagnostics = await self._enrich_content_with_visual_text(
            content,
            page=page,
            url=normalized_url,
            title=title,
        )
        title = self._derive_title_from_content(title, content, source_type=source_type)
        category = payload.category or self._detect_category(title, page.resolved_url, content)

        quality = self._assess_quality(
            title=title,
            content=content,
            url=page.resolved_url,
            html_text=page.html_text,
            issue_code=page.issue_code,
        )
        diagnostics = self._build_diagnostics(
            page,
            quality=quality,
            visual_diagnostics=visual_diagnostics,
            content=content,
        )

        duplicate = self._find_duplicate_by_content(title=title, content=content)
        if duplicate and not payload.force_reimport:
            result = self._build_duplicate_result(
                duplicate,
                reason="content",
                quality=quality,
                diagnostics=diagnostics,
            )
            return self._save_import_record(normalized_url, result, mode="link")

        content_compact_length = len(re.sub(r"\s+", "", content))
        if content_compact_length < 90 and quality["score"] < 55:
            pending = self._save_pending_source(
                title=title,
                raw_url=normalized_url,
                resolved_url=page.resolved_url,
                source_type=source_type,
                category=category,
                author=author,
                raw_text=content or None,
                note=self._build_pending_license_note(page.issue_code),
            )
            result = {
                "status": "pending",
                "reason": page.issue_code or "content_too_short",
                "source_id": pending.id,
                "title": title,
                "source_type": source_type,
                "resolved_url": page.resolved_url,
                "quality": quality,
                "diagnostics": diagnostics,
                "message": self._build_pending_message(page.issue_code),
            }
            return self._save_import_record(normalized_url, result, mode="link")

        llm_hint = await self._build_llm_structured_hint(
            title=title,
            content=content,
            url=page.resolved_url,
            category=category,
            author=author,
        )
        override = self._build_structured_override(title=title, content=content, llm_hint=llm_hint)

        try:
            result = GuideIngestService(self.db).add_guide(
                GuideCreateRequest(
                    title=(llm_hint.get("normalized_title") if llm_hint else None) or title,
                    content=content,
                    source_url=page.resolved_url,
                    source_type=source_type,
                    category=(llm_hint.get("category") if llm_hint else None) or category,
                    raw_url=normalized_url,
                    resolved_url=page.resolved_url,
                    crawl_status="indexed",
                    author=(llm_hint.get("author") if llm_hint else None) or author,
                ),
                structured_override=override,
                source_metadata_override={
                    "author": (llm_hint.get("author") if llm_hint else None) or author,
                },
            )
        except IntegrityError:
            # 中文注释：强制重导入时若正文切片完全一致，SQLite 的唯一哈希约束会拦下重复内容。
            # 这里回滚后降级成“重复攻略”结果，避免接口抛 500。
            self.db.rollback()
            existing = (
                self._find_duplicate_by_content(title=title, content=content)
                or self._find_duplicate_by_url(page.resolved_url)
                or self._find_duplicate_by_url(normalized_url)
            )
            if existing:
                result = self._build_duplicate_result(
                    existing,
                    reason="content_hash",
                    quality=quality,
                    diagnostics=diagnostics,
                )
                return self._save_import_record(normalized_url, result, mode="link")
            raise
        result = {
            **result,
            "status": "indexed",
            "import_mode": "link",
            "title": (llm_hint.get("normalized_title") if llm_hint else None) or title,
            "source_type": source_type,
            "resolved_url": page.resolved_url,
            "content": content,
            "structured": self._build_structured_review_draft(title=title, content=content),
            "quality": quality,
            "diagnostics": diagnostics,
            "llm_enhanced": bool(llm_hint),
            "duplicate": None,
            "guide": self._get_guide_detail(result.get("guide_id")),
        }
        return self._save_import_record(normalized_url, result, mode="link")

    async def preview_link(self, payload: GuideLinkImportRequest) -> dict[str, Any]:
        """抓取链接并返回可编辑预览，不立即写入正式攻略库。"""
        normalized_url = self._normalize_url(payload.url)
        source_type = self._detect_source_type(normalized_url)
        page = await self._fetch_public_page(normalized_url, source_type=source_type)
        title = self._sanitize_title(
            self._extract_title(page.html_text, page.resolved_url),
            source_type=source_type,
            issue_code=page.issue_code,
        )
        author = self._extract_author(page.html_text)
        content = self._extract_main_content(page.html_text)
        content, visual_diagnostics = await self._enrich_content_with_visual_text(
            content,
            page=page,
            url=normalized_url,
            title=title,
        )
        title = self._derive_title_from_content(title, content, source_type=source_type)
        category = payload.category or self._detect_category(title, page.resolved_url, content)
        structured_preview = self._build_structured_review_draft(title=title, content=content)
        quality = self._assess_quality(
            title=title,
            content=content,
            url=page.resolved_url,
            html_text=page.html_text,
            issue_code=page.issue_code,
        )
        diagnostics = self._build_diagnostics(
            page,
            quality=quality,
            visual_diagnostics=visual_diagnostics,
            content=content,
        )
        compact_length = len(re.sub(r"\s+", "", content))
        status = "preview_ready" if compact_length >= 90 or quality["score"] >= 55 else "pending"
        result = {
            "status": status,
            "reason": None if status == "preview_ready" else page.issue_code or "content_too_short",
            "title": title,
            "content": content,
            "category": category,
            "source_type": source_type,
            "resolved_url": page.resolved_url,
            "author": author,
            "structured": structured_preview,
            "quality": quality,
            "diagnostics": diagnostics,
            "message": "已抓取到可编辑攻略预览。" if status == "preview_ready" else self._build_pending_message(page.issue_code),
        }
        return self._save_import_record(normalized_url, result, mode="preview")

    async def confirm_import(self, payload: GuideLinkImportConfirmRequest) -> dict[str, Any]:
        """将用户确认或编辑后的攻略正式入库。"""
        normalized_url = self._normalize_url(payload.url)
        resolved_url = payload.resolved_url or normalized_url
        title = clean_text(payload.title)[:200] or "未命名导入攻略"
        content = clean_text(payload.content)
        source_type = payload.source_type or self._detect_source_type(normalized_url)
        quality = self._assess_quality(
            title=title,
            content=content,
            url=resolved_url,
            html_text=content,
            issue_code=None,
        )
        duplicate = self._find_duplicate_by_content(title=title, content=content)
        if duplicate and not payload.force_reimport:
            result = self._build_duplicate_result(
                duplicate,
                reason="content",
                quality=quality,
                diagnostics={"fetch_method": "editable_confirm", "quality_grade": quality["grade"]},
            )
            return self._save_import_record(normalized_url, result, mode="confirm")

        user_structured = self._normalize_structured_override(payload.structured)
        llm_hint = await self._build_llm_structured_hint(
            title=title,
            content=content,
            url=resolved_url,
            category=payload.category or "用户确认导入",
            author=payload.author,
        )
        llm_override = self._build_structured_override(title=title, content=content, llm_hint=llm_hint)
        override = self._merge_structured_overrides(llm_override, user_structured)
        result = GuideIngestService(self.db).add_guide(
            GuideCreateRequest(
                title=(llm_hint.get("normalized_title") if llm_hint else None) or title,
                content=content,
                source_url=resolved_url,
                source_type=source_type,
                category=(llm_hint.get("category") if llm_hint else None) or payload.category,
                raw_url=normalized_url,
                resolved_url=resolved_url,
                crawl_status="indexed",
                author=(llm_hint.get("author") if llm_hint else None) or payload.author,
            ),
            structured_override=override,
            source_metadata_override={
                "author": (llm_hint.get("author") if llm_hint else None) or payload.author,
            },
        )
        response = {
            **result,
            "status": "indexed",
            "import_mode": "confirm",
            "title": (llm_hint.get("normalized_title") if llm_hint else None) or title,
            "source_type": source_type,
            "resolved_url": resolved_url,
            "content": content,
            "structured": self._normalize_structured_override(override),
            "quality": quality,
            "diagnostics": {"fetch_method": "editable_confirm", "quality_grade": quality["grade"]},
            "llm_enhanced": bool(llm_hint),
            "duplicate": None,
            "guide": self._get_guide_detail(result.get("guide_id")),
        }
        return self._save_import_record(normalized_url, response, mode="confirm")

    def list_import_records(self, limit: int = 30, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        """返回攻略导入历史，供前端做导入结果中心。"""
        total = self.db.execute(select(func.count()).select_from(GuideImportRecord)).scalar_one()
        records = (
            self.db.execute(
                select(GuideImportRecord)
                .order_by(GuideImportRecord.id.desc())
                .offset(offset)
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return [self._record_to_dict(record) for record in records], int(total or 0)

    def get_import_record(self, record_id: int) -> dict[str, Any] | None:
        """中文注释：按记录 ID 拉取完整导入详情，供前端稳定重开历史记录。"""
        record = self.db.get(GuideImportRecord, record_id)
        if not record:
            return None
        return self._record_to_dict(record)

    def delete_import_record(self, record_id: int) -> dict[str, Any] | None:
        """删除单条导入记录；只清理导入历史，不删除已入库攻略正文。"""
        record = self.db.get(GuideImportRecord, record_id)
        if not record:
            return None
        result = self._record_to_dict(record)
        self.db.delete(record)
        self.db.commit()
        return {**result, "deleted": True}

    async def fetch_page_snapshot(self, url: str, source_type: str | None = None) -> FetchedGuidePage:
        """给其它服务复用的公开抓取入口。"""
        normalized_url = self._normalize_url(url)
        resolved_source_type = source_type or self._detect_source_type(normalized_url)
        return await self._fetch_public_page(normalized_url, source_type=resolved_source_type)

    async def _fetch_public_page(self, url: str, source_type: str) -> FetchedGuidePage:
        """抓取公开网页。

        先走轻量 HTTP 抓取；若命中微博等站点的访客墙，再尝试浏览器渲染。
        """
        attempts: list[dict[str, Any]] = []
        best_page: FetchedGuidePage | None = None
        candidates = self._build_fetch_candidates(url, source_type)

        for candidate in candidates:
            try:
                page = await self._fetch_single_page(candidate)
            except Exception as exc:  # noqa: BLE001
                attempts.append(
                    {
                        "method": "httpx",
                        "requested_url": candidate,
                        "resolved_url": candidate,
                        "status_code": 0,
                        "content_type": "",
                        "issue_code": "request_error",
                        "error": str(exc),
                    }
                )
                continue

            page.issue_code = self._detect_access_issue(
                html_text=page.html_text,
                resolved_url=page.resolved_url,
                status_code=page.status_code,
                content_type=page.content_type,
            )
            attempt = self._attempt_from_page(page)
            attempts.append(attempt)
            page.attempts = attempts.copy()

            if self._page_has_usable_public_content(page):
                return page
            if best_page is None or self._page_strength(page) > self._page_strength(best_page):
                best_page = page

        if source_type in {"weibo_link", "xiaohongshu_link"}:
            fallback_pages: list[FetchedGuidePage | None] = []
            if source_type == "weibo_link":
                # 中文注释：微博先走 Node 侧 Playwright 兜底，避免 Python 浏览器链路偶发失效时直接退回访客墙。
                fallback_pages.append(await asyncio.to_thread(self._fetch_with_node_render, candidates))
            fallback_pages.append(await self._fetch_with_browser_render(candidates))
            for rendered_page in fallback_pages:
                if not rendered_page:
                    continue
                attempts.extend(rendered_page.attempts)
                rendered_page.attempts = attempts.copy()
                if self._page_has_usable_public_content(rendered_page):
                    return rendered_page
                if best_page is None or self._page_strength(rendered_page) > self._page_strength(best_page):
                    best_page = rendered_page

        if best_page is not None:
            best_page.attempts = attempts
            return best_page

        raise RuntimeError("未能抓取到公开页面内容")

    async def _fetch_single_page(self, url: str) -> FetchedGuidePage:
        """使用普通 HTTP 请求抓取页面。"""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=headers) as client:
            response = await client.get(url)
            return FetchedGuidePage(
                requested_url=url,
                resolved_url=str(response.url),
                html_text=response.text,
                status_code=response.status_code,
                content_type=response.headers.get("content-type", ""),
                fetch_method="httpx",
                image_urls=self._extract_image_urls(response.text, str(response.url)),
            )

    async def _fetch_with_browser_render(self, candidates: list[str]) -> FetchedGuidePage | None:
        """使用真实浏览器渲染公开页，解决部分站点的访客页重定向问题。"""
        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError
            from playwright.async_api import async_playwright
        except ImportError:
            return None

        edge_path = self._find_edge_executable()
        launch_options: dict[str, Any] = {
            "headless": True,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        }
        if edge_path:
            launch_options["executable_path"] = edge_path
        else:
            launch_options["channel"] = "msedge"

        best_page: FetchedGuidePage | None = None
        attempts: list[dict[str, Any]] = []

        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(**launch_options)
                context = await browser.new_context(
                    locale="zh-CN",
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0 Safari/537.36"
                    ),
                    viewport={"width": 1440, "height": 2000},
                    java_script_enabled=True,
                )
                await context.add_init_script(
                    """
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    window.chrome = window.chrome || { runtime: {} };
                    Object.defineProperty(navigator, 'language', { get: () => 'zh-CN' });
                    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh'] });
                    """
                )

                found_page: FetchedGuidePage | None = None
                for candidate in candidates:
                    page = await context.new_page()
                    try:
                        response = await page.goto(candidate, wait_until="domcontentloaded", timeout=25000)
                        await page.wait_for_timeout(3500)
                        for _ in range(3):
                            if not self._url_looks_blocked(page.url):
                                break
                            await page.wait_for_timeout(1500)
                        await page.evaluate(
                            """
                            () => {
                              for (const node of Array.from(document.querySelectorAll('button, a, span, div'))) {
                                const text = (node.innerText || node.textContent || '').trim();
                                if (/^(展开|展开全文|全文)$/.test(text)) {
                                  try { node.click(); } catch {}
                                }
                              }
                            }
                            """
                        )
                        await page.wait_for_timeout(800)

                        html_text = await page.content()
                        page_title = await page.title()
                        extracted = await page.evaluate(
                            """
                            () => {
                              const clean = (value) => String(value || '')
                                .replace(/\\u00a0/g, ' ')
                                .replace(/[ \\t]+/g, ' ')
                                .replace(/\\n{3,}/g, '\\n\\n')
                                .trim();
                              const normalize = (value) => {
                                if (!value || typeof value !== 'string') return '';
                                let url = value.trim();
                                if (!url || url.startsWith('data:')) return '';
                                try { url = new URL(url, location.href).href; } catch { return ''; }
                                if (url.includes('sinaimg.cn')) {
                                  url = url.replace(/\\/thumb\\d+\\//, '/large/')
                                           .replace(/\\/orj\\d+\\//, '/large/')
                                           .replace(/\\/mw\\d+\\//, '/large/');
                                }
                                return url;
                              };
                              const collectImages = (root) => {
                                const urls = new Set();
                                for (const img of Array.from((root || document).querySelectorAll('img'))) {
                                  const rect = img.getBoundingClientRect();
                                  const candidates = [
                                    img.currentSrc,
                                    img.src,
                                    img.getAttribute('data-src'),
                                    img.getAttribute('data-original'),
                                    img.getAttribute('data-large'),
                                  ];
                                  for (const item of candidates) {
                                    const url = normalize(item);
                                    if (!url) continue;
                                    const useful = url.includes('sinaimg.cn')
                                      || url.includes('wx') || url.includes('mmbiz')
                                      || rect.width >= 160 || rect.height >= 160;
                                    if (useful) urls.add(url);
                                  }
                                }
                                return Array.from(urls).slice(0, 16);
                              };
                              const textOf = (node) => clean(node ? (node.innerText || node.textContent || '') : '');
                              const contentNodes = [
                                ...Array.from(document.querySelectorAll('.wbpro-feed-ogText, .wbpro-feed-content')),
                                ...Array.from(document.querySelectorAll('[class*="feed-content"], [class*="ogText"], [class*="Feed_body"]')),
                              ];
                              let bestNode = null;
                              let bestText = '';
                              for (const node of contentNodes) {
                                const text = textOf(node);
                                const chineseCount = (text.match(/[\\u4e00-\\u9fff]/g) || []).length;
                                const travelHit = /(攻略|路线|景点|门票|交通|住宿|美食|预算|游玩)/.test(text);
                                if (chineseCount >= 30 && (travelHit || chineseCount > bestText.length)) {
                                  if (!bestText || text.length > bestText.length) {
                                    bestNode = node;
                                    bestText = text;
                                  }
                                }
                              }
                              const article = bestNode ? bestNode.closest('article') : document.querySelector('article');
                              const articleText = textOf(article);
                              const lines = articleText.split(/\\n+/).map((item) => item.trim()).filter(Boolean);
                              let author = '';
                              const publicIndex = lines.findIndex((line) => line === '公开');
                              if (publicIndex >= 0 && lines[publicIndex + 1]) {
                                author = lines[publicIndex + 1];
                              }
                              if (!author) {
                                const maybeName = lines.find((line) => /^[\\u4e00-\\u9fffA-Za-z0-9_\\-]{2,24}$/.test(line) && !/关注|返回|公开/.test(line));
                                author = maybeName || '';
                              }
                              let text = bestText || articleText || textOf(document.body);
                              text = clean(text)
                                .replace(/^公开\\n?/, '')
                                .replace(/^关注\\n?/, '');
                              const contentLines = text.split(/\\n+/).map((item) => item.trim()).filter(Boolean);
                              const titleLine = contentLines.find((line) => /攻略|路线|游玩|旅行|旅游|一日|两日|三日/.test(line) && line.length <= 60)
                                || contentLines.find((line) => line.length >= 6 && line.length <= 60)
                                || '';
                              for (const img of Array.from(document.images || [])) {
                              }
                              return {
                                title: titleLine,
                                author,
                                text,
                                imageUrls: collectImages(article || document),
                              };
                            }
                            """
                        )
                        title = extracted.get("title") or page_title
                        author = extracted.get("author") or None
                        visible_text = extracted.get("text") or await page.evaluate(
                            "() => document.body ? document.body.innerText || '' : ''"
                        )
                        image_urls = extracted.get("imageUrls") or []
                        wrapped_html = self._compose_browser_snapshot_html(
                            title=title,
                            visible_text=visible_text,
                            raw_html=html_text,
                            author=author,
                        )
                        fetched = FetchedGuidePage(
                            requested_url=candidate,
                            resolved_url=page.url,
                            html_text=wrapped_html,
                            status_code=response.status if response else 200,
                            content_type=(response.headers.get("content-type", "") if response else "text/html"),
                            fetch_method="browser_render",
                            image_urls=image_urls or [],
                        )
                        fetched.issue_code = self._detect_access_issue(
                            html_text=fetched.html_text,
                            resolved_url=fetched.resolved_url,
                            status_code=fetched.status_code,
                            content_type=fetched.content_type,
                        )
                        attempt = self._attempt_from_page(fetched)
                        attempts.append(attempt)
                        fetched.attempts = [attempt]

                        if self._page_has_usable_public_content(fetched):
                            found_page = fetched
                            found_page.attempts = attempts.copy()
                            break
                        if best_page is None or self._page_strength(fetched) > self._page_strength(best_page):
                            best_page = fetched
                    except PlaywrightTimeoutError:
                        attempts.append(
                            {
                                "method": "browser_render",
                                "requested_url": candidate,
                                "resolved_url": page.url if page else candidate,
                                "status_code": 0,
                                "content_type": "",
                                "issue_code": "browser_timeout",
                            }
                        )
                    except Exception as exc:  # noqa: BLE001
                        attempts.append(
                            {
                                "method": "browser_render",
                                "requested_url": candidate,
                                "resolved_url": page.url if page else candidate,
                                "status_code": 0,
                                "content_type": "",
                                "issue_code": "browser_error",
                                "error": str(exc),
                            }
                        )
                    finally:
                        await page.close()

                await context.close()
                await browser.close()
                if found_page is not None:
                    return found_page
        except Exception:
            return None

        if best_page is not None:
            best_page.attempts = attempts
        return best_page

    def _fetch_with_node_render(self, candidates: list[str]) -> FetchedGuidePage | None:
        """使用 Node 侧 Playwright 作为微博渲染兜底，提升公开微博正文抓取稳定性。"""
        if not WEIBO_RENDERED_FETCHER_PATH.exists():
            return None

        best_page: FetchedGuidePage | None = None
        attempts: list[dict[str, Any]] = []
        for candidate in candidates:
            try:
                result = subprocess.run(
                    ["node", str(WEIBO_RENDERED_FETCHER_PATH), candidate],
                    cwd=str(ROOT_DIR),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=75,
                    check=False,
                )
                if result.returncode != 0:
                    attempts.append(
                        {
                            "method": "browser_render_node",
                            "requested_url": candidate,
                            "resolved_url": candidate,
                            "status_code": 0,
                            "content_type": "",
                            "issue_code": "node_browser_error",
                            "error": (result.stderr or result.stdout or "").strip()[:400],
                        }
                    )
                    continue

                payload = json.loads(result.stdout or "{}")
                page_title = (
                    clean_text(str(payload.get("postTitle") or ""))
                    or clean_text(str(payload.get("pageTitle") or ""))
                    or "微博正文 - 微博"
                )
                visible_text = str(payload.get("bodyText") or "")
                author = clean_text(str(payload.get("author") or "")) or None
                image_urls = [
                    normalized
                    for item in payload.get("imageUrls") or []
                    if isinstance(item, str)
                    for normalized in [self._normalize_image_url(item, candidate)]
                    if normalized
                ]
                fetched = FetchedGuidePage(
                    requested_url=candidate,
                    resolved_url=self._normalize_url(str(payload.get("finalUrl") or candidate)),
                    html_text=self._compose_browser_snapshot_html(
                        title=page_title,
                        visible_text=visible_text,
                        raw_html="",
                        author=author,
                    ),
                    status_code=200,
                    content_type="text/html",
                    fetch_method="browser_render_node",
                    image_urls=image_urls,
                )
                fetched.issue_code = self._detect_access_issue(
                    html_text=fetched.html_text,
                    resolved_url=fetched.resolved_url,
                    status_code=fetched.status_code,
                    content_type=fetched.content_type,
                )
                attempt = self._attempt_from_page(fetched)
                attempts.append(attempt)
                fetched.attempts = attempts.copy()
                if self._page_has_usable_public_content(fetched):
                    return fetched
                if best_page is None or self._page_strength(fetched) > self._page_strength(best_page):
                    best_page = fetched
            except Exception as exc:  # noqa: BLE001
                attempts.append(
                    {
                        "method": "browser_render_node",
                        "requested_url": candidate,
                        "resolved_url": candidate,
                        "status_code": 0,
                        "content_type": "",
                        "issue_code": "node_browser_error",
                        "error": str(exc)[:400],
                    }
                )

        if best_page is not None:
            best_page.attempts = attempts
        return best_page

    def _build_fetch_candidates(self, url: str, source_type: str) -> list[str]:
        """根据来源生成多条抓取候选 URL。"""
        candidates = [url]
        if source_type != "weibo_link":
            return self._unique_urls(candidates)

        status_id = self._extract_weibo_status_id(url)
        if status_id:
            # 中文注释：先尝试用户原始链接，保留平台真实正文结构；移动页作为访客墙后的补充兜底。
            candidates = [
                url,
                f"https://m.weibo.cn/status/{status_id}",
                f"https://m.weibo.cn/detail/{status_id}",
            ]
        return self._unique_urls(candidates)

    def _normalize_url(self, url: str) -> str:
        """统一清洗链接格式，减少重复入库与误判。"""
        compact = url.strip()
        if not compact.startswith(("http://", "https://")):
            compact = f"https://{compact}"

        parsed = urlsplit(compact)
        cleaned_netloc = parsed.netloc.lower()
        cleaned_query = parse_qsl(parsed.query, keep_blank_values=True)
        if "weibo.com" in cleaned_netloc or "m.weibo.cn" in cleaned_netloc:
            cleaned_query = [
                (key, value)
                for key, value in cleaned_query
                if key.lower() not in WEIBO_TRACKING_QUERY_KEYS
            ]
        normalized = urlunsplit(
            (
                parsed.scheme.lower() or "https",
                cleaned_netloc,
                parsed.path.rstrip("/") or parsed.path,
                urlencode(cleaned_query, doseq=True),
                "",
            )
        )
        return normalized.rstrip("/")

    def _extract_title(self, html_text: str, url: str) -> str:
        """优先从 title 与 meta 中提取标题。"""
        candidates: list[str] = []
        for pattern in [
            r'<meta[^>]+property="og:title"[^>]+content="([^"]{2,200})"',
            r'<meta[^>]+name="twitter:title"[^>]+content="([^"]{2,200})"',
            r"<title[^>]*>([^<]{2,200})</title>",
            r"<h1[^>]*>([\s\S]{2,200}?)</h1>",
        ]:
            for match in re.findall(pattern, html_text, flags=re.I):
                cleaned = self._clean_inline_text(match)
                if cleaned:
                    candidates.append(cleaned)
        for candidate in candidates:
            if len(candidate) >= 4:
                return candidate[:120]
        domain = urlparse(url).netloc.replace("www.", "")
        return f"{domain} 旅行攻略"

    def _sanitize_title(self, title: str, *, source_type: str, issue_code: str | None) -> str:
        """避免把访客页标题当成真实攻略标题。"""
        compact = title.strip()
        if compact and compact not in BLOCKED_TITLE_KEYWORDS and "Visitor System" not in compact:
            return compact
        if source_type == "weibo_link":
            return "微博攻略导入"
        return compact or "链接导入攻略"

    def _derive_title_from_content(self, title: str, content: str, *, source_type: str) -> str:
        """当平台标题过泛时，从正文中提炼更像攻略名的标题。"""
        generic_titles = {"微博正文 - 微博", "微博攻略导入", "链接导入攻略"}
        if source_type != "weibo_link" and title not in generic_titles:
            return title
        for line in content.splitlines():
            cleaned = clean_text(line)
            if not cleaned or len(cleaned) > 60:
                continue
            if re.search(r"(攻略|路线|游玩|旅行|旅游|一日|两日|三日)", cleaned):
                return cleaned[:120]
        for line in content.splitlines():
            cleaned = clean_text(line)
            if 6 <= len(cleaned) <= 40:
                return cleaned[:120]
        return title

    def _build_structured_review_draft(self, *, title: str, content: str) -> dict[str, Any]:
        """生成前端可编辑的结构化校对草稿。"""
        structured = build_structured_guide_data(title, content)
        route_nodes = self._extract_route_nodes(content)
        ticket_hints = self._extract_ticket_hints(content)
        budget_tips = self._extract_budget_tips(content)
        risk_notes = self._extract_risk_notes(content)
        if route_nodes:
            known_places = {place.get("name") for place in structured.get("places", []) if isinstance(place, dict)}
            for node in route_nodes:
                if node and node not in known_places:
                    structured.setdefault("places", []).append({"name": node, "type": "scenic"})
                    structured.setdefault("scenic_spots", []).append(node)
                    known_places.add(node)
        structured["route_nodes"] = route_nodes
        structured["ticket_hints"] = ticket_hints
        structured["budget_tips"] = budget_tips
        structured["risk_notes"] = risk_notes
        return structured

    def _extract_route_nodes(self, content: str) -> list[str]:
        """从游玩路线里提取顺序节点。"""
        lines = content.splitlines()
        route_lines: list[str] = []
        for index, line in enumerate(lines):
            if any(keyword in line for keyword in ("路线", "线路", "游玩顺序", "行程")):
                route_lines.append(line)
                if index + 1 < len(lines):
                    route_lines.append(lines[index + 1])
        if not route_lines:
            route_lines = [line for line in lines if "→" in line or "->" in line]
        nodes: list[str] = []
        for line in route_lines[:3]:
            candidate = re.sub(r"^[^：:]{0,16}[：:]", "", line)
            for item in re.split(r"→|->|—|--|>|，|、", candidate):
                cleaned = clean_text(re.sub(r"^[✅🚇📍0-9️⃣.\s]+", "", item))
                if 2 <= len(cleaned) <= 24 and not re.search(r"(路线|线路|游玩|交通|出行)", cleaned):
                    nodes.append(cleaned)
        return self._unique_text_items(nodes, limit=16)

    def _extract_ticket_hints(self, content: str) -> list[str]:
        """抽取门票、船票、预约等明确成本或购买提示。"""
        hints: list[str] = []
        for line in self._iter_content_clauses(content):
            cleaned = clean_text(line)
            if re.search(r"(门票|船票|车票|预约|现场买|换零钱|免费|买票|售票|票价|💰|¥|元/人)", cleaned):
                if 4 <= len(cleaned) <= 90:
                    hints.append(cleaned)
        return self._unique_text_items(hints, limit=10)

    def _extract_budget_tips(self, content: str) -> list[str]:
        """抽取预算和消费提醒。"""
        tips: list[str] = []
        for line in self._iter_content_clauses(content):
            cleaned = clean_text(line)
            if re.search(r"(预算|人均|费用|花费|太贵|省钱|包含|💰|¥|[0-9]{1,5}\s*元)", cleaned):
                if 4 <= len(cleaned) <= 100:
                    tips.append(cleaned)
        return self._unique_text_items(tips, limit=10)

    def _extract_risk_notes(self, content: str) -> list[str]:
        """抽取拥堵、排队、体力、天气、购票等风险提醒。"""
        notes: list[str] = []
        for line in self._iter_content_clauses(content):
            cleaned = clean_text(line)
            if re.search(r"(建议|注意|避开|排队|拥堵|特别堵|抢不到|太贵|雨天|旺季|累|不想|提前)", cleaned):
                if 4 <= len(cleaned) <= 110:
                    notes.append(cleaned)
        return self._unique_text_items(notes, limit=10)

    def _iter_content_clauses(self, content: str) -> list[str]:
        """把正文切成较短提示句，避免整段过长导致门票/风险提示漏抽。"""
        clauses: list[str] = []
        for line in content.splitlines():
            clauses.extend(part for part in re.split(r"[。；;]", line) if part.strip())
        return clauses or content.splitlines()

    def _unique_text_items(self, items: list[str], *, limit: int = 10) -> list[str]:
        """保持顺序去重，供结构化校对字段使用。"""
        results: list[str] = []
        seen: set[str] = set()
        for item in items:
            compact = re.sub(r"\s+", "", item)
            if not compact or compact in seen:
                continue
            seen.add(compact)
            results.append(item)
            if len(results) >= limit:
                break
        return results

    def _normalize_structured_override(self, structured: dict | None) -> dict[str, Any] | None:
        """清洗前端结构化校对结果，避免空字段覆盖有效抽取。"""
        if not isinstance(structured, dict):
            return None
        allowed = {
            "city",
            "days",
            "budget_min",
            "budget_max",
            "transport_modes",
            "lodging_suggestions",
            "travel_style_tags",
            "scenic_spots",
            "food_spots",
            "places",
            "route_nodes",
            "ticket_hints",
            "budget_tips",
            "risk_notes",
            "summary",
        }
        cleaned: dict[str, Any] = {}
        for key in allowed:
            value = structured.get(key)
            if value in (None, "", []):
                continue
            if key in {"days", "budget_min", "budget_max"}:
                number = self._optional_int(value)
                if number is not None:
                    cleaned[key] = number
                continue
            if isinstance(value, list):
                if key == "places":
                    places = []
                    for item in value:
                        if not isinstance(item, dict):
                            continue
                        name = self._optional_string(item.get("name"))
                        place_type = self._optional_string(item.get("type")) or "scenic"
                        if name:
                            places.append({"name": name, "type": place_type})
                    if places:
                        cleaned[key] = places
                    continue
                values = self._optional_string_list(value)
                if values:
                    cleaned[key] = values
                continue
            text = self._optional_string(value)
            if text:
                cleaned[key] = text
        if "places" not in cleaned:
            places = [{"name": name, "type": "scenic"} for name in cleaned.get("scenic_spots", [])]
            places += [{"name": name, "type": "food"} for name in cleaned.get("food_spots", [])]
            if places:
                cleaned["places"] = places
        return cleaned or None

    def _merge_structured_overrides(
        self,
        base: dict[str, Any] | None,
        override: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """合并大模型补强与人工校对结果，人工校对优先。"""
        if not base and not override:
            return None
        merged = dict(base or {})
        for key, value in (override or {}).items():
            if value not in (None, "", []):
                merged[key] = value
        return merged

    def _extract_author(self, html_text: str) -> str | None:
        """尽量抽取公开作者信息。"""
        for pattern in [
            r'<meta[^>]+name="author"[^>]+content="([^"]{2,120})"',
            r'"author"\s*:\s*"([^"]{2,120})"',
            r"作者[:：]\s*([\u4e00-\u9fa5A-Za-z0-9_-]{2,40})",
        ]:
            match = re.search(pattern, html_text, flags=re.I)
            if match:
                return self._clean_inline_text(match.group(1))[:80]
        return None

    def _extract_image_urls(self, html_text: str, base_url: str) -> list[str]:
        """从原始 HTML 中提取图片链接，覆盖纯图片攻略与图文混排攻略。"""
        candidates: list[str] = []
        for pattern in [
            r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"',
            r'<meta[^>]+name="twitter:image"[^>]+content="([^"]+)"',
            r'<img[^>]+src="([^"]+)"',
            r'<img[^>]+data-src="([^"]+)"',
            r'"image"\s*:\s*"([^"]+)"',
        ]:
            for match in re.findall(pattern, html_text, flags=re.I):
                normalized = self._normalize_image_url(match, base_url)
                if normalized:
                    candidates.append(normalized)
        deduped: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
            if len(deduped) >= 16:
                break
        return deduped

    def _normalize_image_url(self, image_url: str, base_url: str) -> str | None:
        """清洗图片链接，并尽量把缩略图替换成大图。"""
        value = html.unescape(image_url or "").replace("\\/", "/").strip()
        if not value or value.startswith("data:"):
            return None
        if value.startswith("//"):
            value = f"{urlparse(base_url).scheme or 'https'}:{value}"
        elif value.startswith("/"):
            parsed = urlparse(base_url)
            value = f"{parsed.scheme}://{parsed.netloc}{value}"
        elif not value.startswith("http"):
            return None
        if "sinaimg.cn" in value:
            value = re.sub(r"/(?:thumb\d+|orj\d+|mw\d+)/", "/large/", value)
        return value

    def _extract_main_content(self, html_text: str) -> str:
        """抽取网页主正文，尽量保留旅行语义。"""
        decoded = html.unescape(html_text)
        normalized = decoded.replace("\\/", "/")
        normalized = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", normalized)
        normalized = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", normalized)
        normalized = re.sub(r"(?is)<noscript[^>]*>.*?</noscript>", " ", normalized)
        normalized = re.sub(r"(?is)<svg[^>]*>.*?</svg>", " ", normalized)
        normalized = re.sub(r"(?is)<(header|footer|nav|aside|form|button)[^>]*>.*?</\1>", " ", normalized)
        normalized = normalized.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
        normalized = re.sub(r"(?i)</p\s*>", "\n", normalized)
        normalized = re.sub(r"(?i)</div\s*>", "\n", normalized)
        normalized = re.sub(r"(?i)</li\s*>", "\n", normalized)

        blocks: list[tuple[int, str]] = []
        for pattern in [
            r"(?is)<article[^>]*>(.*?)</article>",
            r"(?is)<main[^>]*>(.*?)</main>",
            r'(?is)<div[^>]+class="[^"]*(?:article|content|post|entry|detail|body)[^"]*"[^>]*>(.*?)</div>',
            r'(?is)<section[^>]+class="[^"]*(?:article|content|post|entry|detail|body)[^"]*"[^>]*>(.*?)</section>',
            r"(?is)<body[^>]*>(.*?)</body>",
        ]:
            for match in re.findall(pattern, normalized):
                text = self._html_fragment_to_text(match)
                score = self._score_content_block(text)
                if score > 0:
                    blocks.append((score, text))

        if not blocks:
            return ""

        blocks.sort(key=lambda item: item[0], reverse=True)
        best = blocks[0][1]
        return self._normalize_content(best)

    def _html_fragment_to_text(self, fragment: str) -> str:
        """把 HTML 片段转成纯文本段落。"""
        text = re.sub(r"(?is)<[^>]+>", " ", fragment)
        text = text.replace("\\n", "\n").replace("\\t", " ")
        text = re.sub(r"\u3000+", " ", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _normalize_content(self, text: str) -> str:
        """清洗正文，去掉重复与噪音。"""
        lines: list[str] = []
        seen: set[str] = set()
        for raw_line in text.splitlines():
            line = clean_text(raw_line)
            compact = re.sub(r"\s+", "", line)
            if len(compact) < 4:
                continue
            if any(re.search(pattern, compact, flags=re.I) for pattern in NOISE_PATTERNS):
                continue
            if compact in seen:
                continue
            seen.add(compact)
            lines.append(line)

        content = "\n".join(lines)
        # 中文注释：微博详情页的 body 文本可能把正文后的互动区、评论区一起带出来，遇到这些边界词就截断。
        for marker in (
            "\nLive\n",
            "\n微博正文 - 微博",
            "\n登录 注册",
            "\n推荐 热门推荐",
            "Live\n分享这条博文",
            "分享这条博文",
            "同时转发",
            "全部评论",
            "热门评论",
        ):
            if marker in content:
                content = content.split(marker, 1)[0]
        content = re.sub(r"\n{3,}", "\n\n", content)
        return content.strip()

    def _score_content_block(self, text: str) -> int:
        """给候选正文块打分，优先选择旅行信息密度更高的区域。"""
        compact = re.sub(r"\s+", "", text)
        if len(compact) < 80:
            return 0
        score = min(len(compact), 2400)
        paragraph_count = max(1, len([line for line in text.splitlines() if line.strip()]))
        score += min(paragraph_count * 12, 180)
        score += sum(28 for term in TRAVEL_IMPORT_TERMS if term in text)
        score -= sum(40 for noise in ["登录", "扫码", "APP", "广告", "版权所有"] if noise in text)
        return score

    def _detect_source_type(self, url: str) -> str:
        """根据域名识别来源类型。"""
        host = urlparse(url).netloc.lower()
        if "weibo.com" in host or "m.weibo.cn" in host:
            return "weibo_link"
        if "xiaohongshu.com" in host:
            return "xiaohongshu_link"
        if "mp.weixin.qq.com" in host:
            return "wechat_article"
        if any(term in host for term in ["mafengwo", "ctrip", "qunar", "fliggy"]):
            return "travel_site"
        return "web_link"

    def _detect_category(self, title: str, url: str, content: str) -> str:
        """给导入内容一个可用于筛选的分类。"""
        city = infer_city(title, content)
        if city and city != "未知城市":
            return city
        host = urlparse(url).netloc.lower()
        if "weibo" in host:
            return "微博导入"
        if "xiaohongshu" in host:
            return "小红书导入"
        if "weixin" in host:
            return "公众号导入"
        return "链接导入"

    def _assess_quality(
        self,
        *,
        title: str,
        content: str,
        url: str,
        html_text: str,
        issue_code: str | None,
    ) -> dict[str, Any]:
        """给导入内容做基础质量评估。"""
        compact = re.sub(r"\s+", "", content)
        paragraph_count = len([line for line in content.splitlines() if line.strip()])
        travel_hits = sum(1 for term in TRAVEL_IMPORT_TERMS if term in content)
        city = infer_city(title, content)
        days = infer_days(f"{title}\n{content}")
        score = 0
        score += min(len(compact) // 18, 40)
        score += min(paragraph_count * 4, 20)
        score += min(travel_hits * 6, 24)
        if city and city != "未知城市":
            score += 8
        if days:
            score += 8
        if paragraph_count >= 4:
            score += 6
        if travel_hits >= 4:
            score += 6
        if "<article" in html_text.lower() or "<main" in html_text.lower():
            score += 4
        if issue_code in {"login_wall", "rate_limited", "browser_timeout"}:
            score -= 20
        score = max(0, min(score, 100))
        grade = "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 50 else "D"
        return {
            "score": score,
            "grade": grade,
            "city_confidence": "high" if city and city != "未知城市" else "low",
            "paragraph_count": paragraph_count,
            "travel_signal_count": travel_hits,
            "content_length": len(compact),
            "resolved_url": url,
        }

    def _find_duplicate_by_url(self, url: str) -> Guide | None:
        """按链接直接查重。"""
        stmt = (
            select(Guide)
            .join(GuideSource, Guide.source_id == GuideSource.id)
            .where(
                (GuideSource.source_url == url)
                | (GuideSource.raw_url == url)
                | (GuideSource.resolved_url == url)
            )
            .order_by(Guide.id.desc())
        )
        return self.db.execute(stmt).scalars().first()

    def _find_duplicate_by_content(self, *, title: str, content: str) -> Guide | None:
        """按标题和正文相似度查重。"""
        normalized_title = self._compact_text(title)
        normalized_content = self._compact_text(content)[:1600]
        if len(normalized_content) < 120:
            return None

        rows = (
            self.db.execute(
                select(Guide, GuideSource)
                .join(GuideSource, Guide.source_id == GuideSource.id)
                .order_by(Guide.id.desc())
                .limit(400)
            )
            .all()
        )
        for guide, source in rows:
            existing_title = self._compact_text(guide.title)
            existing_content = self._compact_text(source.raw_text or "")[:1600]
            if not existing_content:
                continue
            if normalized_title and existing_title == normalized_title:
                return guide
            similarity = SequenceMatcher(None, normalized_content, existing_content).ratio()
            if similarity >= 0.92:
                return guide
        return None

    def _build_duplicate_result(
        self,
        guide: Guide,
        *,
        reason: str,
        quality: dict[str, Any] | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """统一返回重复命中结果。"""
        return {
            "status": "duplicate",
            "reason": reason,
            "guide_id": guide.id,
            "title": guide.title,
            "city": guide.city,
            "quality": quality,
            "diagnostics": diagnostics,
            "guide": self._get_guide_detail(guide.id),
            "message": "已命中相似攻略，未重复入库。",
        }

    def _save_pending_source(
        self,
        *,
        title: str,
        raw_url: str,
        resolved_url: str,
        source_type: str,
        category: str,
        author: str | None,
        raw_text: str | None,
        note: str,
    ) -> GuideSource:
        """正文不足时先保存来源，方便后续补录。"""
        source = GuideSource(
            source_type=source_type,
            source_url=resolved_url,
            raw_url=raw_url,
            resolved_url=resolved_url,
            category=category,
            crawl_status="pending",
            title=title,
            author=author,
            raw_text=raw_text,
            license_note=note,
        )
        self.db.add(source)
        self.db.commit()
        self.db.refresh(source)
        return source

    async def _build_llm_structured_hint(
        self,
        *,
        title: str,
        content: str,
        url: str,
        category: str,
        author: str | None,
    ) -> dict[str, Any] | None:
        """让大模型补强结构化理解，但失败时不影响主流程。"""
        if not self.llm.configured():
            return None

        prompt = (
            "你是旅游攻略入库结构化助手。"
            "请根据公开网页攻略，输出严格 JSON。"
            "字段：normalized_title, city, days, budget_min, budget_max, category, author, "
            "travel_style_tags, transport_modes, lodging_suggestions, scenic_spots, food_spots, summary。"
            "若无法判断请填 null 或空数组。"
            f"\n来源链接：{url}"
            f"\n分类候选：{category}"
            f"\n作者候选：{author or ''}"
            f"\n标题：{title}"
            f"\n正文：{content[:6000]}"
        )
        data = await self.llm.json_chat(prompt)
        return data if isinstance(data, dict) else None

    def _build_structured_override(
        self,
        *,
        title: str,
        content: str,
        llm_hint: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """把大模型补强结果转成入库服务可合并的 structured override。"""
        if not llm_hint:
            return None

        city = self._optional_string(llm_hint.get("city")) or infer_city(title, content)
        scenic_spots = self._optional_string_list(llm_hint.get("scenic_spots"))
        food_spots = self._optional_string_list(llm_hint.get("food_spots"))
        places = [{"name": name, "type": "scenic"} for name in scenic_spots] + [
            {"name": name, "type": "food"} for name in food_spots
        ]
        override = {
            "city": city,
            "days": self._optional_int(llm_hint.get("days")),
            "summary": self._optional_string(llm_hint.get("summary")),
            "budget_min": self._optional_int(llm_hint.get("budget_min")),
            "budget_max": self._optional_int(llm_hint.get("budget_max")),
            "transport_modes": self._optional_string_list(llm_hint.get("transport_modes")),
            "lodging_suggestions": self._optional_string_list(llm_hint.get("lodging_suggestions")),
            "travel_style_tags": self._optional_string_list(llm_hint.get("travel_style_tags")),
            "scenic_spots": scenic_spots,
            "food_spots": food_spots,
            "places": places or None,
        }
        budget_min = override.get("budget_min")
        budget_max = override.get("budget_max")
        if isinstance(budget_min, int) and isinstance(budget_max, int) and budget_min > budget_max:
            # 中文注释：大模型偶尔会把最小/最大预算写反，入库前统一纠正，避免前端展示失真。
            override["budget_min"], override["budget_max"] = budget_max, budget_min
        return {key: value for key, value in override.items() if value not in (None, [], "")}

    def _get_guide_detail(self, guide_id: Any) -> dict[str, Any] | None:
        """返回前端可直接预览和引用的攻略详情。"""
        if not isinstance(guide_id, int):
            return None
        return RagService(self.db).get_guide_detail(guide_id)

    def _enrich_content_with_ocr(self, content: str, *, page: FetchedGuidePage, url: str) -> str:
        """正文不足时尝试读取页面图片中的攻略文字，作为链接导入兜底。"""
        compact_length = len(re.sub(r"\s+", "", content or ""))
        if compact_length >= 220 or not page.image_urls or not self.ocr.available():
            return content

        seed = self._extract_weibo_status_id(url) or re.sub(r"\W+", "_", url)[-80:] or "guide_import"
        ocr_texts = self.ocr.extract_from_images(page.image_urls, seed=seed)
        ocr_text = "\n\n".join(ocr_texts) if isinstance(ocr_texts, list) else str(ocr_texts or "")
        if len(re.sub(r"\s+", "", ocr_text or "")) < 40:
            return content
        if not content.strip():
            return clean_text(ocr_text)
        return clean_text(f"{content}\n\n图片OCR补充：\n{ocr_text}")

    async def _enrich_content_with_visual_text(
        self,
        content: str,
        *,
        page: FetchedGuidePage,
        url: str,
        title: str,
    ) -> tuple[str, dict[str, Any]]:
        """尽量补齐图片中的攻略正文，并返回可视化诊断数据。"""
        base_content = clean_text(content)
        html_text_length = len(self._compact_text(base_content))
        diagnostics: dict[str, Any] = {
            "image_count": len(page.image_urls),
            "html_text_length": html_text_length,
            "final_content_length": html_text_length,
            "content_sources": ["html"] if html_text_length else [],
            "ocr_used": False,
            "ocr_text_length": 0,
            "ocr_preview_lines": [],
            "ocr_image_total": len(page.image_urls),
            "ocr_target_count": 0,
            "ocr_processed_count": 0,
            "ocr_success_count": 0,
            "ocr_cached_count": 0,
            "ocr_coverage_ratio": 0,
            "ocr_elapsed_seconds": 0,
            "ocr_image_results": [],
            "vision_used": False,
            "vision_text_length": 0,
            "vision_preview_lines": [],
        }
        enriched = base_content
        ocr_text = self._extract_ocr_text(base_content, page=page, url=url)
        if ocr_text:
            enriched = self._merge_visual_text(base_content, ocr_text, label="图片OCR补充")
            diagnostics["ocr_used"] = True
            diagnostics["ocr_text_length"] = len(self._compact_text(ocr_text))
            diagnostics["ocr_preview_lines"] = self._build_visual_preview_lines(ocr_text)
            diagnostics["content_sources"] = [*diagnostics["content_sources"], "ocr"]
        ocr_stats = getattr(self.ocr, "last_run_stats", {}) or {}
        if ocr_stats:
            diagnostics.update(
                {
                    "ocr_image_total": ocr_stats.get("image_total", len(page.image_urls)),
                    "ocr_target_count": ocr_stats.get("target_count", 0),
                    "ocr_processed_count": ocr_stats.get("processed_count", 0),
                    "ocr_success_count": ocr_stats.get("success_count", 0),
                    "ocr_cached_count": ocr_stats.get("cached_count", 0),
                    "ocr_coverage_ratio": ocr_stats.get("coverage_ratio", 0),
                    "ocr_elapsed_seconds": ocr_stats.get("elapsed_seconds", 0),
                    "ocr_image_results": (ocr_stats.get("image_results") or [])[:20],
                }
            )

        if not self._should_use_vision_fallback(enriched, page=page):
            diagnostics["final_content_length"] = len(self._compact_text(enriched))
            return enriched, diagnostics

        vision_text = await self._extract_visual_text_with_llm(page.image_urls, title=title, url=page.resolved_url)
        if len(self._compact_text(vision_text)) < 40:
            diagnostics["final_content_length"] = len(self._compact_text(enriched))
            return enriched, diagnostics

        diagnostics["vision_used"] = True
        diagnostics["vision_text_length"] = len(self._compact_text(vision_text))
        diagnostics["vision_preview_lines"] = self._build_visual_preview_lines(vision_text)
        diagnostics["content_sources"] = [*diagnostics["content_sources"], "vision"]
        enriched = self._merge_visual_text(enriched, vision_text, label="图片识别补充")
        diagnostics["final_content_length"] = len(self._compact_text(enriched))
        return enriched, diagnostics

    def _enrich_content_with_ocr(self, content: str, *, page: FetchedGuidePage, url: str) -> str:
        """优先通过本地 OCR 把图片中的攻略文字并回正文。"""
        ocr_text = self._extract_ocr_text(content, page=page, url=url)
        if not ocr_text:
            return content
        return self._merge_visual_text(content, ocr_text, label="图片OCR补充")

    def _extract_ocr_text(self, content: str, *, page: FetchedGuidePage, url: str) -> str:
        """中文注释：抽出 OCR 纯文本，前后端都能复用同一份诊断来源。"""
        compact_length = len(re.sub(r"\s+", "", content or ""))
        if not page.image_urls or not self.ocr.available():
            return ""
        travel_markers = re.search(r"(攻略|路线|景点|交通|住宿|预算|门票|行程|游玩|旅行|旅游)", content or "")
        image_heavy = len(page.image_urls) >= 4
        looks_like_image_guide = image_heavy and compact_length < 520
        # 中文注释：正文已经足够完整时不强制跑 OCR；但“短正文+多图”通常是长图攻略，必须尽量全量 OCR。
        if compact_length >= 420 and travel_markers and page.issue_code is None and not looks_like_image_guide:
            return ""
        if compact_length >= 900 and page.issue_code is None:
            return ""

        seed = self._extract_weibo_status_id(url) or re.sub(r"\W+", "_", url)[-80:] or "guide_import"
        ocr_limit = self._resolve_ocr_image_limit(page=page, compact_length=compact_length)
        ocr_texts = self._extract_ocr_texts_with_budget(page.image_urls, seed=seed, limit=ocr_limit)
        ocr_text = "\n\n".join(ocr_texts) if isinstance(ocr_texts, list) else str(ocr_texts or "")
        normalized = self._normalize_content(clean_text(ocr_text))
        if len(re.sub(r"\s+", "", normalized or "")) < 40:
            return ""
        return normalized

    def _resolve_ocr_image_limit(self, *, page: FetchedGuidePage, compact_length: int) -> int:
        """根据页面形态决定 OCR 覆盖范围。"""
        if len(page.image_urls) >= 4 and compact_length < 520:
            # 中文注释：短正文多图的微博，正文通常写在长图里，按企业级导入要求尽量覆盖全部图片。
            return min(len(page.image_urls), 12)
        if compact_length < 240:
            return min(len(page.image_urls), 6)
        return min(len(page.image_urls), 4)

    def _extract_ocr_texts_with_budget(self, image_urls: list[str], *, seed: str, limit: int) -> list[str]:
        """调用 OCR 服务，并兼容测试替身或旧实现。"""
        try:
            return self.ocr.extract_from_images(
                image_urls,
                seed=seed,
                limit=limit,
                max_seconds=170,
                min_coverage_ratio=0.8,
            )
        except TypeError:
            return self.ocr.extract_from_images(image_urls, seed=seed, limit=limit)

    def _should_use_vision_fallback(self, content: str, *, page: FetchedGuidePage) -> bool:
        """当 OCR 仍不足以还原正文时，再尝试多模态兜底。"""
        if not page.image_urls or not self.llm.configured():
            return False
        compact_length = len(self._compact_text(content))
        image_heavy = len(page.image_urls) >= 2
        travel_markers = re.search(r"(攻略|路线|景点|交通|住宿|预算|门票|行程|游玩|旅行|旅游)", content or "")
        if compact_length >= 220 and travel_markers:
            return False
        if compact_length < 140:
            return True
        return image_heavy and compact_length < 260 and not travel_markers

    async def _extract_visual_text_with_llm(self, image_urls: list[str], *, title: str, url: str) -> str:
        """使用多模态模型兜底读取图片中的旅行攻略正文。"""
        prompt = (
            "请严格提取这些图片里的旅行攻略正文，只输出可直接入库的中文纯文本。"
            "优先保留目的地、路线顺序、景点、交通、住宿、预算、门票、注意事项。"
            "不要输出解释，不要补充你猜测的内容，也不要使用 Markdown。\n"
            f"标题线索：{title}\n"
            f"来源链接：{url}"
        )
        content = await self.llm.vision_plain_chat(prompt, image_urls)
        if not content:
            return ""
        return self._normalize_content(clean_text(content))

    def _merge_visual_text(self, content: str, extra_text: str, *, label: str) -> str:
        """把 OCR 或图片理解得到的文本并回正文，并做去重。"""
        normalized_extra = self._normalize_content(clean_text(extra_text))
        if not normalized_extra:
            return clean_text(content)
        if not content.strip():
            return normalized_extra

        existing_lines = [self._compact_text(line) for line in content.splitlines() if self._compact_text(line)]
        unique_lines: list[str] = []
        for raw_line in normalized_extra.splitlines():
            line = clean_text(raw_line)
            compact = self._compact_text(line)
            if len(compact) < 4:
                continue
            if any(compact == existing or compact in existing or existing in compact for existing in existing_lines):
                continue
            if any(compact == self._compact_text(item) for item in unique_lines):
                continue
            unique_lines.append(line)
        if not unique_lines:
            return clean_text(content)
        return clean_text(f"{content}\n\n{label}：\n" + "\n".join(unique_lines))


    def _build_visual_preview_lines(self, content: str, limit: int = 5) -> list[str]:
        """提炼可读片段，让前端能直接展示图片补充正文。"""
        preview_lines: list[str] = []
        seen: set[str] = set()
        for raw_line in self._normalize_content(clean_text(content)).splitlines():
            line = clean_text(raw_line)
            compact = self._compact_text(line)
            if len(compact) < 8 or compact in seen:
                continue
            seen.add(compact)
            preview_lines.append(line[:120])
            if len(preview_lines) >= limit:
                break
        return preview_lines

    def _save_import_record(self, url: str, result: dict[str, Any], *, mode: str) -> dict[str, Any]:
        """保存导入结果历史；历史写入失败不影响主导入流程。"""
        try:
            record = GuideImportRecord(
                url=url,
                status=str(result.get("status") or "unknown")[:30],
                mode=mode,
                title=(str(result.get("title"))[:200] if result.get("title") else None),
                source_type=(str(result.get("source_type"))[:60] if result.get("source_type") else None),
                guide_id=result.get("guide_id") if isinstance(result.get("guide_id"), int) else None,
                source_id=result.get("source_id") if isinstance(result.get("source_id"), int) else None,
                reason=(str(result.get("reason"))[:80] if result.get("reason") else None),
                quality_json=json.dumps(result.get("quality"), ensure_ascii=False) if result.get("quality") else None,
                diagnostics_json=(
                    json.dumps(result.get("diagnostics"), ensure_ascii=False) if result.get("diagnostics") else None
                ),
                content=str(result.get("content") or "") if result.get("content") else None,
                structured_json=(
                    json.dumps(result.get("structured"), ensure_ascii=False) if result.get("structured") else None
                ),
                category=(str(result.get("category"))[:120] if result.get("category") else None),
                resolved_url=(str(result.get("resolved_url"))[:1000] if result.get("resolved_url") else None),
                author=(str(result.get("author"))[:120] if result.get("author") else None),
                message=str(result.get("message") or "")[:1000] if result.get("message") else None,
            )
            self.db.add(record)
            self.db.commit()
            self.db.refresh(record)
            result["record"] = self._record_to_dict(record)
        except Exception:  # noqa: BLE001
            self.db.rollback()
        return result

    def _record_to_dict(self, record: GuideImportRecord) -> dict[str, Any]:
        """把数据库记录转换为前端稳定 schema。"""
        fallback_preview = self._load_preview_from_task(record.url) if not record.content else {}
        return {
            "id": record.id,
            "url": record.url,
            "status": record.status,
            "mode": record.mode,
            "title": record.title,
            "source_type": record.source_type,
            "guide_id": record.guide_id,
            "source_id": record.source_id,
            "reason": record.reason,
            "message": record.message,
            "quality": self._loads_json(record.quality_json),
            "diagnostics": self._loads_json(record.diagnostics_json),
            "content": record.content or fallback_preview.get("content"),
            "structured": self._loads_json(record.structured_json) or fallback_preview.get("structured"),
            "category": record.category or fallback_preview.get("category"),
            "resolved_url": record.resolved_url or fallback_preview.get("resolved_url"),
            "author": record.author or fallback_preview.get("author"),
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }

    def _load_preview_from_task(self, url: str) -> dict[str, Any]:
        """兼容旧导入记录：从同链接的后台任务结果中恢复可编辑预览正文。"""
        task = (
            self.db.execute(
                select(GuideImportTask)
                .where(GuideImportTask.url == url)
                .where(GuideImportTask.result_json.is_not(None))
                .order_by(GuideImportTask.created_at.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        if not task or not task.result_json:
            return {}
        data = self._loads_json(task.result_json)
        return data if isinstance(data, dict) else {}

    def _loads_json(self, value: str | None) -> Any:
        """安全读取 JSON 字段，兼容旧记录或异常写入。"""
        if not value:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None

    def _detect_access_issue(
        self,
        *,
        html_text: str,
        resolved_url: str,
        status_code: int,
        content_type: str,
    ) -> str | None:
        """识别抓取失败的主要原因，便于前端和日志给出更准的提示。"""
        if status_code in {429, 432}:
            return "rate_limited"
        if status_code >= 400:
            return "http_error"
        if self._url_looks_blocked(resolved_url):
            return "login_wall"
        lowered = html_text.lower()
        if any(marker.lower() in lowered for marker in BLOCKED_PAGE_MARKERS):
            return "login_wall"
        if content_type and "text/html" not in content_type.lower() and "json" not in content_type.lower():
            return "unexpected_content_type"
        return None

    def _url_looks_blocked(self, url: str) -> bool:
        """通过最终跳转地址快速判断是否落到了访客/登录墙。"""
        host = urlparse(url).netloc.lower()
        return "passport.weibo.com" in host or "visitor.passport.weibo.cn" in host

    def _page_has_usable_public_content(self, page: FetchedGuidePage) -> bool:
        """判断当前页面是否已经拿到了足够可用的公开正文。"""
        content = self._extract_main_content(page.html_text)
        compact_length = len(re.sub(r"\s+", "", content))
        return compact_length >= 100 and page.issue_code is None

    def _page_strength(self, page: FetchedGuidePage) -> int:
        """对失败页和候选页打分，方便挑出最有价值的诊断结果。"""
        content = self._extract_main_content(page.html_text)
        compact_length = len(re.sub(r"\s+", "", content))
        score = compact_length
        if page.fetch_method in {"browser_render", "browser_render_node"}:
            score += 80
        if page.issue_code is None:
            score += 200
        if page.issue_code == "login_wall":
            score -= 150
        if page.issue_code == "rate_limited":
            score -= 180
        score += min(page.status_code, 200)
        return score

    def _attempt_from_page(self, page: FetchedGuidePage) -> dict[str, Any]:
        """将抓取结果压缩成可返回前端的诊断记录。"""
        return {
            "method": page.fetch_method,
            "requested_url": page.requested_url,
            "resolved_url": page.resolved_url,
            "status_code": page.status_code,
            "content_type": page.content_type,
            "issue_code": page.issue_code,
        }

    def _build_diagnostics(
        self,
        page: FetchedGuidePage,
        *,
        quality: dict[str, Any],
        visual_diagnostics: dict[str, Any] | None = None,
        content: str = "",
    ) -> dict[str, Any]:
        """统一组装导入诊断信息。"""
        html_preview_lines = self._build_visual_preview_lines(self._extract_main_content(page.html_text))
        source_preview_lines = html_preview_lines[:]
        if visual_diagnostics:
            for key in ("ocr_preview_lines", "vision_preview_lines"):
                for line in visual_diagnostics.get(key) or []:
                    normalized = clean_text(str(line or ""))
                    if not normalized or normalized in source_preview_lines:
                        continue
                    source_preview_lines.append(normalized[:120])

        diagnostics = {
            "fetch_method": page.fetch_method,
            "issue_code": page.issue_code,
            "attempt_count": len(page.attempts),
            "attempts": page.attempts[:8],
            "quality_grade": quality["grade"],
            "image_count": len(page.image_urls),
            "image_urls": page.image_urls[:8],
            "html_preview_lines": html_preview_lines[:8],
            "source_preview_lines": source_preview_lines[:8],
            "final_preview_lines": self._build_visual_preview_lines(content)[:8],
        }
        if visual_diagnostics:
            diagnostics.update(visual_diagnostics)
        return diagnostics

    def _build_pending_message(self, issue_code: str | None) -> str:
        """为待处理结果生成更明确的提示文案。"""
        if issue_code == "login_wall":
            return "链接已记录为待处理来源：公开页被访客墙拦截，已尝试直连与浏览器渲染，当前仍未稳定拿到正文，建议稍后重试或手动补录。"
        if issue_code == "rate_limited":
            return "链接已记录为待处理来源：目标站点当前触发访问频控，建议稍后重试。"
        if issue_code == "unexpected_content_type":
            return "链接已记录为待处理来源：目标页面返回了非常规内容类型，建议稍后重试或手动补录。"
        return "链接已记录，但暂未抽取到足够正文，建议稍后重试或手动补录。"

    def _build_pending_license_note(self, issue_code: str | None) -> str:
        """把待处理原因写入来源备注，方便后台排查。"""
        if issue_code == "login_wall":
            return "公开链接已记录，但当前命中访客页或登录墙；系统已尝试浏览器渲染兜底，仍未稳定拿到正文。"
        if issue_code == "rate_limited":
            return "公开链接已记录，但当前触发站点访问频控，待后续重试。"
        return "公开链接已记录，但正文抽取不足，建议后续手动补录或再次导入。"

    def _compose_browser_snapshot_html(
        self,
        *,
        title: str,
        visible_text: str,
        raw_html: str,
        author: str | None = None,
    ) -> str:
        """把浏览器可见文本注入 HTML，便于复用现有正文抽取逻辑。"""
        article_text = html.escape(visible_text or "")
        author_meta = f'<meta name="author" content="{html.escape(author)}" />' if author else ""
        # 中文注释：快照只保留“已展开的可见正文”，避免把热搜壳或访客墙原始 HTML 再带回正文判断。
        return (
            f"<html><head><title>{html.escape(title or '')}</title>{author_meta}</head>"
            f"<body><article>{article_text}</article></body></html>"
        )

    def _extract_weibo_status_id(self, url: str) -> str | None:
        """从微博链接里提取状态 ID。"""
        parsed = urlsplit(url)
        matches = re.findall(r"(?<!\d)(\d{8,20})(?!\d)", parsed.path)
        if matches:
            # 中文注释：微博路径里常同时出现用户 ID 和微博 ID，这里优先取更长、且更靠后的那一段。
            return max(matches, key=lambda item: (len(item), parsed.path.rfind(item)))
        query = dict(parse_qsl(parsed.query))
        for key in ("id", "mid"):
            value = query.get(key)
            if value and value.isdigit():
                return value
        return None

    def _find_edge_executable(self) -> str | None:
        """优先复用本机已安装 Edge，降低浏览器兜底的部署成本。"""
        candidates = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        for candidate in candidates:
            try:
                with open(candidate, "rb"):
                    return candidate
            except OSError:
                continue
        return None

    def _unique_urls(self, urls: list[str]) -> list[str]:
        """保持顺序去重 URL。"""
        seen: set[str] = set()
        results: list[str] = []
        for item in urls:
            normalized = self._normalize_url(item)
            if normalized in seen:
                continue
            seen.add(normalized)
            results.append(normalized)
        return results

    def _clean_inline_text(self, value: str) -> str:
        """清洗一段短文本。"""
        text = html.unescape(value)
        text = re.sub(r"(?is)<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _compact_text(self, value: str) -> str:
        """压缩文本用于查重。"""
        return re.sub(r"\s+", "", value or "").strip().lower()

    def _optional_string(self, value: Any) -> str | None:
        """把可空值安全转为字符串。"""
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return None

    def _optional_int(self, value: Any) -> int | None:
        """把多种数值形态统一转为整数。"""
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            numeric = int(value)
            return numeric if 0 < numeric < 500000 else None
        if isinstance(value, str):
            digits = re.sub(r"[^\d]", "", value)
            if digits:
                numeric = int(digits)
                return numeric if 0 < numeric < 500000 else None
        return None

    def _optional_string_list(self, value: Any) -> list[str]:
        """清洗数组型字符串字段。"""
        if not isinstance(value, list):
            return []
        results: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                continue
            cleaned = item.strip()
            compact = self._compact_text(cleaned)
            if not compact or compact in seen:
                continue
            seen.add(compact)
            results.append(cleaned[:60])
        return results[:12]
