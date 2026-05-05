import html
import re
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx
from sqlalchemy.orm import Session

from app.db.models import GuideSource
from app.schemas.guides import GuideCreateRequest
from app.services.guide_ingest_service import GuideIngestService
from app.services.guide_link_import_service import GuideLinkImportService


WEIBO_GUIDE_INDEX_URL = "https://weibo.com/7896659368/QB5oxASNO"


@dataclass
class CrawledGuideLink:
    """微博合集页中抽取到的攻略入口。"""

    title: str
    raw_url: str
    resolved_url: str | None
    category: str
    crawl_status: str
    note: str


class WeiboCrawlerService:
    """微博公开攻略采集服务。

    只处理公开可访问内容，不登录、不绕过验证码、不读取用户 Cookie。
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    async def crawl_index(self, url: str = WEIBO_GUIDE_INDEX_URL, max_links: int = 300) -> dict:
        """抓取微博合集页，尽量解析公开正文，失败时保存人工处理入口。"""
        html_text = await self._fetch_public_html(url)
        links = self.extract_links(html_text, base_url=url, max_links=max_links)
        saved = 0
        skipped = 0
        indexed = 0
        pending = 0

        for link in links:
            exists = (
                self.db.query(GuideSource)
                .filter(GuideSource.raw_url == link.raw_url)
                .first()
            )
            if exists:
                skipped += 1
                continue

            public_text = await self._try_fetch_public_post_text(link.raw_url)
            if public_text and len(public_text) >= 80:
                GuideIngestService(self.db).add_guide(
                    GuideCreateRequest(
                        title=link.title,
                        content=public_text,
                        source_url=link.resolved_url or link.raw_url,
                        source_type="weibo_auto",
                        category=link.category,
                        raw_url=link.raw_url,
                        resolved_url=link.resolved_url or link.raw_url,
                        crawl_status="indexed",
                    )
                )
                saved += 1
                indexed += 1
                continue

            self.db.add(
                GuideSource(
                    source_type="weibo_pending",
                    source_url=link.resolved_url or link.raw_url,
                    raw_url=link.raw_url,
                    resolved_url=link.resolved_url,
                    category=link.category,
                    crawl_status=link.crawl_status,
                    title=link.title,
                    raw_text=None,
                    license_note="公开微博攻略入口，仅保存链接；正文需公开可访问后再入库。",
                )
            )
            saved += 1
            pending += 1

        self.db.commit()
        return {
            "index_url": url,
            "found": len(links),
            "saved": saved,
            "indexed": indexed,
            "pending": pending,
            "skipped": skipped,
            "status": "finished",
        }

    async def _fetch_public_html(self, url: str) -> str:
        """获取公开 HTML，不携带登录态和 Cookie。"""
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
            response.raise_for_status()
            return response.text

    async def _try_fetch_public_post_text(self, url: str) -> str | None:
        """尝试解析公开微博正文，复用更强的链接导入抓取内核。"""
        helper = GuideLinkImportService(self.db)
        try:
            snapshot = await helper.fetch_page_snapshot(url, source_type="weibo_link")
        except Exception:  # noqa: BLE001
            return None

        content = helper._extract_main_content(snapshot.html_text)
        if len(re.sub(r"\s+", "", content)) >= 80:
            return content
        return None

    def _extract_text_candidates(self, page: str) -> list[str]:
        """从 HTML、转义 JSON 和 meta 标签中抽取可能的正文候选。"""
        normalized = html.unescape(page).replace("\\/", "/")
        candidates: list[str] = []

        for pattern in [
            r'"text_raw"\s*:\s*"(.{40,4000}?)"',
            r'"text"\s*:\s*"(.{40,4000}?)"',
            r'<meta\s+name="description"\s+content="(.{40,2000}?)"',
            r'<meta\s+property="og:description"\s+content="(.{40,2000}?)"',
        ]:
            candidates.extend(re.findall(pattern, normalized, flags=re.S))

        plain = re.sub(r"<script[\s\S]*?</script>", " ", normalized, flags=re.I)
        plain = re.sub(r"<style[\s\S]*?</style>", " ", plain, flags=re.I)
        plain = re.sub(r"<[^>]+>", " ", plain)
        candidates.append(plain)
        return candidates

    def _clean_public_text(self, text: str) -> str:
        """清洗公开正文候选，去除 HTML 和转义符。"""
        if "\\u" in text:
            try:
                text = bytes(text, "utf-8").decode("unicode_escape")
            except UnicodeDecodeError:
                pass
        text = html.unescape(text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = text.replace("\\n", "\n").replace("\\t", " ")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def extract_links(self, html_text: str, base_url: str, max_links: int = 300) -> list[CrawledGuideLink]:
        """从微博合集 HTML 中提取公开链接。

        微博页面可能把链接放在转义 JSON、HTML 属性或短链里，所以这里先做反转义再正则抽取。
        """
        normalized = html.unescape(html_text)
        normalized = normalized.replace("\\/", "/")

        url_pattern = re.compile(
            r"https?://(?:weibo\.com|m\.weibo\.cn|t\.cn)/[A-Za-z0-9_?=&%#./:-]+"
        )
        raw_urls = []
        seen: set[str] = set()
        for match in url_pattern.finditer(normalized):
            candidate = match.group(0).rstrip("\\\"'，。)")
            if candidate in seen:
                continue
            seen.add(candidate)
            raw_urls.append(candidate)
            if len(raw_urls) >= max_links:
                break

        # 如果公开 HTML 没有直接暴露链接，也保留合集页本身，便于人工核对。
        if not raw_urls:
            raw_urls = [base_url]

        links: list[CrawledGuideLink] = []
        for index, raw_url in enumerate(raw_urls, start=1):
            title = self._guess_title(normalized, raw_url, index)
            category = self._guess_category(title)
            links.append(
                CrawledGuideLink(
                    title=title,
                    raw_url=urljoin(base_url, raw_url),
                    resolved_url=None,
                    category=category,
                    crawl_status="pending",
                    note="已保存入口链接，正文等待公开解析或人工补录。",
                )
            )
        return links

    def _guess_title(self, page_text: str, raw_url: str, index: int) -> str:
        """为采集链接生成可读标题；真实标题后续可由正文解析更新。"""
        window_index = page_text.find(raw_url)
        if window_index >= 0:
            start = max(0, window_index - 80)
            fragment = re.sub(r"\s+", " ", page_text[start:window_index])
            chinese = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,30}", fragment)
            if chinese:
                return chinese[-1][:60]
        return f"微博攻略入口 {index}"

    def _guess_category(self, title: str) -> str:
        """根据标题推断攻略分类，方便前端筛选和后续清洗。"""
        categories = [
            "江浙沪",
            "粤港澳",
            "云南",
            "川渝",
            "北京",
            "山东",
            "江西",
            "贵州",
            "福建",
            "新疆",
            "东北",
            "内蒙",
            "湖北",
            "河南",
            "广西",
            "出行住宿",
            "长途火车",
            "solo trip",
        ]
        for category in categories:
            if category in title:
                return category
        return "微博合集"
