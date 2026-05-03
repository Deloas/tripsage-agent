import {
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
  ChevronsUpDown,
  DatabaseZap,
  Layers3,
  Link2,
  MapPinned,
  PanelRightOpen,
  RefreshCw,
  Search,
  Sparkles,
  X,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { fetchGuideDetail, fetchGuideLibrary } from "../lib/api";
import type { GuideDetail, GuideLibraryResult, GuideSourceItem } from "../lib/types";

interface KnowledgeBaseWorkbenchProps {
  guideSources: GuideSourceItem[];
  guideResult?: string | null;
  crawlLoading: boolean;
  onAddGuide: () => void;
  onCrawlWeibo: () => void;
  onUseGuide: (guide: GuideDetail) => void;
}

const PAGE_SIZE = 12;

const emptyLibraryResult: GuideLibraryResult = {
  items: [],
  total: 0,
  limit: PAGE_SIZE,
  offset: 0,
  filters: {
    source_types: [],
    cities: [],
    categories: [],
  },
};

export function KnowledgeBaseWorkbench({
  guideSources,
  guideResult,
  crawlLoading,
  onAddGuide,
  onCrawlWeibo,
  onUseGuide,
}: KnowledgeBaseWorkbenchProps) {
  const [library, setLibrary] = useState<GuideLibraryResult>(emptyLibraryResult);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [keywordDraft, setKeywordDraft] = useState("");
  const [keyword, setKeyword] = useState("");
  const [city, setCity] = useState("");
  const [category, setCategory] = useState("");
  const [sourceType, setSourceType] = useState("");
  const [sortBy, setSortBy] = useState<"latest" | "oldest" | "city_hot" | "source_priority">("latest");
  const [page, setPage] = useState(1);
  const [selectedGuideId, setSelectedGuideId] = useState<number | null>(null);
  const [selectedGuide, setSelectedGuide] = useState<GuideDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const indexedCount = guideSources.filter((item) => item.crawl_status === "indexed").length;
  const failedCount = guideSources.filter((item) => item.crawl_status === "failed" || item.crawl_status === "blocked").length;
  const pendingCount = guideSources.filter((item) => item.crawl_status === "pending").length;

  const totalPages = Math.max(1, Math.ceil(library.total / PAGE_SIZE));
  const visiblePages = buildVisiblePages(page, totalPages);

  useEffect(() => {
    let cancelled = false;

    async function loadLibrary() {
      setLoading(true);
      setError(null);
      try {
        const result = await fetchGuideLibrary({
          keyword: keyword || undefined,
          city: city || undefined,
          category: category || undefined,
          source_type: sourceType || undefined,
          sort_by: sortBy,
          limit: PAGE_SIZE,
          offset: (page - 1) * PAGE_SIZE,
        });
        if (!cancelled) {
          setLibrary(result);
        }
      } catch {
        if (!cancelled) {
          setError("攻略库暂时无法加载，请确认后端服务已经启动。");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadLibrary();
    return () => {
      cancelled = true;
    };
  }, [category, city, keyword, page, sortBy, sourceType]);

  useEffect(() => {
    if (!selectedGuideId) {
      setSelectedGuide(null);
      return;
    }
    const guideId = selectedGuideId;
    let cancelled = false;
    async function loadGuideDetail() {
      setDetailLoading(true);
      try {
        const result = await fetchGuideDetail(guideId);
        if (!cancelled) {
          setSelectedGuide(result);
        }
      } catch {
        if (!cancelled) {
          setSelectedGuide(null);
        }
      } finally {
        if (!cancelled) {
          setDetailLoading(false);
        }
      }
    }
    void loadGuideDetail();
    return () => {
      cancelled = true;
    };
  }, [selectedGuideId]);

  function applyKeyword(event: FormEvent) {
    event.preventDefault();
    setPage(1);
    setKeyword(keywordDraft.trim());
  }

  function resetFilters() {
    setKeywordDraft("");
    setKeyword("");
    setCity("");
    setCategory("");
    setSourceType("");
    setSortBy("latest");
    setPage(1);
  }

  function handleUseSelectedGuide() {
    if (!selectedGuide) return;
    onUseGuide(selectedGuide);
    setSelectedGuideId(null);
  }

  const filterSummary = useMemo(() => {
    const parts = [
      sourceType ? `来源 ${sourceType}` : null,
      city ? `地区 ${city}` : null,
      category ? `分类 ${category}` : null,
      keyword ? `关键词 ${keyword}` : null,
    ].filter(Boolean);
    return parts.length ? parts.join(" · ") : "全部攻略";
  }, [category, city, keyword, sourceType]);

  const structured = selectedGuide?.structured;

  return (
    <section className="page-band knowledge-library-band" aria-label="攻略库工作台">
      <div className="knowledge-library-head">
        <div>
          <div className="section-kicker">
            <DatabaseZap size={15} />
            攻略库工作台
          </div>
          <h3>本地攻略检索、筛选与规划复用</h3>
          <p>把攻略库做成可检索、可复核、可加入规划的正式知识资产，而不是只展示一段摘要。</p>
        </div>
        <div className="knowledge-library-actions">
          <button type="button" className="secondary-action" onClick={onAddGuide}>
            <Sparkles size={15} />
            添加攻略
          </button>
          <button type="button" className="primary-action" onClick={onCrawlWeibo} disabled={crawlLoading}>
            <RefreshCw size={15} className={crawlLoading ? "spin" : ""} />
            {crawlLoading ? "正在补采" : "继续补采微博"}
          </button>
        </div>
      </div>

      <div className="knowledge-library-signal-grid">
        <MetricCard label="攻略总数" value={String(library.total)} detail={filterSummary} />
        <MetricCard label="已入库源" value={String(indexedCount)} detail={`异常 ${failedCount} · 待处理 ${pendingCount}`} />
        <MetricCard label="来源类型" value={String(library.filters.source_types.length)} detail="手动入库与微博采集统一管理" />
        <MetricCard label="覆盖分类" value={String(library.filters.categories.length)} detail="支持地区、分类、来源交叉筛选" />
      </div>

      {guideResult ? <div className="knowledge-library-feedback">{guideResult}</div> : null}

      <div className="knowledge-library-shell">
        <aside className="knowledge-library-sidebar">
          <form className="knowledge-search-box" onSubmit={applyKeyword}>
            <label className="knowledge-search-input">
              <Search size={15} />
              <input
                value={keywordDraft}
                onChange={(event) => setKeywordDraft(event.target.value)}
                placeholder="搜索城市、玩法、预算、景点、美食"
              />
            </label>
            <button type="submit" className="primary-action">检索</button>
          </form>

          <div className="knowledge-filter-grid">
            <label>
              <span>来源类型</span>
              <select value={sourceType} onChange={(event) => { setSourceType(event.target.value); setPage(1); }}>
                <option value="">全部来源</option>
                {library.filters.source_types.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label} · {item.count}
                  </option>
                ))}
              </select>
            </label>

            <label>
              <span>地区 / 城市</span>
              <select value={city} onChange={(event) => { setCity(event.target.value); setPage(1); }}>
                <option value="">全部地区</option>
                {library.filters.cities.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label} · {item.count}
                  </option>
                ))}
              </select>
            </label>

            <label>
              <span>分类</span>
              <select value={category} onChange={(event) => { setCategory(event.target.value); setPage(1); }}>
                <option value="">全部分类</option>
                {library.filters.categories.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label} · {item.count}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="knowledge-filter-actions">
            <button type="button" className="secondary-action" onClick={resetFilters}>清空筛选</button>
            <span>{filterSummary}</span>
          </div>

          <div className="knowledge-facet-clusters">
            <FacetCluster
              title="热门分类"
              items={library.filters.categories.slice(0, 8)}
              onPick={(value) => {
                setCategory(value);
                setPage(1);
              }}
            />
            <FacetCluster
              title="热门地区"
              items={library.filters.cities.slice(0, 8)}
              onPick={(value) => {
                setCity(value);
                setPage(1);
              }}
            />
          </div>
        </aside>

        <div className="knowledge-library-main">
          <div className="knowledge-library-toolbar">
            <div>
              <strong>{library.total}</strong>
              <span> 条符合条件的攻略</span>
            </div>
            <div className="knowledge-toolbar-actions">
              <label className="knowledge-sort-select">
                <ChevronsUpDown size={14} />
                <select value={sortBy} onChange={(event) => { setSortBy(event.target.value as typeof sortBy); setPage(1); }}>
                  <option value="latest">最新入库</option>
                  <option value="oldest">最早入库</option>
                  <option value="city_hot">热门地区优先</option>
                  <option value="source_priority">来源优先级</option>
                </select>
              </label>
              <em>
                第 {page} / {totalPages} 页 · 每页 {PAGE_SIZE} 条
              </em>
            </div>
          </div>

          {error ? <div className="knowledge-library-empty danger">{error}</div> : null}

          {!error ? (
            <div className="knowledge-guide-grid">
              {loading
                ? Array.from({ length: 6 }).map((_, index) => (
                  <article className="knowledge-guide-card skeleton" key={`skeleton-${index}`}>
                    <div className="knowledge-guide-badges">
                      <span />
                      <span />
                      <span />
                    </div>
                    <strong />
                    <p />
                    <p />
                    <div className="knowledge-guide-footer">
                      <span />
                      <span />
                    </div>
                  </article>
                ))
                : library.items.map((guide) => (
                  <article className="knowledge-guide-card" key={guide.id}>
                    <div className="knowledge-guide-badges">
                      <span>{guide.city}</span>
                      <span>{guide.category || "未分类"}</span>
                      <span>{guide.source_type || "local"}</span>
                    </div>
                    <strong>{guide.title}</strong>
                    <p>{guide.summary}</p>
                    <div className="knowledge-guide-footer">
                      <span>{guide.crawl_status || "indexed"}</span>
                      <div className="knowledge-guide-actions">
                        <button type="button" className="guide-inline-action" onClick={() => setSelectedGuideId(guide.id)}>
                          <PanelRightOpen size={14} />
                          查看详情
                        </button>
                        {guide.source_url ? (
                          <a href={guide.source_url} target="_blank" rel="noreferrer">
                            查看来源
                            <ArrowUpRight size={14} />
                          </a>
                        ) : (
                          <em>本地条目</em>
                        )}
                      </div>
                    </div>
                  </article>
                ))}
            </div>
          ) : null}

          {!loading && !error && !library.items.length ? (
            <div className="knowledge-library-empty">
              <Layers3 size={18} />
              <span>当前筛选条件下没有攻略，换一个地区、分类或关键词试试。</span>
            </div>
          ) : null}

          <div className="knowledge-pagination">
            <button type="button" className="secondary-action" disabled={page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))}>
              <ChevronLeft size={14} />
              上一页
            </button>
            <div className="knowledge-page-pills">
              {visiblePages.map((item) => (
                <button
                  type="button"
                  key={item}
                  className={`knowledge-page-pill ${item === page ? "active" : ""}`}
                  onClick={() => setPage(item)}
                >
                  {item}
                </button>
              ))}
            </div>
            <button type="button" className="secondary-action" disabled={page >= totalPages} onClick={() => setPage((current) => Math.min(totalPages, current + 1))}>
              下一页
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      </div>

      {selectedGuideId ? (
        <div className="knowledge-detail-overlay" role="dialog" aria-modal="true" aria-label="攻略详情">
          <button type="button" className="knowledge-detail-backdrop" onClick={() => setSelectedGuideId(null)} aria-label="关闭攻略详情" />
          <aside className="knowledge-detail-drawer">
            <div className="knowledge-detail-head">
              <div>
                <div className="section-kicker">
                  <DatabaseZap size={15} />
                  攻略详情
                </div>
                <h4>{selectedGuide?.title || "正在加载"}</h4>
                <div className="knowledge-detail-meta">
                  <span>{selectedGuide?.city || "未知城市"}</span>
                  <span>{selectedGuide?.category || "未分类"}</span>
                  <span>{selectedGuide?.source_type || "local"}</span>
                </div>
              </div>
              <div className="knowledge-detail-head-actions">
                {selectedGuide ? (
                  <button type="button" className="primary-action" onClick={handleUseSelectedGuide}>
                    <Sparkles size={15} />
                    加入当前规划
                  </button>
                ) : null}
                <button type="button" className="icon-button" onClick={() => setSelectedGuideId(null)} aria-label="关闭详情">
                  <X size={16} />
                </button>
              </div>
            </div>

            {detailLoading ? <div className="knowledge-detail-loading">正在加载攻略详情...</div> : null}

            {!detailLoading && selectedGuide ? (
              <div className="knowledge-detail-body">
                <div className="knowledge-detail-stat-grid">
                  <MetricCard label="摘要切片" value={String(selectedGuide.chunk_count)} detail="用于本地检索与命中展示" />
                  <MetricCard label="地点抽取" value={String(selectedGuide.places.length)} detail="供地图、路线与规划复用" />
                  <MetricCard label="建议天数" value={String(selectedGuide.days || structured?.days || "-")} detail="从标题与正文自动抽取" />
                </div>

                <section className="knowledge-detail-section">
                  <div className="knowledge-detail-section-head">
                    <strong>结构化信息</strong>
                    {selectedGuide.source_url ? (
                      <a href={selectedGuide.source_url} target="_blank" rel="noreferrer">
                        <Link2 size={14} />
                        打开来源
                      </a>
                    ) : (
                      <span>本地入库条目</span>
                    )}
                  </div>
                  <div className="knowledge-structured-grid">
                    <StructuredBlock title="预算参考" value={structured?.budget_range || formatBudgetRange(selectedGuide.budget_min, selectedGuide.budget_max) || "未识别"} />
                    <StructuredBlock title="交通建议" value={joinDisplay(structured?.transport_modes) || "未识别"} />
                    <StructuredBlock title="住宿建议" value={joinDisplay(structured?.lodging_suggestions) || "未识别"} />
                    <StructuredBlock title="玩法风格" value={joinDisplay(structured?.travel_style_tags) || selectedGuide.travel_style || "未识别"} />
                  </div>
                  <div className="knowledge-structured-columns">
                    <StructuredList title="核心景点" items={structured?.scenic_spots || []} />
                    <StructuredList title="美食线索" items={structured?.food_spots || []} />
                  </div>
                </section>

                <section className="knowledge-detail-section">
                  <div className="knowledge-detail-section-head">
                    <strong>正文</strong>
                    <span>{structured?.summary || selectedGuide.summary}</span>
                  </div>
                  <div className="knowledge-detail-content">
                    {(selectedGuide.content || "暂无正文").split(/\n{1,2}/).filter(Boolean).map((line, index) => (
                      <p key={`${index}-${line.slice(0, 18)}`}>{line}</p>
                    ))}
                  </div>
                </section>

                <section className="knowledge-detail-section">
                  <div className="knowledge-detail-section-head">
                    <strong>命中切片</strong>
                    <span>{selectedGuide.chunks.length} 条</span>
                  </div>
                  <div className="knowledge-detail-chunks">
                    {selectedGuide.chunks.map((chunk) => (
                      <article className="knowledge-detail-chunk" key={chunk.id}>
                        <span>片段 {chunk.chunk_index + 1}</span>
                        <p>{chunk.content}</p>
                      </article>
                    ))}
                  </div>
                </section>

                <section className="knowledge-detail-section">
                  <div className="knowledge-detail-section-head">
                    <strong>地点抽取</strong>
                    <span>{selectedGuide.places.length} 个</span>
                  </div>
                  <div className="knowledge-detail-places">
                    {selectedGuide.places.length ? selectedGuide.places.map((place) => (
                      <div className="knowledge-place-pill" key={`${place.name}-${place.place_type || ""}`}>
                        <MapPinned size={14} />
                        <div>
                          <strong>{place.name}</strong>
                          <span>{place.place_type || "地点"}</span>
                        </div>
                      </div>
                    )) : <div className="knowledge-facet-empty">当前还没有抽取到地点。</div>}
                  </div>
                </section>
              </div>
            ) : null}
          </aside>
        </div>
      ) : null}
    </section>
  );
}

function MetricCard({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <article className="knowledge-metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
      <p>{detail}</p>
    </article>
  );
}

function FacetCluster({
  title,
  items,
  onPick,
}: {
  title: string;
  items: Array<{ value: string; label: string; count: number }>;
  onPick: (value: string) => void;
}) {
  return (
    <div className="knowledge-facet-cluster">
      <div className="knowledge-facet-title">{title}</div>
      <div className="knowledge-facet-pills">
        {items.length ? items.map((item) => (
          <button type="button" key={item.value} onClick={() => onPick(item.value)}>
            {item.label}
            <span>{item.count}</span>
          </button>
        )) : <span className="knowledge-facet-empty">暂无聚类</span>}
      </div>
    </div>
  );
}

function StructuredBlock({ title, value }: { title: string; value: string }) {
  return (
    <article className="knowledge-structured-card">
      <span>{title}</span>
      <strong>{value}</strong>
    </article>
  );
}

function StructuredList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="knowledge-structured-list">
      <span>{title}</span>
      {items.length ? (
        <div className="knowledge-structured-tags">
          {items.map((item) => (
            <span key={item}>{item}</span>
          ))}
        </div>
      ) : (
        <div className="knowledge-facet-empty">暂无提取结果</div>
      )}
    </div>
  );
}

function joinDisplay(items?: string[] | null) {
  return items?.filter(Boolean).join(" · ") || "";
}

function formatBudgetRange(min?: number | null, max?: number | null) {
  if (min == null && max == null) return "";
  if (min != null && max != null) {
    return min === max ? `约 ${min} 元` : `${min}-${max} 元`;
  }
  if (min != null) return `约 ${min} 元起`;
  return `约 ${max} 元`;
}

function buildVisiblePages(page: number, totalPages: number) {
  if (totalPages <= 5) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }
  if (page <= 3) {
    return [1, 2, 3, 4, 5];
  }
  if (page >= totalPages - 2) {
    return [totalPages - 4, totalPages - 3, totalPages - 2, totalPages - 1, totalPages];
  }
  return [page - 2, page - 1, page, page + 1, page + 2];
}
