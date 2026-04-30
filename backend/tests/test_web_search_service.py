import json
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.db.models import ApiCache
from app.services.web_search_service import (
    BingHtmlParser,
    DuckDuckGoHtmlParser,
    WebSearchResult,
    WebSearchService,
)


def test_duckduckgo_parser_extracts_title_url_and_snippet() -> None:
    """DuckDuckGo HTML 解析器应能提取标题、链接和摘要。"""
    sample = """
    <div class="result results_links">
      <div class="links_main">
        <h2>
          <a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.com%2Ftrip">
            苏州两天一夜攻略
          </a>
        </h2>
        <a class="result__snippet" href="/l/?uddg=https%3A%2F%2Fexample.com%2Ftrip">
          园林、平江路和高铁周末路线。
        </a>
      </div>
    </div>
    """
    parser = DuckDuckGoHtmlParser()
    parser.feed(sample)
    parser.close()

    assert parser.results
    assert "苏州" in parser.results[0]["title"]
    assert "example.com" in parser.results[0]["url"]
    assert "高铁" in parser.results[0]["snippet"]


def test_web_search_url_filter_blocks_private_and_script_urls() -> None:
    """联网搜索来源必须屏蔽本地、内网和脚本协议。"""
    service = WebSearchService()

    assert service._url_allowed("https://example.com/travel") is True
    assert service._url_allowed("javascript:alert(1)") is False
    assert service._url_allowed("file:///C:/secret.txt") is False
    assert service._url_allowed("http://127.0.0.1:8000/admin") is False
    assert service._url_allowed("http://192.168.1.2/debug") is False


def test_web_search_quality_ranking_prefers_relevant_clean_result() -> None:
    """联网搜索排序应优先展示标题干净且与查询相关的结果。"""
    service = WebSearchService()
    noisy = WebSearchResult(
        title="zhihu.comhttps://www.zhihu.com › question",
        snippet="一些旅行内容",
        url="https://www.zhihu.com/question/1",
        provider="bing",
        domain="www.zhihu.com",
    )
    clean = WebSearchResult(
        title="苏州两天一夜旅行攻略",
        snippet="苏州园林、平江路、美食和高铁路线安排。",
        url="https://www.mafengwo.cn/suzhou",
        provider="bing",
        domain="www.mafengwo.cn",
    )

    ranked = service._clean_results([noisy, clean], top_k=2, query="苏州 两天一夜 攻略")

    assert ranked[0].title == "苏州两天一夜旅行攻略"


def test_bing_parser_extracts_result_items() -> None:
    """Bing HTML 备用源也应能解析标准搜索结果结构。"""
    sample = """
    <li class="b_algo">
      <h2><a href="https://example.cn/nanjing">南京三天两夜攻略</a></h2>
      <div class="b_caption"><p>秦淮河、博物馆和本地美食路线。</p></div>
    </li>
    """
    parser = BingHtmlParser()
    parser.feed(sample)
    parser.close()

    assert parser.results
    assert parser.results[0]["url"] == "https://example.cn/nanjing"
    assert "南京" in parser.results[0]["title"]
    assert "秦淮河" in parser.results[0]["snippet"]


def test_web_search_config_status_does_not_expose_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """联网搜索诊断信息不能泄露 API Key 明文。"""
    monkeypatch.setattr(settings, "web_search_api_key", "secret-web-key")
    status = WebSearchService().config_status()

    assert status["has_api_key"] is True
    assert "secret-web-key" not in str(status)
    assert "api_key" not in status


def test_web_search_cache_roundtrip(db_session) -> None:
    """联网搜索结果应能写入并读取 SQLite 缓存。"""
    service = WebSearchService(db_session)
    query = "苏州 两天一夜 攻略"
    result = WebSearchResult(title="苏州攻略", snippet="园林与街巷", url="https://example.com/suzhou")

    service._write_cache(query, 1, [result])
    cached = service._read_cache(query, 1)

    assert cached is not None
    assert cached[0].title == "苏州攻略"
    assert cached[0].url == "https://example.com/suzhou"


def test_web_search_expired_cache_returns_none(db_session) -> None:
    """过期缓存不能被联网搜索继续使用。"""
    service = WebSearchService(db_session)
    query = "南京 三日游 攻略"
    cache_key = service._cache_key(query, 2)
    db_session.add(
        ApiCache(
            provider="web_search",
            cache_key=cache_key,
            request_json=json.dumps({"query": query}, ensure_ascii=False),
            response_json="[]",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
    )
    db_session.commit()

    assert service._read_cache(query, 2) is None
