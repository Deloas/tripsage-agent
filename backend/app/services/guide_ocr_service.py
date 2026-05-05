from __future__ import annotations

import hashlib
import json
import re
import time
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from app.core.config import ROOT_DIR


OCR_CACHE_DIR = ROOT_DIR / "logs" / "guide_ocr_cache"


class GuideOcrService:
    """图片型攻略 OCR 服务，用于长图攻略、图文混排攻略的正文兜底。"""

    def __init__(self) -> None:
        self._engine = None
        self.last_run_stats: dict = {}

    def available(self) -> bool:
        """判断当前环境是否具备 OCR 能力。"""
        try:
            import rapidocr_onnxruntime  # noqa: F401
        except Exception:  # noqa: BLE001
            return False
        return True

    def extract_from_images(
        self,
        image_urls: list[str],
        seed: str,
        limit: int | None = 5,
        *,
        max_seconds: float = 150,
        min_coverage_ratio: float = 0.85,
        min_text_length: int = 40,
    ) -> list[str]:
        """从图片 URL 列表中提取 OCR 文本。

        中文注释：攻略导入是产品链路，不能只识别前几张图；这里按时间预算尽量覆盖全部图片，
        同时用文本缓存避免重复导入同一条微博时再次跑重型 OCR。
        """
        start_at = time.monotonic()
        self.last_run_stats = {
            "available": self.available(),
            "image_total": len(image_urls or []),
            "target_count": 0,
            "processed_count": 0,
            "success_count": 0,
            "cached_count": 0,
            "elapsed_seconds": 0,
            "coverage_ratio": 0,
            "image_results": [],
        }
        if not image_urls or not self.available():
            return []

        unique_urls = self._unique_urls(image_urls)
        target_count = min(len(unique_urls), limit if limit is not None else len(unique_urls))
        self.last_run_stats["target_count"] = target_count
        texts: list[str] = []

        for index, image_url in enumerate(unique_urls[:target_count]):
            elapsed = time.monotonic() - start_at
            required_processed = max(1, int(target_count * min_coverage_ratio + 0.999))
            if elapsed >= max_seconds and self.last_run_stats["processed_count"] >= required_processed:
                break

            result = self._ocr_image_with_stats(image_url, f"{seed}_{index}")
            self.last_run_stats["processed_count"] += 1
            self.last_run_stats["image_results"].append(
                {
                    "index": index,
                    "url": image_url,
                    "cached": result["cached"],
                    "text_length": len(re.sub(r"\s+", "", result["text"] or "")),
                    "score": result["score"],
                }
            )
            if result["cached"]:
                self.last_run_stats["cached_count"] += 1
            text = result["text"]
            if text and len(re.sub(r"\s+", "", text)) >= min_text_length:
                texts.append(text)
                self.last_run_stats["success_count"] += 1

        self.last_run_stats["elapsed_seconds"] = round(time.monotonic() - start_at, 2)
        self.last_run_stats["coverage_ratio"] = round(
            self.last_run_stats["processed_count"] / max(1, target_count),
            3,
        )
        return texts

    def _ocr_image(self, image_url: str, cache_key: str) -> str:
        """下载图片并执行 OCR，返回清洗后的最佳文本。"""
        return self._ocr_image_with_stats(image_url, cache_key)["text"]

    def _ocr_image_with_stats(self, image_url: str, cache_key: str) -> dict:
        """识别单张图片，并返回文本、评分与缓存状态。"""
        OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        ext = Path(urlparse(image_url).path).suffix or ".jpg"
        safe_key = self._safe_cache_key(self._url_digest(image_url))
        local_path = OCR_CACHE_DIR / f"guide_image_{safe_key}{ext}"
        text_cache_path = OCR_CACHE_DIR / f"guide_image_{safe_key}.ocr.txt"
        meta_cache_path = OCR_CACHE_DIR / f"guide_image_{safe_key}.ocr.json"

        cached_text = self._read_text_cache(text_cache_path)
        if cached_text:
            return {
                "text": cached_text,
                "score": self.score_ocr_text(cached_text),
                "cached": True,
            }

        try:
            with httpx.Client(timeout=18, follow_redirects=True) as client:
                response = client.get(image_url)
                response.raise_for_status()
                image_bytes = response.content
            local_path.write_bytes(image_bytes)
        except Exception:  # noqa: BLE001
            return {"text": "", "score": 0, "cached": False}

        best_text = ""
        best_score = -1
        for variant_path in self._build_ocr_variants(local_path, image_bytes):
            try:
                result, _ = self._get_engine()(str(variant_path))
            except Exception:  # noqa: BLE001
                continue
            if not result:
                continue
            cleaned_text = self.clean_ocr_text([str(item[1]).strip() for item in result if str(item[1]).strip()])
            score = self.score_ocr_text(cleaned_text)
            if score > best_score:
                best_score = score
                best_text = cleaned_text
        if best_text:
            text_cache_path.write_text(best_text, encoding="utf-8")
            meta_cache_path.write_text(
                json.dumps(
                    {
                        "url": image_url,
                        "score": best_score,
                        "text_length": len(re.sub(r"\s+", "", best_text)),
                        "created_at": time.time(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        return {"text": best_text, "score": max(best_score, 0), "cached": False}

    def _get_engine(self):
        """懒加载 OCR 引擎，避免普通导入路径额外耗时。"""
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR

            self._engine = RapidOCR()
        return self._engine

    def _build_ocr_variants(self, local_path: Path, image_bytes: bytes) -> list[Path]:
        """为长图生成增强版本，提高小字、列表与长页识别率。"""
        variant_paths: list[Path] = []
        try:
            image = self._fit_image_for_import_ocr(Image.open(BytesIO(image_bytes)).convert("RGB"))
            normalized_path = local_path.with_name(f"{local_path.stem}_normalized.png")
            image.save(normalized_path)
            variant_paths.append(normalized_path)
            for variant_name, variant_image in self._iter_preprocessed_images(image):
                enhanced_path = local_path.with_name(f"{local_path.stem}_{variant_name}.png")
                variant_image.save(enhanced_path)
                variant_paths.append(enhanced_path)
                for tile_index, tile_image in enumerate(self._split_tall_image(variant_image, max_tiles=2)):
                    tile_path = local_path.with_name(f"{local_path.stem}_{variant_name}_tile_{tile_index}.png")
                    tile_image.save(tile_path)
                    variant_paths.append(tile_path)
                    if len(variant_paths) >= 4:
                        return variant_paths
        except Exception:  # noqa: BLE001
            return variant_paths
        return variant_paths[:4]

    def _fit_image_for_import_ocr(self, image: Image.Image) -> Image.Image:
        """中文注释：导入场景优先响应速度，把超大长图压到 OCR 友好的尺寸再识别。"""
        max_width = 900
        max_height = 2600
        ratio = min(max_width / max(1, image.width), max_height / max(1, image.height), 1)
        if ratio >= 1:
            return image
        return image.resize(
            (max(1, int(image.width * ratio)), max(1, int(image.height * ratio))),
            Image.Resampling.LANCZOS,
        )

    def _iter_preprocessed_images(self, image: Image.Image) -> list[tuple[str, Image.Image]]:
        """生成多种适合 OCR 的图像增强版本。"""
        grayscale = ImageOps.grayscale(image)
        contrast = ImageEnhance.Contrast(grayscale).enhance(1.8)
        sharpened = contrast.filter(ImageFilter.SHARPEN)
        binary = sharpened.point(lambda value: 255 if value > 172 else 0)
        return [
            ("enhanced", sharpened),
            ("binary", binary),
        ]

    def _split_tall_image(self, image: Image.Image, max_tiles: int = 4) -> list[Image.Image]:
        """把长图按垂直方向切片，降低整张长图一次识别时的漏字。"""
        if image.height <= image.width * 2.2:
            return []
        tile_count = min(max_tiles, max(2, round(image.height / max(1, image.width * 1.6))))
        tile_height = max(image.width * 2, image.height // tile_count)
        overlap = max(48, image.width // 8)
        tiles: list[Image.Image] = []
        top = 0
        while top < image.height and len(tiles) < max_tiles:
            bottom = min(image.height, top + tile_height)
            tiles.append(image.crop((0, top, image.width, bottom)))
            if bottom >= image.height:
                break
            top = max(0, bottom - overlap)
        return tiles

    def clean_ocr_text(self, lines: list[str]) -> str:
        """清洗 OCR 文本，尽量去掉水印、页脚与互动区噪音。"""
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw_line in lines:
            line = re.sub(r"\s+", " ", raw_line).strip()
            line = line.replace("微博正文", "").replace("图片OCR：", "").strip()
            if not line or len(line) <= 1:
                continue
            if re.fullmatch(r"[0-9/|路•·\-_=]+", line):
                continue
            if len(re.findall(r"[\u4e00-\u9fff]", line)) == 0 and len(line) < 6:
                continue
            if re.search(r"(登录|注册|关于微博|帮助中心|微博客服|合作热线|查看完整热搜榜单)", line):
                continue
            compact = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", line)
            if len(compact) < 2 or compact in seen:
                continue
            seen.add(compact)
            cleaned.append(line)
        return "\n".join(cleaned[:320]).strip()

    def score_ocr_text(self, text: str) -> int:
        """给 OCR 文本做轻量质量评分，优先保留更像攻略正文的结果。"""
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        useful_lines = sum(1 for line in text.splitlines() if len(line.strip()) >= 4)
        travel_hits = sum(
            1
            for term in ("攻略", "路线", "景点", "交通", "住宿", "美食", "预算", "门票", "行程", "出发")
            if term in text
        )
        paragraph_bonus = 18 if useful_lines >= 5 else 0
        return chinese_chars + useful_lines * 6 + travel_hits * 20 + paragraph_bonus

    def _safe_cache_key(self, value: str) -> str:
        """把任意缓存键转成安全文件名。"""
        return re.sub(r"[^A-Za-z0-9_-]", "_", value)[:80]

    def _url_digest(self, value: str) -> str:
        """中文注释：URL 摘要用于稳定缓存同一张远程图片的 OCR 结果。"""
        return hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:16]

    def _read_text_cache(self, path: Path) -> str:
        """读取 OCR 文本缓存。"""
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
        return text if len(re.sub(r"\s+", "", text)) >= 20 else ""

    def _unique_urls(self, urls: list[str]) -> list[str]:
        """保持顺序去重图片链接。"""
        results: list[str] = []
        seen: set[str] = set()
        for url in urls:
            if not url or url in seen:
                continue
            seen.add(url)
            results.append(url)
        return results
