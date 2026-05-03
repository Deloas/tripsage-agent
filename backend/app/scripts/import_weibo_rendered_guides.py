from __future__ import annotations

import asyncio
import hashlib
import json
import re
import subprocess
import sys
from collections import deque
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from rapidocr_onnxruntime import RapidOCR
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.models import GuideSource
from app.db.session import SessionLocal, init_db
from app.schemas.guides import GuideCreateRequest
from app.services.guide_ingest_service import GuideIngestService, clean_text, split_chunks
from app.services.weibo_crawler_service import WEIBO_GUIDE_INDEX_URL


ROOT_DIR = Path(__file__).resolve().parents[3]
FETCHER_PATH = Path(__file__).resolve().with_name("weibo_rendered_fetcher.cjs")
OCR_CACHE_DIR = ROOT_DIR / "logs" / "weibo_ocr_cache"
POST_URL_PATTERN = re.compile(r"^https://weibo\.com/7896659368/[A-Za-z0-9]+$")
CONTENT_PATTERN = re.compile(
    r"\u53d1\u5e03\u4e8e[^\n]*\n(?:\u5df2\u7f16\u8f91\n)?\u5173\u6ce8\n([\s\S]*?)\n\u5206\u4eab\u8fd9\u6761\u535a\u6587"
)
NOISE_LINE_PATTERNS = (
    re.compile(r"^\d+$"),
    re.compile(
        r"^(\u767b\u5f55|\u6ce8\u518c|\u65e0\u969c\u788d|\u63a8\u8350|\u70ed\u95e8\u63a8\u8350|\u70ed\u95e8\u699c\u5355|\u5fae\u535a\u70ed\u641c|\u6211\u7684|\u70ed\u641c|\u6587\u5a31|\u751f\u6d3b|\u793e\u4f1a|\u8fd4\u56de)$"
    ),
    re.compile(
        r"^(\u5e2e\u52a9\u4e2d\u5fc3|\u5fae\u535a\u5ba2\u670d|\u81ea\u52a9\u670d\u52a1\u4e2d\u5fc3|\u5e38\u89c1\u95ee\u9898|\u5408\u4f5c&\u670d\u52a1|\u5fae\u535a\u8425\u9500|\u5f00\u653e\u5e73\u53f0|\u4e3e\u62a5\u4e2d\u5fc3).*$"
    ),
)
NOISE_TITLE_KEYWORDS = ("随时随地发现新鲜事", "微博正文")
NOISE_CONTENT_KEYWORDS = (
    "登录/注册",
    "关于微博",
    "帮助中心",
    "微博客服",
    "自助服务中心",
    "合作热线",
    "查看完整热搜榜单",
    "信息网络传播视听节目许可证",
)
CATEGORY_MAPPING = [
    ("\u6c5f\u6d59\u6caa", "\u6c5f\u6d59\u6caa"),
    ("\u7ca4\u6e2f\u6fb3", "\u7ca4\u6e2f\u6fb3"),
    ("\u4e91\u5357", "\u4e91\u5357"),
    ("\u53f0\u6e7e", "\u53f0\u6e7e"),
    ("\u5ddd\u6e1d", "\u5ddd\u6e1d"),
    ("\u5317\u4eac", "\u5317\u4eac"),
    ("\u5c71\u4e1c", "\u5c71\u4e1c"),
    ("\u6c5f\u897f", "\u6c5f\u897f"),
    ("\u8d35\u5dde", "\u8d35\u5dde"),
    ("\u798f\u5efa", "\u798f\u5efa"),
    ("\u897f\u85cf", "\u897f\u85cf"),
    ("\u9752\u6d77\u7518\u8083", "\u9752\u6d77\u7518\u8083"),
    ("\u897f\u5317", "\u897f\u5317"),
    ("\u65b0\u7586", "\u65b0\u7586"),
    ("\u9ed1\u5409\u8fbd", "\u4e1c\u5317"),
    ("\u5185\u8499", "\u5185\u8499\u53e4"),
    ("\u6e56\u5317", "\u6e56\u5317"),
    ("\u6cb3\u5357", "\u6cb3\u5357"),
    ("\u5c71\u897f", "\u5c71\u897f"),
    ("\u5e7f\u897f", "\u5e7f\u897f"),
    ("\u6cb3\u5317", "\u6cb3\u5317"),
    ("\u5929\u6d25", "\u5929\u6d25"),
    ("\u6e56\u5357", "\u6e56\u5357"),
    ("\u5b89\u5fbd", "\u5b89\u5fbd"),
    ("\u6d77\u5357", "\u6d77\u5357"),
    ("\u97e9\u56fd", "\u97e9\u56fd"),
    ("\u4e1c\u5357\u4e9a", "\u4e1c\u5357\u4e9a"),
    ("\u9713\u8679", "\u65e5\u672c"),
    ("\u706b\u8f66", "\u957f\u9014\u706b\u8f66"),
    ("\u4f4f\u5bbf", "\u51fa\u884c\u4f4f\u5bbf"),
    ("\u65c5\u884c\u7528\u54c1", "\u65c5\u884c\u7528\u54c1"),
    ("solo", "solo trip"),
]


@dataclass
class RenderedPage:
    """保存渲染后页面的主内容、子链接和图片。"""

    final_url: str
    body_text: str
    child_links: list[str]
    image_urls: list[str]


def safe_console_text(value: object) -> str:
    """兼容 Windows 终端编码，避免控制台打印中断导入。"""

    text = str(value)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, errors="ignore").decode(encoding, errors="ignore")


def normalize_post_url(url: str) -> str | None:
    """统一微博正文地址，去掉 query 便于去重。"""

    parsed = urlparse(url)
    candidate = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return candidate if POST_URL_PATTERN.match(candidate) else None


def fetch_rendered_page(url: str) -> RenderedPage:
    """调用 Playwright 抓取浏览器渲染后的微博正文。"""

    result = subprocess.run(
        ["node", str(FETCHER_PATH), url],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"fetcher failed for {url}")

    payload = json.loads(result.stdout)
    final_url = normalize_post_url(payload["finalUrl"]) or url
    child_links: list[str] = []
    seen_links: set[str] = set()
    for link in payload.get("childLinks", []):
        normalized = normalize_post_url(link)
        if normalized and normalized != final_url and normalized not in seen_links:
            seen_links.add(normalized)
            child_links.append(normalized)

    return RenderedPage(
        final_url=final_url,
        body_text=str(payload.get("bodyText") or ""),
        child_links=child_links,
        image_urls=[str(item) for item in payload.get("imageUrls", [])],
    )


def extract_main_text(body_text: str) -> str:
    """从微博整页文本中截出正文区域。"""

    normalized = body_text.replace("\r", "").strip()
    match = CONTENT_PATTERN.search(normalized)
    content = match.group(1).strip() if match else normalized
    cleaned_lines: list[str] = []
    for raw_line in content.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if any(pattern.match(line) for pattern in NOISE_LINE_PATTERNS):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


def build_title(main_text: str, fallback_url: str) -> str:
    """从正文开头提取可读标题。"""

    for line in main_text.splitlines():
        candidate = re.sub(r"^[0-9. ]+", "", line).strip(" -_#")
        candidate = candidate.replace("\u5fae\u535a\u6b63\u6587", "").strip()
        candidate = candidate.replace("\u200b", "").replace("\ufeff", "").strip()
        if len(candidate) >= 4:
            return candidate[:80]
    return f"\u5fae\u535a\u653b\u7565 {fallback_url.rsplit('/', 1)[-1]}"


def infer_category(title: str, text: str) -> str:
    """根据标题和正文给攻略打一个轻量分类。"""

    combined = f"{title}\n{text}"
    for keyword, category in CATEGORY_MAPPING:
        if keyword in combined:
            return category
    return "\u5fae\u535a\u653b\u7565"


def ocr_image(image_url: str, engine: RapidOCR, index: int) -> str:
    """下载图片并执行 OCR，返回文本结果。"""

    OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(urlparse(image_url).path).suffix or ".jpg"
    local_path = OCR_CACHE_DIR / f"weibo_image_{index}{ext}"
    with httpx.Client(timeout=40, follow_redirects=True) as client:
        response = client.get(image_url)
        response.raise_for_status()
        image_bytes = response.content
        local_path.write_bytes(image_bytes)

    best_text = ""
    best_score = -1
    for variant_path in build_ocr_variants(local_path, image_bytes):
        result, _ = engine(str(variant_path))
        if not result:
            continue
        cleaned_text = clean_ocr_text([str(item[1]).strip() for item in result if str(item[1]).strip()])
        score = score_ocr_text(cleaned_text)
        if score > best_score:
            best_score = score
            best_text = cleaned_text
    return best_text


def build_ocr_variants(local_path: Path, image_bytes: bytes) -> list[Path]:
    """为长图生成 OCR 增强版本，提高图片攻略的文字提取质量。"""

    variant_paths = [local_path]
    try:
        image = Image.open(BytesIO(image_bytes)).convert("RGB")
        grayscale = ImageOps.grayscale(image)
        contrast = ImageEnhance.Contrast(grayscale).enhance(1.8)
        sharpened = contrast.filter(ImageFilter.SHARPEN)
        enlarged = sharpened.resize(
            (max(1, sharpened.width * 2), max(1, sharpened.height * 2)),
            Image.Resampling.LANCZOS,
        )
        enhanced_path = local_path.with_name(f"{local_path.stem}_enhanced.png")
        enlarged.save(enhanced_path)
        variant_paths.append(enhanced_path)
    except Exception:
        # 图像增强失败时回退到原图，不影响主流程。
        return variant_paths
    return variant_paths


def clean_ocr_text(lines: list[str]) -> str:
    """清洗 OCR 文本，降低页码、水印和碎片噪声对攻略库的污染。"""

    cleaned: list[str] = []
    seen: set[str] = set()
    for raw_line in lines:
        line = re.sub(r"\s+", " ", raw_line).strip()
        line = line.replace("微博正文", "").replace("图片OCR：", "").strip()
        if not line:
            continue
        if re.fullmatch(r"[0-9/|·•\\-_=]+", line):
            continue
        if len(line) <= 1:
            continue
        if len(re.findall(r"[\u4e00-\u9fff]", line)) == 0 and len(line) < 6:
            continue
        if re.search(r"(登录|注册|关于微博|帮助中心|微博客服|合作热线|查看完整热搜榜单)", line):
            continue
        compact = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", line)
        if len(compact) < 2:
            continue
        if line in seen:
            continue
        seen.add(line)
        cleaned.append(line)
    return "\n".join(cleaned[:240]).strip()


def score_ocr_text(text: str) -> int:
    """给 OCR 文本打轻量质量分，优先保留更像攻略正文的结果。"""

    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    useful_lines = sum(1 for line in text.splitlines() if len(line.strip()) >= 4)
    return chinese_chars + useful_lines * 6


def build_ingest_content(main_text: str, image_urls: list[str], engine: RapidOCR, ocr_index_seed: int) -> str:
    """把微博文字和图片 OCR 结果拼成可入库正文。"""

    content_parts = [main_text] if main_text else []
    if len(main_text) < 220 and image_urls:
        ocr_texts: list[str] = []
        for image_offset, image_url in enumerate(image_urls[:5]):
            ocr_text = ocr_image(image_url, engine, ocr_index_seed * 10 + image_offset)
            if ocr_text and len(ocr_text) >= 40:
                ocr_texts.append(ocr_text)
        if ocr_texts:
            content_parts.append("\u56fe\u7247OCR\uff1a\n" + "\n\n".join(ocr_texts))
    return "\n\n".join(part for part in content_parts if part).strip()


def is_noise_title(title: str) -> bool:
    """过滤微博登录壳页、无意义标题。"""

    compact = re.sub(r"\s+", "", title)
    if not compact or len(compact) < 4:
        return True
    return any(keyword in compact for keyword in NOISE_TITLE_KEYWORDS)


def is_noise_content(content: str) -> bool:
    """过滤微博页脚、热搜壳页和缺乏正文信息的页面。"""

    compact = clean_text(content)
    if len(compact) < 80:
        return True

    chinese_chars = re.findall(r"[\u4e00-\u9fff]", compact)
    if len(chinese_chars) < 40:
        return True

    keyword_hits = sum(1 for keyword in NOISE_CONTENT_KEYWORDS if keyword in compact)
    if keyword_hits >= 2:
        return True

    lines = [line.strip() for line in compact.splitlines() if line.strip()]
    if not lines:
        return True

    short_lines = sum(1 for line in lines if len(line) <= 8)
    if short_lines / max(len(lines), 1) > 0.55:
        return True

    return False


def has_duplicate_chunk(db, content: str) -> bool:
    """在入库前检查是否会撞上已有分片哈希。"""

    for chunk in split_chunks(clean_text(content)):
        digest = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
        exists = db.execute(
            text("SELECT 1 FROM guide_chunks WHERE content_hash = :digest LIMIT 1"),
            {"digest": digest},
        ).first()
        if exists:
            return True
    return False


async def main() -> None:
    """递归采集微博合集中的公开攻略并写入知识库。"""

    init_db()
    db = SessionLocal()
    engine = RapidOCR()
    queue: deque[str] = deque([WEIBO_GUIDE_INDEX_URL])
    visited: set[str] = set()
    fetched = 0
    imported = 0
    skipped_existing = 0
    skipped_short = 0
    skipped_noise = 0
    skipped_duplicate = 0

    try:
        while queue:
            url = normalize_post_url(queue.popleft()) or WEIBO_GUIDE_INDEX_URL
            if url in visited:
                continue
            visited.add(url)

            print(safe_console_text(f"FETCH {len(visited)}: {url}"))
            page = fetch_rendered_page(url)
            fetched += 1

            for child_link in page.child_links:
                if child_link not in visited:
                    queue.append(child_link)

            exists = (
                db.query(GuideSource)
                .filter(GuideSource.raw_url == page.final_url)
                .first()
            )
            if exists:
                skipped_existing += 1
                continue

            main_text = extract_main_text(page.body_text)
            title = build_title(main_text, page.final_url)
            content = build_ingest_content(main_text, page.image_urls, engine, fetched)
            if len(content) < 60:
                skipped_short += 1
                continue
            if is_noise_title(title) or is_noise_content(content):
                skipped_noise += 1
                print(safe_console_text(f"SKIP NOISE: {page.final_url}"))
                continue
            if has_duplicate_chunk(db, content):
                skipped_duplicate += 1
                print(safe_console_text(f"SKIP DUPLICATE: {page.final_url}"))
                continue

            category = infer_category(title, content)
            try:
                GuideIngestService(db).add_guide(
                    GuideCreateRequest(
                        title=title,
                        content=content[:30000],
                        source_url=page.final_url,
                        source_type="weibo_rendered",
                        category=category,
                        raw_url=page.final_url,
                        resolved_url=page.final_url,
                        crawl_status="indexed",
                    )
                )
            except IntegrityError:
                db.rollback()
                skipped_duplicate += 1
                print(safe_console_text(f"SKIP DUPLICATE TX: {page.final_url}"))
                continue
            imported += 1
            print(safe_console_text(f"IMPORTED {imported}: {title}"))

        total_sources = db.query(GuideSource).count()
        print(
            json.dumps(
                {
                    "fetched_pages": fetched,
                    "imported_guides": imported,
                    "skipped_existing": skipped_existing,
                    "skipped_short": skipped_short,
                    "skipped_noise": skipped_noise,
                    "skipped_duplicate": skipped_duplicate,
                    "total_guide_sources": total_sources,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
